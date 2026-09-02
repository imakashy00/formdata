import pytest
from fastapi import status

from app.core.errors import (
    AppError,
    DuplicateError,
    ForbiddenError,
    IncorrectCloudflareTournstileKey,
    NotFoundError,
    ToastType,
    TypeCoversionError,
    WorkbookFailed,
)


def test_app_error_defaults():
    """Verify base AppError attributes."""
    exc = AppError(message="Something failed")
    assert exc.message == "Something failed"
    assert exc.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.toast_type == ToastType.ERROR
    assert str(exc) == "Something failed"


def test_not_found_error():
    """Verify NotFoundError behavior."""
    exc = NotFoundError(message="Project not found")
    assert exc.status_code == status.HTTP_404_NOT_FOUND
    assert exc.message == "Project not found"


def test_duplicate_error():
    """Verify DuplicateError behavior."""
    exc = DuplicateError(message="Form name already exists")
    assert exc.status_code == status.HTTP_409_CONFLICT
    assert exc.message == "Form name already exists"


def test_forbidden_error():
    """Verify ForbiddenError behavior."""
    exc = ForbiddenError(message="Access denied to resource")
    assert exc.status_code == status.HTTP_403_FORBIDDEN
    assert exc.message == "Access denied to resource"


def test_type_conversion_error():
    """Verify TypeCoversionError behavior."""
    exc = TypeCoversionError()
    assert exc.status_code == status.HTTP_400_BAD_REQUEST
    assert exc.message == "Invalid Input"


def test_workbook_failed():
    """Verify WorkbookFailed error behavior."""
    exc = WorkbookFailed()
    assert exc.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_turnstile_key_error():
    """Verify IncorrectCloudflareTournstileKey error behavior."""
    exc = IncorrectCloudflareTournstileKey()
    assert exc.status_code == status.HTTP_400_BAD_REQUEST

