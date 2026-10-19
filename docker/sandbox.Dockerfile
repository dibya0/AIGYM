# Local sandbox (docker compose --profile sandbox up sandbox redis): the same FastAPI app Vercel runs.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "uvicorn>=0.30" "redis>=5.0"
COPY paygym ./paygym
COPY ruleset ./ruleset
EXPOSE 8000
CMD ["uvicorn", "paygym.sandbox.app:app", "--host", "0.0.0.0", "--port", "8000"]
