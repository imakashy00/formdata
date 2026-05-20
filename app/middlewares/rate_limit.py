from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from app.core.settings import settings


# Create limiter instance with Redis backend
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.RATE_LIMIT_PER_MINUTE}/minute"],
    storage_uri=settings.REDIS_URL,
    enabled=settings.RATE_LIMIT_ENABLED,
)


def setup_rate_limiting(app):
    """Add rate limiting middleware to FastAPI app"""
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
