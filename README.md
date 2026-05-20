# YTNotes - AI-Powered YouTube Note Generator

Generate AI-powered notes from YouTube videos with automatic transcription, summarization, and organization.

## Overview

- FastAPI backend
- PostgreSQL database
- Redis for caching and rate-limiting
- Uvicorn for running the app in Docker

## Prerequisites

- Docker & Docker Compose
- Python 3.13 (for local dev virtualenv tasks)

## Quickstart (Docker)

1. Copy environment example and customize values:

```bash
cp .env.example .env
# Edit .env to set secrets and credentials
```

2. Start services:

```bash
docker-compose up -d --build
```

3. Run database migrations (inside the web container):

```bash
docker-compose exec web uv run alembic upgrade head
```

4. Open the app at `http://localhost:8000`.

## Local Development (optional)

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies (using `uv`):

```bash
uv sync
```

3. Set `DATABASE_URL` in `.env` to a local Postgres or use Docker DB above.

4. Run locally:

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Important Environment Variables

- `DATABASE_URL` - e.g. `postgresql://user:pass@db:5432/dbname` (used by the app)
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` - used by the Postgres container to initialise the DB
- `REDIS_URL` - Redis connection string
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` - Google OAuth
- `OPENAI_API_KEY` - OpenAI API key
- `JWT_SECRET`, `SECRET` - application secrets
- `PADDLE_API_KEY`, `PADDLE_WEBHOOK_SECRET` - Paddle payment keys

Add more variables in `.env` as necessary (see `.env` file for full list).

## Viewing Logs

- Follow container logs:

```bash
docker-compose logs -f web
```

- The app also writes to `logs/app.log` in the project root. To tail it:

```bash
tail -f logs/app.log
```

## Database Access

- List tables using `psql` inside the DB container:

```bash
docker-compose exec db psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dt"
```

## Common Troubleshooting

- `Couldn't connect to localhost:8000`:
  - Ensure `docker-compose ps` shows `web` running and ports mapped (`0.0.0.0:8000->8000/tcp`).
  - Inspect logs: `docker-compose logs -f web` and `tail -f logs/app.log`.

- `DATABASE_URL` missing in settings:
  - Ensure `DATABASE_URL` exists in `.env`. The app reads the env file using Pydantic settings.

- Port conflicts (6379 or 5432):
  - Stop local services using those ports or change ports in `docker-compose.yml`.

## Useful Commands

```bash
# Start services in background
docker-compose up -d

# Stop and remove containers
docker-compose down

# Remove volumes (clears DB) and restart
docker-compose down -v
docker-compose up -d

# Run migrations inside container
docker-compose exec web uv run alembic upgrade head

# Run tests
pytest
```

## Notes

- This repository runs the app with Uvicorn inside Docker for simplicity. For production use, consider adding a reverse proxy and process manager.

---

If you'd like, I can commit this README update and also add a `Makefile` with shortcuts for the commands above.
