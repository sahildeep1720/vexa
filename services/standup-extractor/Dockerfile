FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Build context is the repo root (see docker-compose.azure.yml).
COPY services/standup-extractor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/standup-extractor/app ./app

RUN useradd -r -s /bin/false appuser
USER appuser

EXPOSE 8086

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8086/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8086"]
