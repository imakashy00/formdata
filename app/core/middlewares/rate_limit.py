# from fastapi import Request
# from fastapi.responses import JSONResponse
# from slowapi import Limiter
# from slowapi.errors import RateLimitExceeded
# from slowapi.middleware import SlowAPIMiddleware
# from slowapi.util import get_remote_address

# from app.core.settings import settings

# # Create limiter instance with Redis backend
# limiter = Limiter(
#     key_func=get_remote_address,
#     default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
#     storage_uri=str(settings.REDIS_URL),
#     enabled=settings.RATE_LIMIT_ENABLED,
# )


# async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
#     return JSONResponse(
#         status_code=429,
#         content={"detail": "Rate limit exceeded. Try again later."},
#         headers={"Retry-After": "60"},
#     )


# def setup_rate_limiting(app):
#     """Add rate limiting middleware to FastAPI app"""
#     app.state.limiter = limiter
#     app.add_middleware(SlowAPIMiddleware)
#     app.add_exception_handler(
#         RateLimitExceeded, rate_limit_exceeded_handler
#     )  # ← add this


# # Only trust your specific proxy IP
# # uv run uvicorn main:app --proxy-headers --forwarded-allow-ips="203.0.113.10"

"""Postgres-backed fixed-window rate limiter — replaces slowapi's Redis
storage backend. `limits`/slowapi has no Postgres storage option, so this
is a small hand-rolled FastAPI dependency instead of a `storage_uri` swap.

Honest trade-off: this adds one DB round trip per request. Redis answers
this from memory in well under a millisecond; Postgres — especially a Neon
compute waking from scale-to-zero — will be slower and adds load to your
primary database. Fine at moderate traffic. If you're doing very high QPS,
an in-memory store (even a small Redis/Upstash instance dedicated to just
this) will scale better than routing rate-limit checks through Postgres.

Usage, per route:

    from fastapi import Depends
    from app.services.rate_limiter import rate_limit

    @router.post("/login", dependencies=[Depends(rate_limit(limit=5, window_seconds=60))])
    async def login(...): ...

Usage, app-wide (equivalent to slowapi's `default_limits`):

    app = FastAPI(dependencies=[Depends(rate_limit(limit=100, window_seconds=60))])
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request
from sqlalchemy import CursorResult, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.settings import settings
from app.models.user import RateLimitBucket


def _bucket_start(now: datetime, window_seconds: int) -> datetime:
    epoch = int(now.timestamp())
    bucket = epoch - (epoch % window_seconds)
    return datetime.fromtimestamp(bucket, tz=UTC)


def rate_limit(limit: int, window_seconds: int = 60, key_prefix: str = "global"):
    async def dependency(
        request: Request, db: Annotated[AsyncSession, Depends(get_db)]
    ) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return

        client_ip = request.client.host if request.client else "unknown"
        bucket_key = f"{key_prefix}:{client_ip}"
        now = datetime.now(UTC)
        window_start = _bucket_start(now, window_seconds)

        # Atomic increment: Postgres serializes concurrent ON CONFLICT DO
        # UPDATE on the same row, so this is race-free without app-level locking.
        stmt = (
            pg_insert(RateLimitBucket)
            .values(bucket_key=bucket_key, window_start=window_start, request_count=1)
            .on_conflict_do_update(
                index_elements=[
                    RateLimitBucket.bucket_key,
                    RateLimitBucket.window_start,
                ],
                set_={"request_count": RateLimitBucket.request_count + 1},
            )
            .returning(RateLimitBucket.request_count)
        )
        try:
            result = await db.execute(stmt)
            await db.commit()
            count = result.scalar_one()

            if count > limit:
                retry_after = window_seconds - (int(now.timestamp()) % window_seconds)
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
        except HTTPException:
            raise
        except Exception:
            if settings.ENV == "development":
                return
            raise

    return dependency


async def cleanup_expired_buckets(
    db: AsyncSession, older_than: timedelta = timedelta(hours=1)
) -> int:
    cutoff = datetime.now(UTC) - older_than
    result = await db.execute(
        delete(RateLimitBucket).where(RateLimitBucket.window_start < cutoff)
    )
    await db.commit()
    return cast(CursorResult, result).rowcount or 0


