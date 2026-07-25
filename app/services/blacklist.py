from datetime import UTC, datetime

import redis.asyncio as redis

from app.core.settings import settings

# ✅ Use a single global Redis client (connection pool managed internally)
redis_client = redis.from_url(str(settings.REDIS_URL), decode_responses=True)


async def is_revoked(jti: str) -> bool:
    """
    Check if the token JTI is revoked.
    Purpose:
    Checks if a token's jti is in the blacklist.
    How it works:
    Returns True if the key jwt:blacklist:{jti} exists, meaning the token is revoked.

    """
    return await redis_client.exists(f"jwt:blacklist:{jti}") == 1


async def revoke(jti: str, exp_unix: int,delete_refresh_whitelist:bool = False):
    """
    Revoke a JWT by storing its JTI in Redis with TTL = token expiry.
    Redis auto-cleans expired keys.
    revoke(jti, exp_unix)
    Purpose:
    Adds a token's jti to the blacklist in Redis, with a TTL matching the token's expiry.
    How it works:
    Calculates the TTL: exp_unix - now.
    Stores the key jwt:blacklist:{jti} with value '1' and TTL.
    Effect:
    After the token expires, Redis automatically deletes the key.
    """
    ttl = max(1, exp_unix - int(datetime.now(UTC).timestamp()))
    await redis_client.setex(f"jwt:blacklist:{jti}", ttl, "1")
    if delete_refresh_whitelist:
        await redis_client.delete(f"auth:refresh_jti:{jti}")
