import io
import json
import uuid
from typing import Annotated

import openpyxl
from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from loguru import logger as log
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.core.templates import temp
from app.models.user import Form as FormDB
from app.models.user import Submission, SubmissionStatus, User
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
    get_form_analytics,
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
    search: str | None = Query(None),
    status: str | None = Query(None),
):
    try:
        # Base query fetching the specific form
        result = await db.execute(
            select(FormDB).where(FormDB.id == form_id, FormDB.project_id == project_id)
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        context = await get_form_analytics(
            request, form, db, user, search, status, form_id
        )
        # Target partial block template for HTMX filter requests, full template for tabs
        if htmx_req:
            # If HTMX request came directly from filters, swap just the table body element
            if request.headers.get("HX-Target") == "submissions-table-container":
                template = "partials/submissions_table.html"
            else:
                template = "form_submissions.html"
        else:
            template = "form.html"
        return temp.TemplateResponse(request, template, context)

    except SQLAlchemyError as e:
        log.exception(f"Something went wrong while fetching form details: {e}")
        raise HTTPException(status_code=500, detail="Database retrieval error.")


@form_router.get(
    "/{project_id}/forms/{form_id}/submissions/{submission_id}",
    response_class=HTMLResponse,
)
async def handle_get_form_submission_by_id(
    request: Request,
    form_id: str,
    project_id: str,
    submission_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    # 1. Validate UUID format to prevent database query crashes
    try:
        submission_uuid = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid submission ID format.",
        )

    # 2. Fetch submission and eager-load the related form
    query = select(Submission).where(
        Submission.id == submission_uuid, Submission.form_id == form_id
    )
    result = await db.execute(query)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found."
        )

    # 3. Optional: Mark submission as opened automatically if it wasn't already
    if not submission.opened:
        submission.opened = True
        await db.commit()

    form_query = select(FormDB).where(FormDB.id == form_id)
    form_result = await db.execute(form_query)
    form = form_result.scalar_one_or_none()

    # 4. Render context
    context = {
        "request": request,
        "project_id": project_id,
        "form_id": form_id,
        "form": form,
        "active_tab": "submissions",
        "active_tab_template": TAB_TEMPLATES[FormTab.submissions],
        "tab_labels": TAB_LABELS,
        "submission": submission,
    }

    # If it's a direct browser refresh (non-HTMX), you might want to wrap it in a full layout
    if not htmx_req:
        return temp.TemplateResponse(request, "submission_details.html", context)

    return temp.TemplateResponse(
        request, "partials/submission_details_card.html", context
    )


