from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal, Optional
from urllib.parse import urlparse
from datetime import timedelta


class Settings(BaseSettings):
    ENV: Literal["development", "stagging", "production"] = "development"
    BASE_URL: Optional[str] = None  # eg. https://ytnotes.co
    RENDER_EXTERNAL_URL: Optional[str] = None

    SECRET: str

    DATABASE_URL: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10

    # JWT
    JWT_ALGO: str
    JWT_SECRET: str
    ACCESS_TTL_MIN: int
    REFRESH_TTL_MIN: int

    # OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # Third party
    OPENAI_API_KEY: str
    SMART_PROXY_USERNAME: str
    SMART_PROXY_PASSWORD: str
    REDIS_URL: str = "redis://localhost:6379"

    # Paddle
    PADDLE_API_KEY: str
    PADDLE_WEBHOOK_SECRET: str
    PADDLE_BASE_URL: str = "https://sandbox-api.paddle.com"
    PADDLE_MONTHLY_PRICE_ID: str
    PADDLE_YEARLY_PRICE_ID: str

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 100

    @property
    def effective_base_url(self) -> str:
        return (
            self.BASE_URL or self.RENDER_EXTERNAL_URL or "http://localhost:8000"
        ).rstrip("/")

    @property
    def ISSUER(self) -> str:
        return self.effective_base_url

    @property
    def AUDIENCE(self) -> str:
        return self.effective_base_url

    @property
    def COOKIE_DOMAIN(self) -> Optional[str]:
        host = urlparse(self.effective_base_url).hostname or ""
        if host in ("localhost",) or host.endswith("ngrok-free.app"):
            return None
        return host

    @property
    def SECURE_COOKIES(self) -> bool:
        return self.effective_base_url.startswith("https://")

    @property
    def ACCESS_TTL(self) -> timedelta:
        return timedelta(minutes=self.ACCESS_TTL_MIN)

    @property
    def REFRESH_TTL(self) -> timedelta:
        return timedelta(minutes=self.REFRESH_TTL_MIN)

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


settings = Settings()  # type: ignore


"""

If your website domain is dailyblog.com and you are using FastAPI with HTMX, set:

issuer (iss): "https://dailyblog.com"
audience (aud): "https://dailyblog.com"

--------------------    -----------------------     ------------------------------

If your backend is api.dailyblog.com and your frontend is dailyblog.com:

issuer (iss): "https://api.dailyblog.com"
(the backend issues the token)

audience (aud): "https://dailyblog.com"
(the frontend or client that the token is intended for)

Summary:

iss = your API domain
aud = your frontend domain


"""
