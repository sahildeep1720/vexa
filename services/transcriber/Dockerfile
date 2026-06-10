FROM python:3.11-slim

WORKDIR /app

# Build context is the repo root (see docker-compose.openrouter.yml).
COPY services/transcriber/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/transcriber/app ./app

RUN useradd -r -s /bin/false appuser
USER appuser

EXPOSE 8085

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8085/health')"]

# Per-chunk POSTs make access logs the dominant noise; failures still logged by app loggers.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8085", "--no-access-log"]
