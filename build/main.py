import os
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from typing import List, Dict, Any
import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Read environment variables ---
DATABASE_URL = os.getenv("DATABASE_URL")
TABLES_ENV = os.getenv("TABLES")
table_names = [table.strip() for table in TABLES_ENV.split(',')] if TABLES_ENV else []
PORT = int(os.getenv("PORT", 8000))

# --- Database connection pool setup ---
if not DATABASE_URL:
    raise Exception("DATABASE_URL environment variable is not set.")

# Create connection pool (minconn=1, maxconn=5)
pool = SimpleConnectionPool(1, 5, dsn=DATABASE_URL)

# --- FastAPI application setup ---
app = FastAPI()

# Mount for serving static files (HTML, JS, CSS)
app.mount("/static", StaticFiles(directory="public"), name="static")

# Dictionary to store table schema information
table_schemas = {}

# --- Database connection dependency ---
def get_db_connection():
    """Dependency function to get a database connection from the pool"""
    conn = None
    try:
        conn = pool.getconn()
        yield conn
    finally:
        if conn:
            pool.putconn(conn)

# --- Load schema information on server startup ---
@app.on_event("startup")
async def startup_event():
    """Pre-loads table schema information on server startup."""
    print('Fetching schemas for tables:', table_names)
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
                        print(f"'{table_name}' schema loaded. Primary key: {primary_key or 'None'}")
                    else:
                        print(f"Warning: Table '{table_name}' not found or has no columns.")
                except Exception as e:
                    print(f"Error fetching schema for table '{table_name}':", e)
    finally:
        if conn:
            pool.putconn(conn)
    if not table_names:
        print('Warning: "TABLES" environment variable not set in .env file. No tables to manage.')


# --- API Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Returns the main HTML page."""
    with open("public/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/api/schema")
async def get_schema():
    """Returns the list of tables and their schemas."""
    if not table_schemas:
        raise HTTPException(status_code=404, detail="No tables to manage or schemas could not be loaded.")
    return {"tables": table_names, "schemas": table_schemas}

@app.get("/api/data/{table}")
async def get_data(table: str, conn=Depends(get_db_connection), sort_by: str = None, sort_order: str = 'asc'):
    """Retrieves and sorts data for a specific table."""
    if table not in table_names:
        raise HTTPException(status_code=404, detail="Unknown table.")

    schema = table_schemas.get(table)
    if not schema:
        raise HTTPException(status_code=404, detail="Table schema not found.")

    order_by_clause = ""
    if sort_by:
        valid_columns = [col['column_name'] for col in schema['columns']]
        if sort_by not in valid_columns:
            raise HTTPException(status_code=400, detail="Invalid sort column.")

        if sort_order.lower() not in ['asc', 'desc']:
            raise HTTPException(status_code=400, detail="Invalid sort order.")

        order_by_clause = f'ORDER BY "{sort_by}" {sort_order.upper()}'
    else:
        primary_key = schema.get("primaryKey")
        if primary_key:
            order_by_clause = f'ORDER BY "{primary_key}" ASC'

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            query = f'SELECT * FROM "{table}" {order_by_clause}'
            cur.execute(query)
            result = [dict(row) for row in cur.fetchall()]
            return jsonable_encoder(result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching data: {e}")

@app.post("/api/data/{table}")
async def create_data(table: str, request: Request, conn=Depends(get_db_connection)):
    """Adds a new record to the table."""
    if table not in table_names:
        raise HTTPException(status_code=404, detail="Unknown table.")

    data = await request.json()
    columns = data.keys()
    values = data.values()

    cols_str = ", ".join([f'"{col}"' for col in columns])
    vals_str = ", ".join(["%s"] * len(values))

    query = f'INSERT INTO "{table}" ({cols_str}) VALUES ({vals_str}) RETURNING *'

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, list(values))
            new_record = cur.fetchone()
            conn.commit()
            return JSONResponse(content=jsonable_encoder(new_record), status_code=201)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error adding data: {e}")


@app.put("/api/data/{table}/{item_id}")
async def update_data(table: str, item_id: str, request: Request, conn=Depends(get_db_connection)):
    """Updates an existing record."""
    schema = table_schemas.get(table)
    if not schema or not schema.get("primaryKey"):
        raise HTTPException(status_code=400, detail="Cannot update a table with no primary key defined.")

    primary_key = schema["primaryKey"]
    data = await request.json()

    data.pop(primary_key, None)

    columns = data.keys()
    values = list(data.values())

    set_clause = ", ".join([f'"{col}" = %s' for col in columns])
    query = f'UPDATE "{table}" SET {set_clause} WHERE "{primary_key}" = %s RETURNING *'

    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, values + [item_id])
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Record with the specified ID not found.")
            updated_record = cur.fetchone()
            conn.commit()
            return jsonable_encoder(updated_record)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating data: {e}")


@app.delete("/api/data/{table}/{item_id}")
async def delete_data(table: str, item_id: str, conn=Depends(get_db_connection)):
    """Deletes a record."""
    schema = table_schemas.get(table)
    if not schema or not schema.get("primaryKey"):
        raise HTTPException(status_code=400, detail="Cannot delete from a table with no primary key defined.")

    primary_key = schema["primaryKey"]
    query = f'DELETE FROM "{table}" WHERE "{primary_key}" = %s'

    try:
        with conn.cursor() as cur:
            cur.execute(query, (item_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Record with the specified ID not found.")
            conn.commit()
            return JSONResponse(content={}, status_code=204)
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting data: {e}")

# --- Uvicorn server execution (for development) ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
