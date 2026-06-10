FROM python:3.11-slim

WORKDIR /app

# Build context is the repo root (see docker-compose.openrouter.yml).
COPY services/standup-extractor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/standup-extractor/app ./app

RUN useradd -r -s /bin/false appuser
USER appuser

EXPOSE 8086

# No curl in the image — probe with the stdlib instead.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8086/health').status==200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8086", "--no-access-log"]
