# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates gcc build-essential curl tzdata &&     rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (speed up rebuilds)
COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

# Copy app (user will place their code here)
COPY . .

# Create a non-root user
RUN useradd -ms /bin/bash appuser && mkdir -p /data && chown -R appuser:appuser /app /data
USER appuser

# Default data dir
ENV DATABASE_URL=sqlite+aiosqlite:///data/bot.db

# Entrypoint
# NOTE: replace "bot.main" with your actual module if different.
CMD ["python", "-m", "bot.main"]
