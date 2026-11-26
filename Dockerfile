FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml README.md ./
COPY aisupport_ml/ aisupport_ml/
COPY softline_backend/ softline_backend/
RUN python -m pip install --no-cache-dir '.[backend]' \
    && useradd --system --no-create-home app
WORKDIR /
USER app
