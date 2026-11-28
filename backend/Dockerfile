FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py docker-entrypoint.sh ./

ENTRYPOINT ["/bin/sh", "/app/docker-entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--root-path", "/api", "--timeout-graceful-shutdown", "5"]
