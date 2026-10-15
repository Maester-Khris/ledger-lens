# Load-test image (named load.Dockerfile: the repo ignores plain Dockerfile). API set only (no Docling): the same packages Railway installs. Code is mounted read-only by docker-compose.yml.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
