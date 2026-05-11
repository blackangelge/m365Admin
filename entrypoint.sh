#!/bin/sh
# Uvicorn-Startskript — aktiviert --reload automatisch wenn APP_DEBUG=true
set -e

if [ "${APP_DEBUG:-false}" = "true" ]; then
    echo "[startup] Debug-Modus aktiv: uvicorn startet mit --reload"
    echo "[startup] Dateiänderungen in /app werden automatisch erkannt."
    exec uvicorn app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --proxy-headers \
        --forwarded-allow-ips='*' \
        --reload \
        --reload-dir /app
else
    echo "[startup] Produktions-Modus: uvicorn ohne --reload"
    exec uvicorn app.main:app \
        --host 0.0.0.0 \
        --port 8000 \
        --proxy-headers \
        --forwarded-allow-ips='*'
fi
