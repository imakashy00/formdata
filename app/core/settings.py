import os
from datetime import timedelta
from typing import Literal

from pydantic import AnyHttpUrl, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_default_url = os.getenv("APP_URL") or "http://localhost:3000"


class Settings(BaseSettings):
    ENV: Literal["development", "production"] = "development"
    BASE_URL: AnyHttpUrl = _default_url  # type: ignore

    CLEANUP_INTERVAL_SECONDS: int = 3600

    SESSION_SECRET: str = "default-session-secret-key-at-least-32-chars!"

    DATABASE_URL: PostgresDsn | str = "postgresql+asyncpg://postgres:postgres@localhost:5432/formdata"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5

    # JWT
    JWT_ALGO: str = "HS256"
    JWT_SECRET: SecretStr = SecretStr("default-jwt-secret-key-at-least-32-chars-long!")
    ACCESS_TTL_MIN: int = 15
    REFRESH_TTL_MIN: int = 45

    # OAuth
    GOOGLE_CLIENT_ID: str = "google_client_id_default"
    GOOGLE_CLIENT_SECRET: str = "google_client_secret_default"

    # Paddle
    PADDLE_API_KEY: str = "paddle_api_key_default"
    PADDLE_WEBHOOK_SECRET: str = "paddle_webhook_secret_default"
    PADDLE_BASE_URL: str = "https://sandbox-api.paddle.com"
    PADDLE_PRICE_ID_SOLO: str = "pri_solo_default"
    PADDLE_PRICE_ID_STUDIO: str = "pri_studio_default"
    PADDLE_CLIENT_TOKEN: str = "paddle_client_token_default"
    PADDLE_ENVIRONMENT: str = "sandbox"

    RESEND_API_KEY: str = "resend_api_key_default"
    FROM_EMAIL: str = "notifications@formdata.space"
    FROM_NAME: str = "Formdata"

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 100

    MIN_SUBMIT_SECONDS: float = 1.5  # reject submissions faster than a human could type
    SESSION_TOKEN_MAX_AGE: int = (
        60 * 30
    )  # sessions older than this are stale, not just "fast"
    ALTCHA_CHALLENGE_EXPIRES: int = 120  # seconds a challenge stays valid

    RATE_LIMIT_IP: tuple = (20, 60)  # 20 requests / 60s per IP across all forms
    RATE_LIMIT_FORM: tuple = (
        200,
        60,
    )  # 200 requests / 60s per form, isolates noisy tenants

    # File limits
    MAX_UPLOAD_BYTES: int = 10 * 1024 * 1024
    MAX_FILES_PER_SUBMISSION: int = 5

    # Cloudflare Storage
    R2_ACCOUNT_ID: str = "r2_account_id_default"
    R2_ACCESS_KEY_ID: str = "r2_access_key_default"
    R2_SECRET_ACCESS_KEY: str = "r2_secret_key_default"
    R2_BUCKET: str = "r2_bucket_default"

    HONEYPOT_FIELD: str = "_hp"

    @property
    def SECURE_COOKIES(self) -> bool:
        return str(self.BASE_URL).startswith("https://")

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
