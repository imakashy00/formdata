import re
from enum import Enum
from typing import Self

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


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
    turnstileSitekey: str | None = None
    success: dict | None = None


class FormSettingsPayload(BaseModel):
    name: str
    honeypot: str
    notification_email: EmailStr
    redirect_url: str | None = None
    allowed_domains: str
    turnstile_secret: str | None = None
    duplicate_allowed: bool
    duplicate_check_input: str | None = None
    is_active: bool
    sub_message: str
    sub_bg_color: str
    sub_txt_color: str
    sub_lnk_color: str

    @model_validator(mode="after")
    def validate_deduplication_input(self) -> Self:
        # If duplicates are blocked, we require a target payload key to track uniqueness
        if not self.duplicate_allowed:
            # Strip any unintended trailing or leading whitespaces
            input_val = (
                self.duplicate_check_input.strip() if self.duplicate_check_input else ""
            )

            if not input_val:
                raise ValueError(
                    "A target field name is required when duplicate submissions are blocked."
                )

            # Save the clean stripped value back onto the instance
            self.duplicate_check_input = input_val
        else:
            # Clean up and reset field if duplicates are allowed anyway
            self.duplicate_check_input = None

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
