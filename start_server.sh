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

# Ensure local PostgreSQL daemon is running
if ! pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
    mkdir -p /var/run/postgresql && chown -R postgres:postgres /var/run/postgresql 2>/dev/null || true
    if [ ! -d /var/lib/postgresql/data/base ]; then
        useradd -m -s /bin/bash postgres 2>/dev/null || true
        mkdir -p /var/lib/postgresql/data
        chown -R postgres:postgres /var/lib/postgresql
        su - postgres -c "/usr/lib/postgresql/15/bin/initdb -D /var/lib/postgresql/data"
    fi
    su - postgres -c "/usr/lib/postgresql/15/bin/pg_ctl -D /var/lib/postgresql/data -l /var/lib/postgresql/logfile start" || true
    su - postgres -c "/usr/lib/postgresql/15/bin/psql -c \"CREATE USER username WITH PASSWORD 'password' SUPERUSER;\"" 2>/dev/null || true
    su - postgres -c "/usr/lib/postgresql/15/bin/createdb -O username dbname" 2>/dev/null || true
fi

exec ./.venv/bin/uvicorn main:app --host 0.0.0.0 --port 3000
