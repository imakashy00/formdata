import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from app.core.settings import settings


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _exp(ttl: timedelta) -> int:
    return int((_now() + ttl).timestamp())


def create_token(
    *,
    sub: str,  # user id
    email: str,
    type: Literal["access", "refresh"],
    ttl: timedelta,
) -> tuple[str, str, int]:
    jti = str(
        uuid.uuid4()
    )  # a unique identifier for the token (usually a UUID). Used to track/revoke tokens individually.
    payload = {
        "sub": sub,
        "email": email,
        "type": type,
        "jti": jti,
        "iat": int(_now().timestamp()),
        "nbf": int(_now().timestamp()),
        "exp": _exp(ttl),
    }
    token = jwt.encode(payload, str(settings.JWT_SECRET), algorithm=settings.JWT_ALGO)
    return token, jti, payload["exp"]

