from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.core.settings import settings

# Create limiter instance with Redis backend
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
    storage_uri=str(settings.REDIS_URL),
    enabled=settings.RATE_LIMIT_ENABLED,
)

async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": "60"},
    )

def setup_rate_limiting(app):
    """Add rate limiting middleware to FastAPI app"""
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)  # ← add this



# Only trust your specific proxy IP
# uv run uvicorn main:app --proxy-headers --forwarded-allow-ips="203.0.113.10"