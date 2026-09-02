import pytest
from pydantic import ValidationError

from app.schemas.form import (
    FormSettingsPayload,
    FormTab,
    NewForm,
    TAB_LABELS,
    TAB_TEMPLATES,
    WidgetConfig,
)


def test_new_form_schema_valid():
    """Verify NewForm schema validation."""
    form = NewForm(name="Contact Form")
    assert form.name == "Contact Form"


def test_new_form_schema_invalid():
    """Verify NewForm schema rejects bad names."""
    with pytest.raises(ValidationError):
        NewForm(name="12")

    with pytest.raises(ValidationError):
        NewForm(name="99Forms")


def test_form_settings_payload():
    """Verify FormSettingsPayload field parsing and defaults."""
    payload = FormSettingsPayload(
        name="Lead Generation",
        heading="Fill this out",
        honeypot="_gotcha",
        notification_email="admin@example.com",
        redirect=True,
        redirect_url="https://example.com/thanks",
        allowed_domains="example.com,app.example.com",
        turnstile_enabled=False,
        duplicate_allowed=True,
        is_active=True,
        sub_message="Thank you for your submission!",
        sub_bg_color="#ffffff",
        sub_txt_color="#000000",
        sub_lnk_color="#0066cc",
    )
    assert payload.name == "Lead Generation"
    assert payload.notification_email == "admin@example.com"
    assert payload.redirect is True
    assert payload.redirect_url == "https://example.com/thanks"


def test_widget_config_schema():
    """Verify WidgetConfig parsing."""
    widget = WidgetConfig(
        provider="turnstile",
        honeypotField="_gotcha",
        sessionToken="tok_123",
        challengeUrl="https://example.com/challenge",
        turnstileSitekey="sitekey_abc",
    )
    assert widget.provider == "turnstile"
    assert widget.turnstileSitekey == "sitekey_abc"


def test_form_tabs_enum():
    """Verify FormTab enum and tab dictionaries."""
    assert FormTab.submissions == "submissions"
    assert FormTab.settings == "settings"
    assert TAB_TEMPLATES[FormTab.submissions] == "form_submissions.html"
    assert TAB_LABELS[FormTab.submissions] == "Submissions"

