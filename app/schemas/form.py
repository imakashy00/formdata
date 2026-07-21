import re
from typing import Optional

from fastapi import Form
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.user import CaptchaType


class NewForm(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_project_name(cls, value: str) -> str:
        # 2. Strip leading/trailing whitespace
        value = value.strip()

        # 3. Reject names that are just special characters or numbers (Optional)
        if value.isdigit():
            raise ValueError("Project name cannot contain only numbers.")

        # 4. Enforce character safety (Alphanumeric, spaces, hyphens, underscores)
        # Prevents XSS, SQL injection risks, and URL breaking
        if not re.match(r"^[a-zA-Z0-9_\-\s]+$", value):
            raise ValueError(
                "Project name can only contain letters, numbers, spaces, hyphens, and underscores."
            )

        return value


class WidgetConfig(BaseModel):
    provider: str
    honeypotField: str
    sessionToken: str
    challengeUrl: str
    turnstileSitekey: Optional[str] = None
    success: dict | None = None


class FormSettingsPayload(BaseModel):
    name: str
    honeypot: str
    notification_email: EmailStr
    redirect_url: Optional[str] = None
    allowed_domains: str
    captcha_type: CaptchaType = CaptchaType.TURNSTILE
    turnstile_sitekey: Optional[str] = None
    turnstile_secret: Optional[str] = None
    is_active: bool
    sub_message: str
    sub_bg_color: str
    sub_txt_color: str
    sub_lnk_color: str

    # Class method to map incoming form fields to Pydantic
    @classmethod
    def as_form(
        cls,
        name: str = Form(...),
        honeypot: str = Form(...),
        notification_email: EmailStr = Form(...),
        redirect_url: Optional[str] = Form(None),
        allowed_domains: str = Form(...),
        captcha_type: CaptchaType = Form(CaptchaType.TURNSTILE),
        turnstile_sitekey: Optional[str] = Form(None),
        turnstile_secret: Optional[str] = Form(None),
        is_active: bool = Form(...),
        sub_message: str = Form(...),
        sub_bg_color: str = Form(...),
        sub_txt_color: str = Form(...),
        sub_lnk_color: str = Form(...),
    ):
        return cls(
            name=name,
            honeypot=honeypot,
            notification_email=notification_email,
            redirect_url=redirect_url,
            allowed_domains=allowed_domains,
            captcha_type=captcha_type,
            turnstile_sitekey=turnstile_sitekey,
            turnstile_secret=turnstile_secret,
            is_active=is_active,
            sub_message=sub_message,
            sub_bg_color=sub_bg_color,
            sub_txt_color=sub_txt_color,
            sub_lnk_color=sub_lnk_color,
        )

    @field_validator("honeypot")
    @classmethod
    def normalize_honeypot(cls, value: str) -> str:
        value = value.strip().lstrip("_")
        if not value:
            raise ValueError("Honeypot field name is required.")
        if not re.match(r"^[a-zA-Z0-9_\-]+$", value):
            raise ValueError("Honeypot field name can only contain letters, numbers, hyphens, and underscores.")
        return f"_{value}"

    @model_validator(mode="after")
    def validate_turnstile_settings(self):
        if self.captcha_type == CaptchaType.TURNSTILE:
            if not self.turnstile_sitekey or not self.turnstile_sitekey.strip():
                raise ValueError("Turnstile site key is required when Turnstile bot protection is selected.")
            if not self.turnstile_secret or not self.turnstile_secret.strip():
                raise ValueError("Turnstile secret key is required when Turnstile bot protection is selected.")
        return self
