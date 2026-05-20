#!/bin/sh
set -e

# Activate virtual environment
. /app/.venv/bin/activate

echo "🔄 Running database migrations..."

MAX_RETRIES=${MIGRATION_RETRIES:-30}
SLEEP=${MIGRATION_SLEEP:-2}

i=0

until alembic upgrade head; do
    i=$((i+1))

    echo "⏳ Migration attempt $i/$MAX_RETRIES failed. Retrying in ${SLEEP}s..."

    if [ "$i" -ge "$MAX_RETRIES" ]; then
        echo "❌ Migrations failed after $MAX_RETRIES attempts."
        exit 1
    fi

    sleep "$SLEEP"
done

echo "✅ Migrations applied."

echo "🚀 Starting FastAPI..."

exec uv run uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --reload