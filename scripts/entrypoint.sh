#!/bin/sh
# entrypoint.sh — runtime bootstrap for the Children's Story Studio container.
#
# Seeding the demo stories used to live here as a `cp -Rn` on top of an
# Azure Files mount.  With the storage backend abstraction (see
# backend/app/storage/) seeding is now done in Python during FastAPI's
# startup hook (`seed_demo_stories_if_empty`) so it works identically for
# both the local-filesystem and Azure-Blob backends.
#
# All this script does is exec uvicorn so signals (SIGTERM from App Service)
# reach Python directly via tini.

set -eu

: "${PORT:=8000}"

echo "[entrypoint] Starting uvicorn on 0.0.0.0:$PORT"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers --forwarded-allow-ips="*"
