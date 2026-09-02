import pytest

from app.services.submission_sync import (
    _now_iso,
    _stringify_value,
    _sync_entry,
    validate_google_sheets_config,
)


def test_now_iso_format():
    """Verify _now_iso generates valid ISO timestamp."""
    iso_str = _now_iso()
    assert isinstance(iso_str, str)
    assert "T" in iso_str


def test_stringify_value():
    """Verify _stringify_value serialization for dicts, lists, None, and strings."""
    assert _stringify_value(None) == ""
    assert _stringify_value("simple") == "simple"
    assert _stringify_value(123) == "123"
    assert _stringify_value({"key": "val"}) == '{"key": "val"}'


def test_validate_google_sheets_config_valid():
    """Verify validate_google_sheets_config parses spreadsheet URL and ID."""
    url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit"
    parsed = validate_google_sheets_config(url, "Submissions")
    assert parsed["spreadsheet_id"] == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    assert parsed["worksheet_name"] == "Submissions"


def test_validate_google_sheets_config_invalid():
    """Verify validate_google_sheets_config rejects invalid or non-Google URLs."""
    with pytest.raises(ValueError, match="spreadsheet URL is required"):
        validate_google_sheets_config("", "Sheet1")

    with pytest.raises(ValueError, match="Google Spreadsheet URL"):
        validate_google_sheets_config("https://example.com/not-sheets", "Sheet1")
