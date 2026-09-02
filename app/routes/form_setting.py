from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse
from loguru import logger as log
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import NotFoundError, ToastType
from app.core.htmx import hx_toast_headers, is_htmx_dep
from app.core.templates import temp
from app.models.user import User
from app.repositories.form_repository import FormRepository
from app.schemas.form import TAB_LABELS, TAB_TEMPLATES, FormSettingsPayload, FormTab
from app.services.dependencies import current_user
from app.services.form import update_form_settings

form_settings_router = APIRouter(
    prefix="/projects/{project_id}/forms/{form_id}/settings"
)


@form_settings_router.get("/", response_class=HTMLResponse)
async def handle_get_project_form_setttings(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):

    form = await FormRepository(db).get_by_id_and_project(
        form_id, project_id, include_submissions=True
    )
    if not form:
        raise NotFoundError("Form not found")

    if htmx_req and not request.headers.get("HX-History-Restore-Request"):
        template = "form_settings.html"
    else:
        template = "form.html"
    context = {
        "request": request,
        "form": form,
        "active_tab": "settings",
        "active_tab_template": TAB_TEMPLATES[FormTab.settings],
        "tab_labels": TAB_LABELS,
        "user": user,
        "page": "projects",
    }
    return temp.TemplateResponse(request, template, context)


# Formspree handles this beautifully by allowing an empty array [] or {"*"}
# to mean "Accept submissions from anywhere" during initial setup.
# Then, once the form receives its first submission,
# Formspree automatically locks the form to that specific domain to prevent spam,
# while allowing the user to manually add localhost or other staging domains later in their settings dashboard.
@form_settings_router.put("/")
async def handle_update_form_setting(
    request: Request,
    form_id: str,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    payload: Annotated[FormSettingsPayload, Form()],
):

    db_form = await FormRepository(db).get_by_id_and_project(form_id, project_id) 
    if not db_form:
        raise NotFoundError("Form not found")
    # 3. Parse comma-separated accepted domains into a list
    await update_form_settings(payload, db_form, db)

    # 6. Return success template response or swap element
    return temp.TemplateResponse(
        request,
        "form_settings.html",  # Change to your success partial
        {"request": request, "form": db_form},
        headers=hx_toast_headers(
            "Settings updated successfully!", type_=ToastType.SUCCESS
        ),
        status_code=status.HTTP_200_OK,
    )
