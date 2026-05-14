# syntax=docker/dockerfile:1.7
#
# Multi-stage build for Children's Story Studio.
#
#   Stage 1 (frontend-build): build the Vite/React SPA into /app/dist
#   Stage 2 (runtime):        Python 3.12 + FastAPI/uvicorn, copies the
#                             built SPA in and serves it from the same origin
#                             as the API.
#
# Designed for Azure App Service for Linux (custom container) but runs
# anywhere Docker runs.

# ─── Stage 1: build the React frontend ────────────────────────────────────────
FROM node:20-bookworm-slim AS frontend-build

WORKDIR /app

# Install dependencies first (cached layer)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund

# Copy sources and build
COPY frontend/ ./
RUN npm run build


# ─── Stage 2: Python runtime ──────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

# Azure App Service health probes / Speech SDK need a few system libs.
# - libssl3, ca-certificates: TLS
# - libasound2: required by azure-cognitiveservices-speech
# - tini: clean PID-1 signal handling
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libssl3 \
        libasound2 \
        tini \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # App config defaults — overridden by App Service settings
    PORT=8000 \
    FRONTEND_DIST_DIR=/app/frontend/dist \
    DEMO_STORIES_DIR=/home/data/demo_stories \
    SEED_DEMO_STORIES_DIR=/app/backend/demo_stories

WORKDIR /app

# Install Python deps (cached on requirements.txt changes)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install -r /app/backend/requirements.txt

# Copy backend source
COPY backend/ /app/backend/

# Copy built frontend from stage 1
COPY --from=frontend-build /app/dist /app/frontend/dist

# Entrypoint: seeds demo stories into the persistent mount, then exec uvicorn
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /app/backend

# App Service injects $PORT (defaults to 8000). EXPOSE is informational.
EXPOSE 8000

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
