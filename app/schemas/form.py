import re
from enum import Enum
from typing import Self

from pydantic import BaseModel, EmailStr, field_validator, model_validator


class NewForm(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_form_name(cls, value: str) -> str:
        # 2. Strip leading/trailing whitespace
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Form name must be at least 3 characters long.")
        if len(value) > 50:
            raise ValueError("Form name must be atmost 50 characters long.")

        # 3. Reject names that are just special characters or numbers (Optional)
        if value.isdigit():
            raise ValueError("Form name cannot contain only numbers.")
        if value[0].isdigit():
            raise ValueError("Form name cannot be started with numbers.")
        # 4. Enforce character safety (Alphanumeric, spaces, hyphens, underscores)
        # Prevents XSS, SQL injection risks, and URL breaking
        if not re.match(r"^[a-zA-Z0-9_\-\s]+$", value):
            raise ValueError(
                "Form name can only contain letters, numbers, spaces, hyphens, and underscores."
            )

        return value


class WidgetConfig(BaseModel):
    provider: str
    honeypotField: str
    sessionToken: str
    challengeUrl: str
    turnstileSitekey: str | None = None
    success: dict | None = None


class FormSettingsPayload(BaseModel):
    name: str
    heading: str | None = None
    honeypot: str
    notification_email: EmailStr
    redirect: bool
    redirect_url: str | None = None
    allowed_domains: str
    turnstile_enabled: bool
    turnstile_secret: str | None = None
    duplicate_allowed: bool
    duplicate_check_input: str | None = None
    is_active: bool
    sub_message: str
    sub_bg_color: str
    sub_txt_color: str
    sub_lnk_color: str

    @model_validator(mode="after")
    def validate_conditional_features(self) -> Self:
        if self.heading is not None:
            self.heading = self.heading.strip()
            if not self.heading:
                self.heading = None
        # 1. Validate Deduplication
        if not self.duplicate_allowed:
            input_val = (
                self.duplicate_check_input.strip() if self.duplicate_check_input else ""
            )
            if not input_val:
                raise ValueError(
                    "A target field name is required when duplicate submissions are blocked."
                )
            self.duplicate_check_input = input_val
        else:
            self.duplicate_check_input = None

        # 2. Validate Redirection
        if self.redirect:
            url_val = self.redirect_url.strip() if self.redirect_url else ""
            if not url_val:
                raise ValueError(
                    "A redirect URL is required when redirection is enabled."
                )
            self.redirect_url = url_val
        else:
            self.redirect_url = None

        # 3. Validate Turnstile Bot Protection
        if self.turnstile_enabled:
            secret_val = self.turnstile_secret.strip() if self.turnstile_secret else ""
            if not secret_val:
                raise ValueError(
                    "A Cloudflare Turnstile secret key is required when Turnstile is enabled."
                )
            self.turnstile_secret = secret_val
        else:
            self.turnstile_secret = None

        return self


class FormTab(str, Enum):
    submissions = "submissions"
    setup = "setup"
    templates = "templates"
    settings = "settings"
    integrations = "integrations"
    analytics = "analytics"
    exports = "exports"


TAB_TEMPLATES = {
    FormTab.submissions: "form_submissions.html",
    FormTab.setup: "form_setup.html",
    FormTab.templates: "form_template.html",
    FormTab.settings: "form_settings.html",
    FormTab.integrations: "form_integrations.html",
    FormTab.analytics: "form_analytics.html",
    FormTab.exports: "form_exports.html",
}

TAB_LABELS = {
    FormTab.submissions: "Submissions",
    FormTab.setup: "Set Up",
    FormTab.templates: "Templates",
    FormTab.settings: "Settings",
    FormTab.integrations: "Integrations",
    FormTab.analytics: "Analytics",
    FormTab.exports: "Exports",
}
