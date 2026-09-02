import json
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core.htmx import (
    hx_toast_headers,
    is_html_request,
    is_htmx,
    is_htmx_dep,
)


def test_is_htmx():
    """Verify is_htmx checks for the hx-request header."""
    scope_htmx = {
        "type": "http",
        "headers": [(b"hx-request", b"true")],
    }
    req_htmx = Request(scope_htmx)
    assert is_htmx(req_htmx) is True

    scope_normal = {
        "type": "http",
        "headers": [],
    }
    req_normal = Request(scope_normal)
    assert is_htmx(req_normal) is False


@pytest.mark.asyncio
async def test_is_htmx_dep():
    """Verify is_htmx_dep dependency wrapper."""
    scope = {
        "type": "http",
        "headers": [(b"hx-request", b"true")],
    }
    req = Request(scope)
    assert await is_htmx_dep(req) is True


def test_hx_toast_headers():
    """Verify hx_toast_headers generates expected HX-Trigger and HX-Redirect payload."""
    headers = hx_toast_headers("Action succeeded", type_="success", reload=True, redirect="/dashboard")
    assert "HX-Trigger" in headers
    assert headers.get("HX-Redirect") == "/dashboard"

    parsed = json.loads(headers["HX-Trigger"])
    assert parsed["show-toast"]["value"] == "Action succeeded"
    assert parsed["show-toast"]["type"] == "success"
    assert parsed["reload-page"] is True


def test_is_html_request():
    """Verify is_html_request detects browser accept header or htmx."""
    scope_html = {
        "type": "http",
        "headers": [(b"accept", b"text/html,application/xhtml+xml")],
    }
    assert is_html_request(Request(scope_html)) is True

    scope_api = {
        "type": "http",
        "headers": [(b"accept", b"application/json")],
    }
    assert is_html_request(Request(scope_api)) is False

