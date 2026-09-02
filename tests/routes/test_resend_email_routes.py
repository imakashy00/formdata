import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_resend_email_webhook_ping(client: AsyncClient):
    """Verify POST /email/webhook handles email delivery events."""
    payload = {
        "type": "email.delivered",
        "created_at": "2026-09-02T12:00:00.000Z",
        "data": {
            "email_id": "email_test_123",
            "created_at": "2026-09-02T12:00:00.000Z",
            "from_": "notifications@formdata.space",
            "to": ["user@example.com"],
            "subject": "New Submission",
            "message_id": "msg_12345",
            "attachments": [],
        },
    }
    response = await client.post(
        "/email/webhook",
        json=payload,
    )
    assert response.status_code in (200, 202, 204)
