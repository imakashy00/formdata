import pytest

from app.services.file_upload import (
    DANGEROUS_EXTENSIONS,
    _safe_filename,
)


def test_safe_filename_cleaning():
    """Verify _safe_filename sanitizes invalid characters and prevents directory traversal."""
    assert _safe_filename("../../etc/passwd") == "passwd"
    assert _safe_filename("my resume (1).pdf") == "my_resume__1_.pdf"
    assert _safe_filename(None) == "file"


def test_dangerous_extensions_denylist():
    """Verify dangerous executable and script extensions are included in the denylist."""
    assert ".exe" in DANGEROUS_EXTENSIONS
    assert ".bat" in DANGEROUS_EXTENSIONS
    assert ".sh" in DANGEROUS_EXTENSIONS
    assert ".php" in DANGEROUS_EXTENSIONS
    assert ".js" in DANGEROUS_EXTENSIONS
    assert ".pdf" not in DANGEROUS_EXTENSIONS
    assert ".png" not in DANGEROUS_EXTENSIONS
