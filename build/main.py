import os
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any
import psycopg2
import psycopg2.extras  # <--- 오류 해결을 위해 이 라인을 추가했습니다.
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

# .env 파일에서 환경변수 로드
load_dotenv()

# --- 환경변수 읽기 ---
DATABASE_URL = os.getenv("DATABASE_URL")
TABLES_ENV = os.getenv("TABLES")
table_names = [table.strip() for table in TABLES_ENV.split(',')] if TABLES_ENV else []
PORT = int(os.getenv("PORT", 8000))

# --- 데이터베이스 연결 풀 설정 ---
if not DATABASE_URL:
    raise Exception("DATABASE_URL 환경 변수가 설정되지 않았습니다.")

# 연결 풀 생성 (minconn=1, maxconn=5)
pool = SimpleConnectionPool(1, 5, dsn=DATABASE_URL)

# --- FastAPI 애플리케이션 설정 ---
app = FastAPI()

# 정적 파일 (HTML, JS, CSS) 제공을 위한 마운트
app.mount("/static", StaticFiles(directory="public"), name="static")

# 테이블 스키마 정보를 저장할 딕셔너리
table_schemas = {}

# --- 데이터베이스 연결 의존성 ---
def get_db_connection():
    """연결 풀에서 데이터베이스 커넥션을 가져오는 의존성 함수"""
    conn = None
    try:
        conn = pool.getconn()
        yield conn
    finally:
        if conn:
            pool.putconn(conn)

# --- 서버 시작 시 스키마 정보 로드 ---
@app.on_event("startup")
async def startup_event():
    """서버 시작 시 테이블 스키마 정보를 미리 불러옵니다."""
    print('관리 대상 테이블 스키마를 가져옵니다:', table_names)
    conn = None
    try:
        conn = pool.getconn()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            for table_name in table_names:
                try:
                    query = """
                        SELECT
                            c.column_name,
                            c.data_type,
                            c.is_nullable,
                            (SELECT COUNT(*)
                             FROM information_schema.table_constraints tc
                             JOIN information_schema.key_column_usage kcu
                             ON tc.constraint_name = kcu.constraint_name
                             WHERE tc.table_name = c.table_name
                             AND tc.constraint_type = 'PRIMARY KEY'
                             AND kcu.column_name = c.column_name
                            ) = 1 as is_primary_key
                        FROM
                            information_schema.columns c
                        WHERE
                            c.table_name = %s
                            AND c.table_schema = 'public'
                        ORDER BY
                            c.ordinal_position;
                    """
                    cur.execute(query, (table_name,))
                    rows = [dict(row) for row in cur.fetchall()]
                    if rows:
                        primary_key = next((col['column_name'] for col in rows if col['is_primary_key']), None)
                        table_schemas[table_name] = {
                            "columns": rows,
                            "primaryKey": primary_key,
                        }
                        print(f"'{table_name}' 테이블 스키마 로드 완료. 기본 키: {primary_key or '없음'}")
                    else:
                        print(f"경고: '{table_name}' 테이블을 찾을 수 없거나 컬럼이 없습니다.")
                except Exception as e:
                    print(f"'{table_name}' 테이블 스키마 조회 중 오류:", e)
    finally:
        if conn:
            pool.putconn(conn)
    if not table_names:
        print('경고: .env 파일에 "TABLES" 환경 변수가 설정되지 않았습니다. 관리할 테이블이 없습니다.')


# --- API 라우트 ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """메인 HTML 페이지를 반환합니다."""
    with open("public/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/schema")
async def get_schema():
    """테이블 목록과 스키마 정보를 반환합니다."""
    if not table_schemas:
        raise HTTPException(status_code=404, detail="관리할 테이블이 없거나 스키마를 불러올 수 없습니다.")
    return {"tables": table_names, "schemas": table_schemas}

@app.get("/api/data/{table}")
async def get_data(table: str, conn=Depends(get_db_connection)):
    """특정 테이블의 모든 데이터를 조회합니다."""
    if table not in table_names:
        raise HTTPException(status_code=404, detail="알 수 없는 테이블입니다.")
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(f'SELECT * FROM "{table}"')
            result = [dict(row) for row in cur.fetchall()]
            return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"데이터 조회 중 오류: {e}")

@app.post("/api/data/{table}")
async def create_data(table: str, request: Request, conn=Depends(get_db_connection)):
    """새로운 데이터를 테이블에 추가합니다."""
    if table not in table_names:
        raise HTTPException(status_code=404, detail="알 수 없는 테이블입니다.")

    data = await request.json()
    columns = data.keys()
    values = data.values()

    cols_str = ", ".join([f'"{col}"' for col in columns])
    vals_str = ", ".join(["%s"] * len(values))

    query = f'INSERT INTO "{table}" ({cols_str}) VALUES ({vals_str}) RETURNING *'

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, list(values))
            new_record = dict(cur.fetchone())
            conn.commit()
            return JSONResponse(content=new_record, status_code=201)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"데이터 추가 중 오류: {e}")


@app.put("/api/data/{table}/{item_id}")
async def update_data(table: str, item_id: str, request: Request, conn=Depends(get_db_connection)):
    """기존 데이터를 수정합니다."""
    schema = table_schemas.get(table)
    if not schema or not schema.get("primaryKey"):
        raise HTTPException(status_code=400, detail="기본 키가 정의되지 않은 테이블은 수정할 수 없습니다.")

    primary_key = schema["primaryKey"]
    data = await request.json()

    # 기본 키는 업데이트 대상에서 제외
    data.pop(primary_key, None)

    columns = data.keys()
    values = list(data.values())

    set_clause = ", ".join([f'"{col}" = %s' for col in columns])
    query = f'UPDATE "{table}" SET {set_clause} WHERE "{primary_key}" = %s RETURNING *'

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, values + [item_id])
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="해당 ID의 데이터를 찾을 수 없습니다.")
            updated_record = dict(cur.fetchone())
            conn.commit()
            return updated_record
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"데이터 수정 중 오류: {e}")


@app.delete("/api/data/{table}/{item_id}")
async def delete_data(table: str, item_id: str, conn=Depends(get_db_connection)):
    """데이터를 삭제합니다."""
    schema = table_schemas.get(table)
    if not schema or not schema.get("primaryKey"):
        raise HTTPException(status_code=400, detail="기본 키가 정의되지 않은 테이블은 삭제할 수 없습니다.")

    primary_key = schema["primaryKey"]
    query = f'DELETE FROM "{table}" WHERE "{primary_key}" = %s'

    try:
        with conn.cursor() as cur:
            cur.execute(query, (item_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="해당 ID의 데이터를 찾을 수 없습니다.")
            conn.commit()
            return JSONResponse(content={}, status_code=204)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"데이터 삭제 중 오류: {e}")

# --- Uvicorn 서버 실행 (개발용) ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
