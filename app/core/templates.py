import json
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.templating import _TemplateResponse

temp = Jinja2Templates(directory="app/templates")


templates = Jinja2Templates(directory="templates")


def render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    toast_message: str | None = None,
)  -> _TemplateResponse:
    """Standardizes template responses and injects HTMX triggers cleanly."""

    # Ensure context exists and contains the required request object
    ctx = context or {}
    ctx["request"] = request

    headers = {}

    # Cleanly bundle HTMX toast triggers if provided
    if toast_message:
        trigger_payload = json.dumps({"showToast": toast_message})
        headers["HX-Trigger"] = trigger_payload

    return temp.TemplateResponse(
        request=request,
        name=template_name,
        context=ctx,
        status_code=status_code,
        headers=headers,
    )
