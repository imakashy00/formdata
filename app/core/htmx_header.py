import json
from typing import Any


def hx_toast_headers(
    message: str,
    type_: str = "success",
    *,
    reload: bool = False,
) -> dict[str, str]:
    """Build an HX-Trigger header that fires the `show-toast` window event
    your Alpine toast component listens for, optionally paired with a
    `reload-page` event for a delayed full-page refresh."""
    payload: dict[str, Any] = {"show-toast": {"value": message, "type": type_}}
    if reload:
        payload["reload-page"] = True
    return {"HX-Trigger": json.dumps(payload)}
