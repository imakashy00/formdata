from pydantic import BaseModel, EmailStr, Field
# from sqlalchemy import Enum
from enum import Enum


class RegisterUser(BaseModel):
    name: str = Field(max_length=100)
    email: EmailStr = Field(max_length=255)
    google_sub: str = Field(max_length=50)
    picture: str | None = Field(max_length=500, default=None)


class DBUser(BaseModel):
    id: str
    email: EmailStr
    jti: str


class SubscriptionStatus(Enum):
    TRIAL = "trial"
    ACTIVE = "active"
    CANCELED = "canceled"        


