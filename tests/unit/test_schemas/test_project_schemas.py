import pytest
from pydantic import ValidationError

from app.schemas.project import NewProject


def test_new_project_schema_valid():
    """Verify NewProject validation with valid names."""
    p1 = NewProject(name="Marketing Website")
    assert p1.name == "Marketing Website"

    p2 = NewProject(name="  App-Backend_2026  ")
    assert p2.name == "App-Backend_2026"


def test_new_project_name_too_short():
    """Verify error when project name is less than 3 characters."""
    with pytest.raises(ValidationError, match="at least 3 characters"):
        NewProject(name="ab")


def test_new_project_name_too_long():
    """Verify error when project name exceeds 50 characters."""
    with pytest.raises(ValidationError, match="atmost 50 characters"):
        NewProject(name="A" * 51)


def test_new_project_name_started_with_numbers():
    """Verify error when project name starts with digits."""
    with pytest.raises(ValidationError, match="started with numbers"):
        NewProject(name="123Project")


def test_new_project_name_invalid_characters():
    """Verify error when project name contains forbidden characters like script tags or symbols."""
    with pytest.raises(ValidationError, match="can only contain letters"):
        NewProject(name="Project<script>")
