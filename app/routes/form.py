import io
import uuid
from typing import Annotated

import openpyxl
from fastapi import (
    APIRouter,
    Depends,
    Form,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, StreamingResponse
from loguru import logger as log
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import (
    DuplicateError,
    NotFoundError,
    ToastType,
    TypeCoversionError,
    WorkbookFailed,
)
from app.core.htmx import hx_toast_headers, is_htmx_dep
from app.core.templates import temp
from app.models.user import User
from app.repositories.form_repository import FormRepository
from app.schemas.form import (
    TAB_LABELS,
    TAB_TEMPLATES,
    FormSettingsPayload,
    FormTab,
    NewForm,
)
from app.services.dependencies import current_user
from app.services.form import (
    _get_form_analytics,
    _get_owned_form,
    generate_workbook_sheet,
    get_form_analytics,
    update_form_settings,
)

form_router = APIRouter(prefix="/projects")


@form_router.get("/test-widget", response_class=HTMLResponse)
async def test_widget(request: Request):
    return temp.TemplateResponse(request, "test.html", {"request": request})


@form_router.post("/{project_id}/forms", response_class=HTMLResponse)
async def handle_create_form(
    request: Request,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    name: str = Form(...),
):

    form = NewForm(name=name)
    repository = FormRepository(db)
    existing_form = await repository.get_by_name_and_project(form.name, project_id)

    if existing_form:
        raise DuplicateError(f"A form '{form.name}' already exists!")

    new_form = await repository.create(form.name, project_id, user.email)

    return temp.TemplateResponse(
        request,
        "form_card.html",
        {
            "form": new_form,
            "project": {"id": project_id},  # let it be nested, required in Frontend
        },
        status_code=status.HTTP_201_CREATED,
        headers=hx_toast_headers(
            f"Form '{new_form.name}' created successfully!", type_=ToastType.SUCCESS
        ),
    )


@form_router.get("/{project_id}/forms", response_class=HTMLResponse)
async def handle_get_forms(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    project_id: uuid.UUID,
):

    # Fetch forms belonging to this user. Filter by project if provided.
    forms = await FormRepository(db).list_for_project(user.id)
    if not forms:
        raise NotFoundError("No form found")
    return temp.TemplateResponse(
        request,
        "forms.html",
        {
            "forms": forms,
            "project_id": project_id,
            "user": user,
            "page": "forms",
        },
    )


# Formspree handles this beautifully by allowing an empty array [] or {"*"}
# to mean "Accept submissions from anywhere" during initial setup.
# Then, once the form receives its first submission,
# Formspree automatically locks the form to that specific domain to prevent spam,
# while allowing the user to manually add localhost or other staging domains later in their settings dashboard.
@form_router.put("/{project_id}/forms/{form_id}/settings")
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


# --- 5. DELETE A FORM ---
@form_router.delete("/{project_id}/forms/{form_id}")
async def handle_delete_form(
    form_id: str,
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):

    deleted = await FormRepository(db).delete_by_id_and_project(form_id, project_id)
    if not deleted:
        raise NotFoundError("Form not found")

    # Ideal for HTMX delete operations (returns empty layout chunk, removing it from UI array)
    return Response(
        status_code=status.HTTP_200_OK,
        headers=hx_toast_headers(
            "Form Deleted Sucessfully!",
            type_=ToastType.SUCCESS,
            redirect=f"/projects/{project_id}",
        ),
    )


@form_router.get(
    "/{project_id}/forms/{form_id}/submissions", response_class=HTMLResponse
)
async def handle_get_project_form_submissions(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    search: str | None = Query(None),
    status: str | None = Query(None),
):

    form = await FormRepository(db).get_by_id_and_project(form_id, project_id)
    if not form:
        raise NotFoundError("Form not found")

    context = await get_form_analytics(request, form, db, user, search, status, form_id)
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


@form_router.get(
    "/{project_id}/forms/{form_id}/submissions/{submission_id}",
    response_class=HTMLResponse,
)
async def handle_get_form_submission_by_id(
    request: Request,
    form_id: str,
    project_id: str,
    submission_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    # 1. Validate UUID format to prevent database query crashes
    try:
        submission_uuid = uuid.UUID(submission_id)
    except ValueError:
        raise TypeCoversionError("Invalid submission ID")

    repository = FormRepository(db)
    submission = await repository.get_submission(form_id, str(submission_uuid))

    if not submission:
        raise NotFoundError("Submission not found.")

    # 3. Optional: Mark submission as opened automatically if it wasn't already
    submission = await repository.set_submission_opened(submission)
    form = await repository.get_by_id_and_project(form_id, project_id)

    # 4. Render context
    context = {
        "request": request,
        "project_id": project_id,
        "form_id": form_id,
        "form": form,
        "user": user,
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
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    # 1. Validate UUID format
    try:
        submission_uuid = uuid.UUID(submission_id)
    except ValueError:
        raise TypeCoversionError("Invalid Submission id")

    repository = FormRepository(db)
    submission = await repository.get_submission(form_id, str(submission_uuid))

    if not submission:
        raise NotFoundError("Submission not found.")
    form = await repository.get_by_id_and_project(form_id, project_id)

    submission = await repository.update_submission_status(submission, action)

    # 4. Return just the specific table row fragment (`<tr>...</tr>`) to swap out
    # 'sub' context variable is passed so it maps cleanly to your existing template naming
    return temp.TemplateResponse(
        request,
        "partials/submission_row.html",
        context={"sub": submission, "form": form},
        headers=hx_toast_headers(
            "Submission status changed successfully!", type_=ToastType.SUCCESS
        ),
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
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    # 1. Parse and validate the UUID
    try:
        submission_uuid = uuid.UUID(submission_id)
    except ValueError:
        raise TypeCoversionError("Invalid submission ID ")

    repository = FormRepository(db)
    submission = await repository.get_submission(form_id, str(submission_uuid))

    if not submission:
        raise NotFoundError("Submission not found.")

    # 3. Perform database deletion
    await repository.delete_submission(submission)

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
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):

    form = await FormRepository(db).get_by_id_and_project(
        form_id, project_id, include_submissions=True
    )
    if not form:
        raise NotFoundError("Form not found")

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
        "user": user,
        "page": "projects",
    }
    return temp.TemplateResponse(request, template, context)


@form_router.get("/{project_id}/forms/{form_id}/settings", response_class=HTMLResponse)
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
        "user": user,
        "page": "projects",
    }
    return temp.TemplateResponse(request, template, context)


@form_router.get(
    "/{project_id}/forms/{form_id}/integrations", response_class=HTMLResponse
)
async def handle_get_project_form_integrations(
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
        raise NotFoundError("Form not found.")

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
        "user": user,
        "page": "projects",
    }
    return temp.TemplateResponse(
        request,
        template,
        context,
    )


@form_router.get("/{project_id}/forms/{form_id}/analytics")
async def handle_form_analytics(
    form_id: str,
    request: Request,
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    range: int = Query(7, ge=1, le=90, alias="range"),
):
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
        "user": user,
        "page": "projects",
    }
    return temp.TemplateResponse(
        request,
        template,
        context,
    )


