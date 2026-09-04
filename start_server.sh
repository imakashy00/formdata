#!/usr/bin/env bash
set -e

# If .venv or uvicorn is missing, install uv and sync packages
if [ ! -f .venv/bin/uvicorn ]; then
    echo "Virtualenv not found. Bootstrapping environment..."
    if ! command -v uv >/dev/null 2>&1 && [ ! -f /usr/local/bin/uv ] && [ ! -f /root/.local/bin/uv ]; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    UV_BIN="$(command -v uv 2>/dev/null || echo "")"
    if [ -z "$UV_BIN" ]; then
        if [ -f /usr/local/bin/uv ]; then
            UV_BIN="/usr/local/bin/uv"
        elif [ -f /root/.local/bin/uv ]; then
            UV_BIN="/root/.local/bin/uv"
        fi
    fi
    "$UV_BIN" sync
fi

exec ./.venv/bin/uvicorn main:app --host 0.0.0.0 --port 3000
