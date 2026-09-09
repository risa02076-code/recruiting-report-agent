FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 배포 환경에는 data/*.db가 없으므로(gitignore), 시작할 때 합성 데이터를 새로 만든다.
# app_state.db(실행 이력/인사이트)는 컨테이너가 재배포될 때마다 비워진다 — 무료 호스팅의
# 흔한 제약이라 README/PRD 11장에 명시해뒀다.
CMD ["sh", "-c", "python -m app.generate_synthetic_data && python -m uvicorn app.web.main:app --host 0.0.0.0 --port ${PORT:-8800}"]
