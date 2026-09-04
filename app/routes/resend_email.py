from datetime import datetime
from typing import Any, NotRequired, TypedDict

import resend
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from loguru import logger as log
from pydantic import BaseModel, Field

from app.core.settings import settings

email_router = APIRouter()

resend.api_key = settings.RESEND_API_KEY


class ExtractedEmailData(BaseModel):
    email_id: str
    from_address: str
    from_name: str
    to_addresses: list[str]
    cc_addresses: list[str]
    bcc_addresses: list[str]
    reply_to: list[str]
    subject: str
    date_created: datetime | None = None
    text_content: str | None = None
    return_path: str | None = None
    message_id: str | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    raw_download_url: str | None = None
    spam_verdict: str | None = None
    virus_verdict: str | None = None
    additional_metadata: dict[str, Any] = Field(default_factory=dict)


class Attachment(BaseModel):
    id: str
    filename: str
    content_type: str
    content_disposition: str
    content_id: str | None = None


class EmailData(BaseModel):
    email_id: str
    created_at: str
    from_: str | None = None  # Note: 'from' is a reserved keyword, use 'from_'
    to: list[str]
    cc: list[str] = []
    bcc: list[str] = []
    subject: str
    message_id: str
    attachments: list[Attachment] = []
    tags: dict[str, str] | None = None


class WebhookPayload(BaseModel):
    type: str
    created_at: str
    data: EmailData


class EmailAttachment(TypedDict):
    id: str
    filename: str | None
    content_type: str
    content_id: str | None
    content_disposition: str | None
    size: int | None


class ReceivedEmail(TypedDict):
    object: str
    id: str
    to: list[str]
    created_at: str
    subject: str
    html: str | None
    text: str | None
    bcc: list[str] | None
    cc: list[str] | None
    reply_to: list[str] | None
    received_for: list[str]
    headers: NotRequired[dict[str, str]]


@email_router.post("/webhook/resend")
async def handle_receive_support_mail(
    payload: Request, background_tasks: BackgroundTasks
):
    try:
        body = await payload.json()

        # Verify it's an email.received event
        if body.get("type") != "email.received":
            return {"status": "ignored", "reason": "Not an email.received event"}

        data = body.get("data", {})
        email_id = data.get("email_id")
        to_addresses = data.get("to", [])
        if to_addresses[0] == "support@formdata.cloud":
            background_tasks.add_task(fetch_and_process_email, email_id)
        return {"status": "success", "email_id": email_id}

    except Exception as e:
        print(f"Error processing webhook: {e!s}")
        raise HTTPException(status_code=400, detail="Invalid webhook payload")


async def fetch_and_process_email(email_id: str):
    try:
        email = resend.Emails.Receiving.get(email_id)
        print(f"Email==>{email}")
        print(extract_resend_webhook_data(email))

    except Exception as e:
        log.error(f"Something went wrong while fetching full email: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to retrieve email: {e!s}")


def extract_resend_webhook_data(payload: ReceivedEmail) -> ExtractedEmailData:
    """
    Extracts and maps raw Resend email webhook data from ReceivedEmail TypedDict
    into the structured ExtractedEmailData Pydantic model.
    """
    # Safeguard headers dictionary fallback since it is NotRequired
    headers = payload.get("headers") or {}

    # Safely extract from_address and display name from headers['from']
    # Example format: '"Akash yadav" <yakashadav26@gmail.com>'
    raw_from_header = headers.get("from", "")
    from_name = ""
    from_address = ""

    if "<" in raw_from_header and ">" in raw_from_header:
        # Extract display name part before '<'
        name_part = raw_from_header.split("<")[0]
        from_name = name_part.strip().strip('"').strip("'").strip()

        # Extract address part between '<' and '>'
        from_address = raw_from_header.split("<")[1].split(">")[0].strip()
    else:
        # Fallback if header format doesn't match standard routing wrappers
        from_address = raw_from_header
        from_name = raw_from_header

    # Extract non-TypedDict payload fields safely via fallback casting
    # (Since ReceivedEmail payload dictionary might contain extra un-typed keys like 'raw')
    raw_section = payload.get("raw") if isinstance(payload, dict) else {}
    raw_download_url = (
        raw_section.get("download_url") if isinstance(raw_section, dict) else None
    )

    # Handle list properties that can arrive as None values
    to_addresses = payload.get("to") or []
    cc_addresses = payload.get("cc") or []
    bcc_addresses = payload.get("bcc") or []
    reply_to = payload.get("reply_to") or []
    attachments = payload.get("attachments") or []

    return ExtractedEmailData(
        email_id=payload.get("id", ""),
        from_address=from_address,
        from_name=from_name,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        bcc_addresses=bcc_addresses,
        reply_to=reply_to,
        subject=payload.get("subject", ""),
        date_created=payload.get(  # type: ignore
            "created_at"
        ),
        text_content=payload.get("text"),
        return_path=headers.get("return-path"),
        message_id=headers.get("message-id"),
        attachments=attachments,
        raw_download_url=raw_download_url,
        spam_verdict=headers.get("x-ses-spam-verdict"),
        virus_verdict=headers.get("x-ses-virus-verdict"),
        additional_metadata={
            "html_format": payload.get("html_format"),
            "http_headers": payload.get("http_headers", {}),
            "received_for": payload.get("received_for", []),
        },
    )