@form_router.post(
    "/{project_id}/forms/{form_id}/submissions/{submission_id}/toggle-status",
    response_class=HTMLResponse,
)
async def handle_toggele_status_form_submission(
    request: Request,
    form_id: str,
    project_id: str,
    action: str,
    submission_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    # 1. Validate UUID format
    try:
        submission_uuid = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ID format.")

    # 2. Fetch the submission
    query = select(Submission).where(
        Submission.id == submission_uuid, Submission.form_id == form_id
    )
    result = await db.execute(query)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found.")
    form_query = select(FormDB).where(FormDB.id == form_id)
    form_result = await db.execute(form_query)
    form = form_result.scalar_one_or_none()
    # 3. Apply state mutation based on single action argument
    if action == "spam":
        submission.status = (
            SubmissionStatus.REJECTED
        )  # Make sure this matches your Enum value
    elif action == "unspam":
        submission.status = SubmissionStatus.ACCEPTED
    else:
        raise HTTPException(status_code=400, detail="Invalid action parameter.")

    await db.commit()
    await db.refresh(submission)
    
    # 4. Return just the specific table row fragment (`<tr>...</tr>`) to swap out
    # 'sub' context variable is passed so it maps cleanly to your existing template naming
    return temp.TemplateResponse(
        request,
        "partials/submission_row.html",
        context={"sub": submission, "form": form},
    )


@form_router.delete(
    "/{project_id}/forms/{form_id}/submissions/{submission_id}/delete",
    response_class=HTMLResponse,
)
async def handle_delete_form_submission(
    request: Request,
    form_id: str,
    project_id: str,
    submission_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    # 1. Parse and validate the UUID
    try:
        submission_uuid = uuid.UUID(submission_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid submission ID format.",
        )

    # 2. Fetch the target database record
    query = select(Submission).where(
        Submission.id == submission_uuid, Submission.form_id == form_id
    )
    result = await db.execute(query)
    submission = result.scalar_one_or_none()

    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission already deleted or not found.",
        )

    # 3. Perform database deletion
    await db.delete(submission)
    await db.commit()

    # 4. Handle frontend DOM updates via HTMX
    # If the request comes from the "Details" screen, redirect them back to the full table list.
    # if action == "redirect_to_list":
    #     response = HTMLResponse(content="", status_code=status.HTTP_200_OK)
    #     # Instructs HTMX to perform a client-side layout swap to the table view
    #     response.headers["HX-Redirect"] = (
    #         f"/projects/{project_id}/forms/{form_id}/submissions"
    #     )
    #     return response

    # Default action: If clicking "Delete" directly from a table row, return empty content.
    # Combined with hx-target="closest tr" and hx-swap="outerHTML", this removes the row seamlessly.
    response = HTMLResponse(content="", status_code=status.HTTP_200_OK)
    response.headers["HX-Push-Url"] = "false"
    return response


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


@form_router.post("/{project_id}/forms/{form_id}/template", response_class=HTMLResponse)
async def handle_update_form_template(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx)],
    subject: Annotated[str, Form()],
    body: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    try:
        result = await db.execute(
            select(FormDB).where(FormDB.id == form_id, FormDB.project_id == project_id)
        )
        form = result.scalar_one_or_none()
        if not form:
            raise HTTPException(status_code=404, detail="Form not found.")

        # Persist user custom values
        form.customer_subject = subject
        form.customer_body = body

        await db.commit()
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
        await db.rollback()
        log.exception(f"Failed to update form template: {e}")
        raise HTTPException(status_code=500, detail="Could not save template.")


@form_router.get("/{project_id}/forms/{form_id}/export")
async def export_form_submission_excel(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    form_id: str = Path(..., description="The UUID string of the parent form"),
    status: str = Query(
        "", description="Filter records by status string matching your Enum values"
    ),
):
    query = select(Submission).where(Submission.form_id == form_id)

    # 2. Append optional status filter if provided
    if status:
        query = query.where(Submission.status == status)
    # Execute and fetch all results from database
    result = await db.execute(query)
    submissions = result.scalars().all()

    wb = openpyxl.Workbook()
    ws = wb.active

    if ws is None:
        raise ValueError("Failed to initialize an active worksheet.")

    ws.title = "Submissions Export"
    if not submissions:
        # Prevent crash if there are no items in the database table
        ws.append(["No records found for this form criteria"])
    else:
        # 4. Handle Dynamic JSONB Payload Column Headers
        # We look at the first record's payload dictionary keys to create dynamic columns
        sample_payload = submissions[0].payload or {}
        dynamic_keys = list(sample_payload.keys())

        # Combine standard fixed model columns + your custom dynamic JSON keys
        base_headers = ["ID", "Status", "Opened", "Country", "Note", "Created At"]
        ws.append(base_headers + dynamic_keys)

        # 5. Populate Rows
        for sub in submissions:
            # Flatten fixed model row data values
            row_data = [
                str(sub.id),
                sub.status.value if hasattr(sub.status, "value") else str(sub.status),
                "Yes" if sub.opened else "No",
                sub.country or "Unknown",
                sub.note or "",
                sub.created_at.strftime("%Y-%m-%d %H:%M:%S %Z")
                if sub.created_at
                else "",
            ]

            # Safely extract matching JSONB payload fields for this row
            payload_data = sub.payload or {}
            for key in dynamic_keys:
                row_data.append(payload_data.get(key, ""))

            ws.append(row_data)

    # 6. Stream file binary payload directly to Alpine's fetch method without reloading page
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"form_{form_id}_{status if status else 'all'}.xlsx"

    return StreamingResponse(
        io.BytesIO(output.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
