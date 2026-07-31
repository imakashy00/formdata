import json

from fastapi import Request, status

from templates import temp


class DuplicateFormException(Exception):
    def __init__(self, name: str):
        self.name = name

async def duplicate_form_exception_handler(request: Request, exc: DuplicateFormException):
    trigger_payload = json.dumps({"show-toast": f"Error: A form named '{exc.name}' already exists!"})
    return temp.TemplateResponse(
        request,
        "partials/duplicate_error.html",
        {"request": request},
        headers={"HX-Trigger": trigger_payload},
        status_code=status.HTTP_200_OK,
    )
