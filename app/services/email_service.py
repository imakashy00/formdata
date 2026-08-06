import logging
import re
from dataclasses import dataclass, field
from typing import Any

import markdown
import resend  # Official SDK
from pydantic_settings import BaseSettings

log = logging.getLogger(__name__)


class EmailSettings(BaseSettings):
    resend_api_key: str = "re_your_api_key"
    from_email: str = "notifications@yourdomain.com"
    from_name: str = "Formspree Alternative"

    class Config:
        env_file = ".env"
        extra = "ignore"


@dataclass(frozen=True, kw_only=True)
class SendParams:
    # Required field (must be passed as keyword argument)
    to: str | list[str]

    # Optional fields with default values
    from_addr: str | None = None  # Renamed from 'from'
    subject: str | None = None
    bcc: list[str] | str | None = None
    cc: list[str] | str | None = None
    reply_to: list[str] | str | None = None
    html: str | None = None
    text: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    attachments: list[Any] = field(default_factory=list)
    tags: list[Any] = field(default_factory=list)
    template: Any | None = None


settings = EmailSettings()

# Configure the global Resend client key
resend.api_key = settings.resend_api_key


class EmailService:
    def __init__(self):
        self.from_addr = f"{settings.from_name} <{settings.from_email}>"

    def _parse_template(
        self, subject_tpl: str, body_tpl: str, form_name: str, payload: dict[str, Any]
    ) -> tuple[str, str]:
        """Parses custom markdown tags and converts them into rich HTML string blocks."""
        # 1. Compile default dynamic list of submission fields
        details_list = []
        for key, value in payload.items():
            if not key.startswith("_"):  # Strip honeypot / system meta
                details_list.append(f"**{key.capitalize()}**: {value}")
        submission_details = "\n".join(details_list)

        # 2. Map payload keys directly to merge tags
        context = {
            "form_name": form_name,
            "submission_details": submission_details,
            **payload,
        }

        def replacer(match):
            tag = match.group(1)
            return str(context.get(tag, match.group(0)))

        # Replace bracketed parameters {variable} safely
        parsed_subject = re.sub(r"\{([^}]+)\}", replacer, subject_tpl)
        parsed_markdown = re.sub(r"\{([^}]+)\}", replacer, body_tpl)

        # Render Markdown to standard HTML for email client cross-compatibility
        html_body = markdown.markdown(parsed_markdown, extensions=["extra", "nl2br"])
        return parsed_subject, html_body

    async def _send_via_resend(
        self, to_email: str, subject: str, html_content: str, reply_to: str
    ):
        """Asynchronous HTTP call transport wrapper using the Resend REST API wrapper."""
        # If sending to an admin, set reply_to to the customer's email address
        reply_to_address = reply_to if reply_to else None
        params = SendParams(
            from_addr=self.from_addr,
            to=[to_email],
            subject=subject,
            html=html_content,
            reply_to=reply_to_address,  # Passed directly
        )

        try:
            # Native async execution using the official Resend SDK wrapper
            response = await resend.Emails.send_async(params)
            log.info(f"Successfully dispatched Resend email. ID: {response.get('id')}")
        except Exception as e:
            log.error(f"Resend API error while dispatching email to {to_email}: {e}")

    async def send_user_notification(
        self, user_email: str, form_name: str, payload: dict[str, Any]
    ):
        """Dispatches internal notification alerts to YOUR platform user (the form owner)."""
        subject_tpl = "New Submission on {form_name}"
        body_tpl = "You received a new submission alert!\n\n### Form Data:\n{submission_details}"

        subject, html_content = self._parse_template(
            subject_tpl, body_tpl, form_name, payload
        )

        # Auto-extract reply_to so your user can reply directly to their customer from their inbox
        customer_reply_to = (
            payload.get("email")
            or payload.get("Email")
            or payload.get("_replyto")
            or "fake customer"
        )

        await self._send_via_resend(
            to_email=user_email,
            subject=subject,
            html_content=html_content,
            reply_to=customer_reply_to,
        )

    async def send_customer_autoresponder(
        self,
        customer_email: str,
        form_name: str,
        subject_tpl: str,
        body_tpl: str,
        payload: dict[str, Any],
    ):
        """Dispatches custom confirmation responses back to your user's CLIENTS."""
        subject, html_content = self._parse_template(
            subject_tpl, body_tpl, form_name, payload
        )
        await self._send_via_resend(
            to_email=customer_email,
            subject=subject,
            html_content=html_content,
            reply_to="sdfjsldjfal",
        )
