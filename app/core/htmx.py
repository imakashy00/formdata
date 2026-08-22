import json
from typing import Any

from fastapi import Request


def hx_toast_headers(
    message: str,
    type_: str = "success",
    *,
    reload: bool = False,
    redirect: str | None = None,
) -> dict[str, str]:
    """Fires the `show-toast` window event. Safe on error responses —
    htmx processes HX-Trigger/HX-Redirect on every status except 3xx
    (a real redirect response never reaches htmx's JS at all)."""
    trigger_payload: dict[str, Any] = {"show-toast": {"value": message, "type": type_}}
    if reload:
        trigger_payload["reload-page"] = True

    headers = {"HX-Trigger": json.dumps(trigger_payload)}
    if redirect:
        headers["HX-Redirect"] = redirect
    return headers


def is_htmx(request: Request) -> bool:
    """Plain check — safe to call from anywhere, including exception
    handlers, which never go through FastAPI's Depends() resolution."""
    return request.headers.get("hx-request") == "true"


async def is_htmx_dep(request: Request) -> bool:
    """Depends()-compatible wrapper for route signatures,
    e.g. `htmx: bool = Depends(is_htmx_dep)`."""
    return is_htmx(request)


def is_html_request(request: Request) -> bool:
    """True for browsers and htmx requests; False for pure API/JSON clients."""
    accept = request.headers.get("accept", "")
    return "text/html" in accept or is_htmx(request)
