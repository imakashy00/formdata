import json
import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse
from loguru import logger as log
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.templates import temp
from app.models.user import Form as FormDB
from app.models.user import User
from app.routes.page import get_current_user
from app.schemas.form import (
    TAB_LABELS,
    TAB_TEMPLATES,
    FormSettingsPayload,
    FormTab,
    NewForm,
)
from app.services.form import (
    _get_form_analytics,
    _get_owned_form,
    is_htmx,
    update_form_settings,
)

form_router = APIRouter(prefix="/projects")


@form_router.post("/{project_id}/forms", response_class=HTMLResponse)
async def handle_create_form(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    name: str = Form(...),
):
    try:
        form = NewForm(name=name)

        query = select(FormDB).where(
            FormDB.project_id == project_id, FormDB.name == form.name
        )
        result = await db.execute(query)
        existing_form = result.scalar_one_or_none()

        if existing_form:
            # Option A: Trigger a failure Toast for HTMX without crashing the app
            trigger_payload = json.dumps(
                {"show-toast": f"Error: A form named '{form.name}' already exists!"}
            )
            return temp.TemplateResponse(
                request,
                "partials/duplicate_error.html",  # Keep this file completely blank
                {"request": request},
                headers={"HX-Trigger": trigger_payload},
                status_code=status.HTTP_200_OK,  # 200 tells HTMX to process the empty swap safely
            )

        new_form = FormDB(
            name=form.name,
            project_id=project_id,
            notification_email=user.email,
        )
        db.add(new_form)
        await db.commit()
        await db.refresh(new_form)

        trigger_payload = json.dumps(
            {"show-toast": f"Form '{new_form.name}' created successfully!"}
        )
        # return RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)
        return temp.TemplateResponse(
            request,
            "form_card.html",
            {"request": request, "form": new_form, "project": {"id": project_id}},
            headers={
                "HX-Trigger": trigger_payload
            },  # 👈 HTMX automatically listens to this
        )

    except ValidationError as exc:
        log.warning(f"Failed to create new Form: {exc}")
        error_msg = exc.errors()[0]["msg"]
        log.warning(f"Validation failed for new form: {error_msg}")
        # Re-render the form page with the error message and the typed value
        return temp.TemplateResponse(
            request,
            "create_project_form.html",
            {
                "request": request,
                "error": error_msg,
                "typed_name": name,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except SQLAlchemyError as exc:
        log.error(f"Failed to create new form due to system error: {exc}")
        return temp.TemplateResponse(
            request,
            "projects.html",
            {"request": request, "error": "Something went wrong on our end."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@form_router.get("/{project_id}/forms/{form_id}", response_class=HTMLResponse)
async def handle_get_project_form(
    request: Request,
    form_id: str,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await db.execute(
            select(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        return temp.TemplateResponse(
            request,
            "form.html",
            {
                "request": request,
                "form": form,
                "active_tab_template": TAB_TEMPLATES[FormTab.submissions],
                "tab_labels": TAB_LABELS,
                "active_tab": "submissions",
                "email": user.email,
                "name": user.name,
                "user_id": user.id,
                "page": "projects",
            },
        )
    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")


@form_router.get("/test-widget", response_class=HTMLResponse)
async def test_widget(request: Request):
    return temp.TemplateResponse(request, "test.html", {"request": request})


@form_router.get("/{project_id}/forms", response_class=HTMLResponse)
async def handle_get_forms(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    project_id: uuid.UUID | None = None,
):
    try:
        # Fetch forms belonging to this user. Filter by project if provided.
        query = select(FormDB).where(FormDB.project_id == user.id)

        results = await db.execute(query)
        forms = results.scalars().all()

        return temp.TemplateResponse(
            request,
            "forms.html",
            {
                "forms": forms,
                "project_id": project_id,
                "email": user.email,
                "name": user.name,
                "user_id": user.id,
                "page": "forms",
            },
        )
    except SQLAlchemyError as e:
        log.warning(f"Error fetching Forms: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# Formspree handles this beautifully by allowing an empty array [] or {"*"}
# to mean "Accept submissions from anywhere" during initial setup.
# Then, once the form receives its first submission,
# Formspree automatically locks the form to that specific domain to prevent spam,
# while allowing the user to manually add localhost or other staging domains later in their settings dashboard.
@form_router.put("/{project_id}/forms/{form_id}/settings")
async def handle_update_form_setting(
    request: Request,
    form_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    payload: Annotated[FormSettingsPayload, Form()],
):
    try:
        query = select(FormDB).where(
            FormDB.id == form_id,
        )
        result = await db.execute(query)
        db_form = result.scalars().first()
        if not db_form:
            trigger_payload = json.dumps({"show-toast": "Error: Form not found!"})
            return temp.TemplateResponse(
                request,
                "partials/duplicate_error.html",  # Your blank file
                {"request": request},
                headers={"HX-Trigger": trigger_payload},
                status_code=status.HTTP_200_OK,
            )
        # 3. Parse comma-separated accepted domains into a list
        await update_form_settings(payload, db_form, db)

        # 6. Return success template response or swap element
        success_trigger = json.dumps({"show-toast": "Settings updated successfully!"})
        return temp.TemplateResponse(
            request,
            "form_settings.html",  # Change to your success partial
            {"request": request, "form": db_form},
            headers={"HX-Trigger": success_trigger},
            status_code=status.HTTP_200_OK,
        )

    except SQLAlchemyError as e:
        await db.rollback()
        # Handle or log server exception safely
        log.exception(f"Failed to update the form settings: Error {e}")
        error_trigger = json.dumps({"show-toast": "An unexpected error occurred."})
        return temp.TemplateResponse(
            request,
            "partials/duplicate_error.html",
            {"request": request},
            headers={"HX-Trigger": error_trigger},
            status_code=status.HTTP_200_OK,
        )


# --- 5. DELETE A FORM ---
@form_router.delete("/{project_id}/forms/{form_id}")
async def handle_delete_form(
    form_id: str,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        # Explicit delete criteria safeguarding multi-tenant architecture
        print(project_id)
        stmt = (
            delete(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .returning(FormDB.id)
        )
        result = await db.execute(stmt)
        deleted_id = result.scalar_one_or_none()
        if deleted_id is None:
            raise HTTPException(
                status_code=404, detail="Form asset not found or unauthorized."
            )

        await db.commit()

        # Ideal for HTMX delete operations (returns empty layout chunk, removing it from UI array)
        return Response(
            status_code=200, headers={"HX-Redirect": f"/projects/{project_id}"}
        )
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        log.error(f"Error executing form deletion payload: {e}")
        raise HTTPException(status_code=400, detail="Deletion runtime failure.")


@form_router.get(
    "/{project_id}/forms/{form_id}/submissions", response_class=HTMLResponse
)
async def handle_get_project_form_submissions(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await db.execute(
            select(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        if htmx_req:
            template = "form_submissions.html"
        else:
            template = "form.html"

        context = {
            "request": request,
            "form": form,
            "active_tab": "submissions",
            "active_tab_template": TAB_TEMPLATES[FormTab.submissions],
            "tab_labels": TAB_LABELS,
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "projects",
        }
        return temp.TemplateResponse(request, template, context)

    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")


@form_router.get("/{project_id}/forms/{form_id}/setup", response_class=HTMLResponse)
async def handle_get_project_form_setup(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await db.execute(
            select(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        if htmx_req:
            template = "form_setup.html"
        else:
            template = "form.html"
        context = {
            "request": request,
            "form": form,
            "active_tab": "setup",
            "active_tab_template": "form_setup.html",  # Pass the snippet filename here
            "tab_labels": TAB_LABELS,
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "projects",
        }
        return temp.TemplateResponse(request, template, context)
    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")


@form_router.get("/{project_id}/forms/{form_id}/settings", response_class=HTMLResponse)
async def handle_get_project_form_setttings(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await db.execute(
            select(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        if htmx_req:
            template = "form_settings.html"
        else:
            template = "form.html"
        context = {
            "request": request,
            "form": form,
            "active_tab": "settings",
            "active_tab_template": TAB_TEMPLATES[FormTab.settings],
            "tab_labels": TAB_LABELS,
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "projects",
        }
        return temp.TemplateResponse(request, template, context)
    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")


@form_router.get(
    "/{project_id}/forms/{form_id}/integrations", response_class=HTMLResponse
)
async def handle_get_project_form_integrations(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await db.execute(
            select(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        if htmx_req:
            template = "form_integrations.html"
        else:
            template = "form.html"

        context = {
            "request": request,
            "form": form,
            "active_tab": "integrations",
            "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
            "tab_labels": TAB_LABELS,
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "projects",
        }
        return temp.TemplateResponse(
            request,
            template,
            context,
        )
    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")


@form_router.get("/{project_id}/forms/{form_id}/analytics")
async def handle_form_analytics(
    form_id: str,
    request: Request,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    range: int = Query(7, ge=1, le=90, alias="range"),
):
    try:
        form = await _get_owned_form(db, user, form_id)

        analytics = await _get_form_analytics(db, form, range_days=range)

        if htmx_req:
            template = "form_analytics.html"
        else:
            template = "form.html"
        context = {
            "request": request,
            "form": form,
            "analytics": analytics,
            "active_tab": "analytics",
            "active_tab_template": TAB_TEMPLATES[FormTab.analytics],
            "tab_labels": TAB_LABELS,
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "projects",
        }
        return temp.TemplateResponse(
            request,
            template,
            context,
        )
    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")


@form_router.get("/{project_id}/forms/{form_id}/exports", response_class=HTMLResponse)
async def handle_get_project_form_exports(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await db.execute(
            select(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        if htmx_req:
            template = "form_exports.html"
        else:
            template = "form.html"
        context = {
            "request": request,
            "form": form,
            "active_tab": "exports",
            "active_tab_template": TAB_TEMPLATES[FormTab.exports],
            "tab_labels": TAB_LABELS,
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "projects",
        }
        return temp.TemplateResponse(request, template, context)
    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")


@form_router.get("/{project_id}/forms/{form_id}/templates", response_class=HTMLResponse)
async def handle_get_project_form_template(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await db.execute(
            select(FormDB)
            .where(FormDB.id == form_id, FormDB.project_id == project_id)
            .options(selectinload(FormDB.submissions))
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        if htmx_req:
            template = "form_template.html"
        else:
            template = "form.html"
        context = {
            "request": request,
            "form": form,
            "active_tab": "templates",
            "active_tab_template": TAB_TEMPLATES[FormTab.templates],
            "tab_labels": TAB_LABELS,
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "projects",
        }
        return temp.TemplateResponse(request, template, context)
    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")
