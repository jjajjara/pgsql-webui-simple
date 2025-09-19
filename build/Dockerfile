# 1. Python 3.11-slim 버전을 기반 이미지로 사용
FROM python:3.11-slim

# 2. 작업 디렉토리 설정
WORKDIR /app

# 3. 필요한 Python 패키지를 설치하기 위해 requirements.txt 복사
COPY requirements.txt .

# 4. pip를 사용하여 패키지 설치
# --no-cache-dir: 불필요한 캐시를 남기지 않아 이미지 크기를 줄임
# -r requirements.txt: 해당 파일에 명시된 모든 패키지를 설치
RUN pip install --no-cache-dir -r requirements.txt

# 5. 현재 디렉토리의 모든 파일(.dockerignore에 명시된 파일 제외)을 컨테이너의 /app 디렉토리로 복사
COPY . .

# 6. 컨테이너가 8000번 포트에서 리스닝하도록 설정
# 이 포트는 uvicorn 서버가 실행될 포트와 일치해야 함
EXPOSE 8000

# 7. 컨테이너가 시작될 때 실행할 기본 명령어 설정
# uvicorn을 사용하여 main.py 파일의 app 객체를 실행
# --host 0.0.0.0: 컨테이너 외부에서도 접근 가능하도록 설정
# --port 8000: 8000번 포트에서 서버 실행
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
