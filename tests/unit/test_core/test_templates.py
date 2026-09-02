from datetime import datetime, timezone
import pytest

from app.core.templates import format_datetime, render_template, templates, time_ago


def test_format_datetime_filter():
    """Verify custom Jinja datetime formatting filter."""
    dt = datetime(2026, 9, 2, 15, 30, 0, tzinfo=timezone.utc)
    formatted = format_datetime(dt)
    assert "Sep" in formatted or "09" in formatted or "2026" in formatted


def test_time_ago_filter():
    """Verify relative time formatting."""
    now = datetime.now(timezone.utc)
    assert time_ago(now) == "just now"


def test_templates_instance():
    """Verify templates object is initialized with custom filters."""
    assert templates is not None
    assert "format_datetime" in templates.env.filters
    assert "time_ago" in templates.env.filters
