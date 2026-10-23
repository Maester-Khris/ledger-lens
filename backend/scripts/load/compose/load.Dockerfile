# Load-test image (named load.Dockerfile: the repo ignores plain Dockerfile). API set only (no Docling): the same packages Railway installs. Code is mounted read-only by docker-compose.yml.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
# Trivy DS-0002 (N8 F3): run as a non-root user; the mounted code is read-only, so the user needs no write access.
RUN useradd --create-home --uid 10001 app
USER app
# Trivy DS-0026 (N8 F4): both services serve GET /health; the mock overrides HEALTH_PORT in compose.yaml.
ENV HEALTH_PORT=8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"HEALTH_PORT\"]}/health', timeout=2)"
