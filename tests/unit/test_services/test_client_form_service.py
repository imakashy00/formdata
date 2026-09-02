import pytest
from starlette.datastructures import FormData, Headers, UploadFile

from app.models.user import Form as FormDB
from app.services.client_form import _split_form_data


def test_split_form_data_text_and_files():
    """Verify _split_form_data separates standard text fields from UploadFile attachments."""
    raw = FormData([
        ("name", "Alice"),
        ("email", "alice@example.com"),
        ("tags", "support"),
        ("tags", "urgent"),
    ])
    fields, files = _split_form_data(raw)
    assert fields["name"] == "Alice"
    assert fields["email"] == "alice@example.com"
    assert fields["tags"] == ["support", "urgent"]
    assert len(files) == 0
