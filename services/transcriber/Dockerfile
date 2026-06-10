FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Build context is the repo root (see docker-compose.azure.yml).
COPY services/azure-transcriber/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/azure-transcriber/app ./app

RUN useradd -r -s /bin/false appuser
USER appuser

EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8085/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085"]
