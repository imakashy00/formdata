from unittest.mock import patch
import pytest

from app.services.email_service import EmailService, SendParams


def test_send_params_dataclass():
    """Verify SendParams configuration dataclass."""
    params = SendParams(
        to="user@example.com",
        subject="New Submission Received",
        html="<p>Test</p>",
    )
    assert params.to == "user@example.com"
    assert params.subject == "New Submission Received"


def test_email_service_template_parsing():
    """Verify template variable parsing and markdown formatting in EmailService."""
    service = EmailService()
    subject_tpl = "New message on {{form_name}} from {{name}}"
    body_tpl = "# Hello {{name}}\n\nYour message: {{message}}"
    
    subject, html = service._parse_template(
        subject_tpl=subject_tpl,
        body_tpl=body_tpl,
        form_name="Contact Form",
        payload={"name": "Alice", "message": "Great work!"},
    )
    assert "Contact Form" in subject
    assert "Alice" in subject
    assert "Alice" in html
    assert "Great work!" in html


@pytest.mark.asyncio
async def test_email_service_send_mocked(mock_resend):
    """Verify EmailService send triggers resend API."""
    service = EmailService()
    params = SendParams(
        to="client@example.com",
        subject="Welcome",
        html="<h1>Welcome</h1>",
    )
    res = await service.send(params)
    assert res is not None
