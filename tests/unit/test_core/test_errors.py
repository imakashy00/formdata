import pytest

from app.core.errors import (
    AppException,
    BadRequestError,
    DuplicateRecordError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    UnauthorizedError,
    ValidationError,
)


def test_app_exception_defaults():
    """Verify base AppException attributes."""
    exc = AppException(message="Something failed", status_code=400, details={"field": "test"})
    assert exc.message == "Something failed"
    assert exc.status_code == 400
    assert exc.details == {"field": "test"}
    assert str(exc) == "Something failed"


def test_validation_error():
    """Verify ValidationError status code and structure."""
    exc = ValidationError(message="Invalid email address", details={"field": "email"})
    assert exc.status_code == 422
    assert exc.message == "Invalid email address"
    assert exc.details == {"field": "email"}


def test_not_found_error():
    """Verify NotFoundError behavior."""
    exc = NotFoundError(message="Project not found", details={"resource": "Project", "id": "123"})
    assert exc.status_code == 404
    assert exc.message == "Project not found"
    assert exc.details["id"] == "123"


def test_unauthorized_error():
    """Verify UnauthorizedError behavior."""
    exc = UnauthorizedError(message="Session expired")
    assert exc.status_code == 401
    assert exc.message == "Session expired"


def test_forbidden_error():
    """Verify ForbiddenError behavior."""
    exc = ForbiddenError(message="Access denied to resource")
    assert exc.status_code == 403
    assert exc.message == "Access denied to resource"


def test_bad_request_error():
    """Verify BadRequestError behavior."""
    exc = BadRequestError(message="Malformed input parameters")
    assert exc.status_code == 400
    assert exc.message == "Malformed input parameters"


def test_duplicate_record_error():
    """Verify DuplicateRecordError behavior."""
    exc = DuplicateRecordError(message="Form name already exists", details={"name": "Contact"})
    assert exc.status_code == 409
    assert exc.message == "Form name already exists"


def test_rate_limit_error():
    """Verify RateLimitError behavior."""
    exc = RateLimitError(message="Too many submissions. Please slow down.")
    assert exc.status_code == 429
    assert exc.message == "Too many submissions. Please slow down."
