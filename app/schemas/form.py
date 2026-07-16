import re
from typing import Optional

from fastapi import Form
from pydantic import BaseModel, EmailStr, Field, field_validator


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
    success: dict | None = None


class FormSettingsPayload(BaseModel):
    name: str
    honeypot_field: str
    notification_email: EmailStr
    redirect_url: Optional[str] = None
    accepted_domains: str
    captcha_type: str
    turnstile_sitekey: Optional[str] = None
    turnstile_secret: Optional[str] = None
    sub_message: str
    sub_bg_color: str
    sub_txt_color: str
    sub_lnk_color: str

    # Class method to map incoming form fields to Pydantic
    @classmethod
    def as_form(
        cls,
        name: str = Form(...),
        honeypot_field: str = Form(...),
        notification_email: EmailStr = Form(...),
        redirect_url: Optional[str] = Form(None),
        accepted_domains: str = Form(...),
        captcha_type: str = Form(...),
        turnstile_sitekey: Optional[str] = Form(None),
        turnstile_secret: Optional[str] = Form(None),
        sub_message: str = Form(...),
        sub_bg_color: str = Form(...),
        sub_txt_color: str = Form(...),
        sub_lnk_color: str = Form(...)
    ):
        return cls(
            name=name, honeypot_field=honeypot_field, notification_email=notification_email,
            redirect_url=redirect_url, accepted_domains=accepted_domains, captcha_type=captcha_type,
            turnstile_sitekey=turnstile_sitekey, turnstile_secret=turnstile_secret,
            sub_message=sub_message, sub_bg_color=sub_bg_color, sub_txt_color=sub_txt_color, sub_lnk_color=sub_lnk_color
        )
