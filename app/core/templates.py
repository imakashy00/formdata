import json
from datetime import UTC, datetime
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from starlette.templating import _TemplateResponse

from app.core.settings import settings


def strftime_filter(value, fmt="%B %d, %Y"):
    if value is None:
        return ""
    # handle unix timestamps stored as int/float
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=UTC)
    # handle ISO strings coming from JSON/DB drivers that don't auto-parse
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime(fmt)


temp = Jinja2Templates(directory="app/templates")
temp.env.globals["studio_price_id"] = settings.PADDLE_PRICE_ID_STUDIO
temp.env.filters["tojson"] = json.dumps
temp.env.filters["strftime"] = strftime_filter

# Plain json.dumps works for the settings template we built (booleans, plain strings, lists of strings). If you ever pass something Jinja2/Starlette-specific through tojson (e.g. a datetime, UUID, or SQLAlchemy model instance) it'll throw a TypeError since json.dumps doesn't know how to serialize those. If that comes up later, swap in a small wrapper with a default= fallback:
# python
# def _tojson(value: Any) -> str:
#     return json.dumps(value, default=str)

# temp.env.filters["tojson"] = _tojson


def render_template(
    request: Request,
    template_name: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
    toast_message: str | None = None,
) -> _TemplateResponse:
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