@form_router.get("/{project_id}/forms/{form_id}/exports", response_class=HTMLResponse)
async def handle_get_project_form_exports(
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
        raise NotFoundError("Form not found.")

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
        "user": user,
        "page": "projects",
    }
    return temp.TemplateResponse(request, template, context)


@form_router.get("/{project_id}/forms/{form_id}/templates", response_class=HTMLResponse)
async def handle_get_project_form_template(
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
        "user": user,
        "page": "projects",
    }
    return temp.TemplateResponse(request, template, context)


@form_router.post("/{project_id}/forms/{form_id}/template", response_class=HTMLResponse)
async def handle_update_form_template(
    request: Request,
    form_id: str,
    project_id: str,
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    subject: Annotated[str, Form()],
    body: Annotated[str, Form()],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):

    form = await FormRepository(db).get_by_id_and_project(form_id, project_id)
    if not form:
        raise NotFoundError("Form not found")

    form = await FormRepository(db).update_template(form_id, project_id, subject, body)
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
        "user": user,
        "page": "projects",
    }
    return temp.TemplateResponse(request, template, context)


@form_router.get("/{project_id}/forms/{form_id}/export")
async def export_form_submission_excel(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    form_id: str = Path(..., description="The UUID string of the parent form"),
    status: str = Query(
        "", description="Filter records by status string matching your Enum values"
    ),
):
    submissions = await FormRepository(db).list_submissions(form_id, status or None)

    wb = openpyxl.Workbook()
    ws = wb.active

    if ws is None:
        log.critical("Failed to Initialize Workbook.")
        raise WorkbookFailed("Failed to initialize an active worksheet.")

    ws.title = "Submissions Export"
    if not submissions:
        # Prevent crash if there are no items in the database table
        raise NotFoundError("No submission found")
    output = await generate_workbook_sheet(submissions, ws, wb)

    filename = f"form_{form_id}_{status if status else 'all'}.xlsx"

    return StreamingResponse(
        io.BytesIO(output.getvalue()),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
