import json
import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.core.htmx import (
    HXRedirect,
    HXRefresh,
    HXReswap,
    HXRetarget,
    HXTrigger,
    htmx_redirect,
    htmx_response,
    is_htmx_request,
)


def test_is_htmx_request():
    """Verify is_htmx_request checks for the HX-Request header."""
    scope_htmx = {
        "type": "http",
        "headers": [(b"hx-request", b"true")],
    }
    req_htmx = Request(scope_htmx)
    assert is_htmx_request(req_htmx) is True

    scope_normal = {
        "type": "http",
        "headers": [],
    }
    req_normal = Request(scope_normal)
    assert is_htmx_request(req_normal) is False


def test_htmx_redirect():
    """Verify htmx_redirect builds a response with HX-Redirect header."""
    resp = htmx_redirect("/dashboard")
    assert resp.headers.get("HX-Redirect") == "/dashboard"


def test_htmx_response_with_triggers():
    """Verify htmx_response attaches triggers, retarget, and reswap headers."""
    resp = htmx_response(
        trigger="formSaved",
        trigger_data={"id": "form_123"},
        target="#form-container",
        swap="innerHTML",
    )
    assert resp.headers.get("HX-Target") == "#form-container"
    assert resp.headers.get("HX-Reswap") == "innerHTML"
    
    # Check trigger header
    trigger_header = resp.headers.get("HX-Trigger")
    assert trigger_header is not None
    parsed = json.loads(trigger_header)
    assert "formSaved" in parsed
    assert parsed["formSaved"] == {"id": "form_123"}


def test_hx_redirect_response_class():
    """Verify HXRedirect response class sets correct status and header."""
    resp = HXRedirect(url="/login")
    assert resp.headers.get("HX-Redirect") == "/login"


def test_hx_refresh_response_class():
    """Verify HXRefresh response class sets HX-Refresh header."""
    resp = HXRefresh()
    assert resp.headers.get("HX-Refresh") == "true"
