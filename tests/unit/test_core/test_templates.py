from datetime import datetime, timezone
import pytest

from app.core.templates import render_template, strftime_filter, temp


def test_strftime_filter():
    """Verify custom Jinja strftime formatting filter."""
    dt = datetime(2026, 9, 2, 15, 30, 0, tzinfo=timezone.utc)
    formatted = strftime_filter(dt)
    assert "Sep" in formatted or "09" in formatted or "2026" in formatted
    assert strftime_filter(None) == ""


def test_templates_instance():
    """Verify Jinja2Templates instance is configured with filters."""
    assert temp is not None
    assert "strftime" in temp.env.filters
    assert "tojson" in temp.env.filters

