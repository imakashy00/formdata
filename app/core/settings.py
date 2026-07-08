from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal
from datetime import timedelta
from pydantic import AnyHttpUrl, PostgresDsn, RedisDsn
from pydantic import SecretStr

class Settings(BaseSettings):
    ENV: Literal["development", "production"] = "development"
    BASE_URL: AnyHttpUrl   # eg. https://ytnotes.co


    SECRET: str

    DATABASE_URL: PostgresDsn
    DB_POOL_SIZE: int 
    DB_MAX_OVERFLOW: int 

    # JWT
    JWT_ALGO: str
    JWT_SECRET: SecretStr
    ACCESS_TTL_MIN: int
    REFRESH_TTL_MIN: int

    # OAuth
    GOOGLE_CLIENT_ID: str
    GOOGLE_CLIENT_SECRET: str

    # Third party
    REDIS_URL: RedisDsn 

    # Paddle
    PADDLE_API_KEY: str
    PADDLE_WEBHOOK_SECRET: str
    PADDLE_BASE_URL: str = "https://sandbox-api.paddle.com"
    PADDLE_PRICE_ID_SOLO: str
    PADDLE_PRICE_ID_STUDIO: str

    PADDLE_PRICE_ID_EXTRA_SUBMISSIONS: str   # pri_xxx — $1 per 200-submission block
    PADDLE_PRICE_ID_EXTRA_STORAGE: str       # pri_xxx — $1 per GB

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 100



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



