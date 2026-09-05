import base64
import io
import json
import uuid
from typing import Annotated

import httpx
import openpyxl
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    Path,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
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
from app.core.settings import settings
from app.core.templates import temp
from app.models.user import IntegrationProvider, SubmissionStatus, User
from app.repositories.form_repository import FormRepository
from app.schemas.form import (
    TAB_LABELS,
    TAB_TEMPLATES,
    FormTab,
    NewForm,
)
from app.services.dependencies import current_user
from app.services.form import (
    _get_form_analytics,
    _get_owned_form,
    generate_workbook_sheet,
    get_form_analytics,
)
from app.services.oauth import oauth
from app.services.submission_sync import (
    _refresh_google_token,
    build_pending_sync_status,
    sync_submission_integrations,
    validate_google_sheets_config,
    validate_notion_config,
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
    # Target partial block template for HTMX filter requests, full template for tabs / history restore
    if htmx_req and not request.headers.get("HX-History-Restore-Request"):
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

    # If it's a direct browser refresh or history restore (non-HTMX or HX-History-Restore-Request), wrap in full layout
    if not htmx_req or request.headers.get("HX-History-Restore-Request"):
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
    background_tasks: BackgroundTasks,
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

    # When unspammed (marked as Approved/Accepted), export to configured integrations
    if action == "unspam":
        enabled_integrations = await repository.get_enabled_integrations(form_id)
        if enabled_integrations:
            submission.integration_sync_status = build_pending_sync_status(
                enabled_integrations
            )
            await db.commit()
            await db.refresh(submission)
            background_tasks.add_task(sync_submission_integrations, str(submission.id))

    # 4. Return just the specific table row fragment (`<tr>...</tr>`) to swap out
    # 'sub' context variable is passed so it maps cleanly to your existing template naming
    return temp.TemplateResponse(
        request,
        "partials/submission_row.html",
        context={"sub": submission, "form": form},
        headers=hx_toast_headers(
            "Submission marked as Approved and queued for sync!"
            if action == "unspam"
            else "Submission marked as Spam.",
            type_=ToastType.SUCCESS,
        ),
    )


@form_router.post(
    "/{project_id}/forms/{form_id}/submissions/{submission_id}/sync",
    response_class=HTMLResponse,
)
async def handle_sync_form_submission(
    request: Request,
    form_id: str,
    project_id: str,
    submission_id: str,
    background_tasks: BackgroundTasks,
    htmx_req: Annotated[bool, Depends(is_htmx_dep)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    try:
        submission_uuid = uuid.UUID(submission_id)
    except ValueError:
        raise TypeCoversionError("Invalid Submission id")

    repository = FormRepository(db)
    submission = await repository.get_submission(form_id, str(submission_uuid))

    if not submission:
        raise NotFoundError("Submission not found.")
    form = await repository.get_by_id_and_project(form_id, project_id)

    if submission.status != SubmissionStatus.ACCEPTED:
        return temp.TemplateResponse(
            request,
            "partials/submission_row.html",
            context={"sub": submission, "form": form},
            headers=hx_toast_headers(
                "Only approved submissions can be exported to integrations.",
                type_=ToastType.WARNING,
            ),
        )

    enabled_integrations = await repository.get_enabled_integrations(form_id)
    if not enabled_integrations:
        return temp.TemplateResponse(
            request,
            "partials/submission_row.html",
            context={"sub": submission, "form": form},
            headers=hx_toast_headers(
                "No active integrations configured. Please connect Google Sheets or Notion first.",
                type_=ToastType.WARNING,
            ),
        )

    submission.integration_sync_status = build_pending_sync_status(enabled_integrations)
    await db.commit()
    await db.refresh(submission)
    background_tasks.add_task(sync_submission_integrations, str(submission.id))

    return temp.TemplateResponse(
        request,
        "partials/submission_row.html",
        context={"sub": submission, "form": form},
        headers=hx_toast_headers(
            "Export to integrations queued!", type_=ToastType.SUCCESS
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

    if htmx_req and not request.headers.get("HX-History-Restore-Request"):
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

    if htmx_req and not request.headers.get("HX-History-Restore-Request"):
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
        "integration_map": await FormRepository(db).get_integration_map(
            form_id, project_id
        ),
    }
    return temp.TemplateResponse(
        request,
        template,
        context,
    )


@form_router.get(
    "/{project_id}/forms/{form_id}/integrations/google_sheets/connect",
)
async def handle_connect_google_sheets(
    request: Request,
    project_id: str,
    form_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    if not user:
        return RedirectResponse(url="/", status_code=303)
    form = await FormRepository(db).get_by_id_and_project(form_id, project_id)
    if not form:
        raise NotFoundError("Form not found")

    state_data = {
        "type": "google_sheets",
        "user_id": str(user.id),
        "project_id": str(project_id),
        "form_id": str(form_id),
    }
    state_str = base64.urlsafe_b64encode(json.dumps(state_data).encode()).decode()
    request.session["google_sheets_state"] = state_data

    redirect_uri = str(request.url_for("auth_callback"))
    if request.headers.get("x-forwarded-proto") == "https" or str(settings.BASE_URL).startswith("https:"):
        redirect_uri = redirect_uri.replace("http://", "https://", 1)

    return await oauth.google_sheets.authorize_redirect(
        request,
        redirect_uri,
        state=state_str,
        access_type="offline",
        prompt="consent",
    )


@form_router.post(
    "/{project_id}/forms/{form_id}/integrations/google_sheets/disconnect",
    response_class=HTMLResponse,
)
async def handle_disconnect_google_sheets(
    request: Request,
    project_id: str,
    form_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    form = await FormRepository(db).get_by_id_and_project(form_id, project_id)
    if not form:
        raise NotFoundError("Form not found")

    await FormRepository(db).remove_form_integration(
        form_id, project_id, IntegrationProvider.GOOGLE_SHEETS
    )

    integration_map = await FormRepository(db).get_integration_map(form_id, project_id)
    return temp.TemplateResponse(
        request,
        "form_integrations.html",
        {
            "request": request,
            "form": form,
            "active_tab": "integrations",
            "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
            "tab_labels": TAB_LABELS,
            "user": user,
            "page": "projects",
            "integration_map": integration_map,
        },
        headers=hx_toast_headers("Google Sheets integration disconnected.", type_=ToastType.SUCCESS),
        status_code=status.HTTP_200_OK,
    )


@form_router.post(
    "/{project_id}/forms/{form_id}/integrations/google_sheets/create_sheet",
    response_class=HTMLResponse,
)
async def handle_create_google_sheet(
    request: Request,
    project_id: str,
    form_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    form = await FormRepository(db).get_by_id_and_project(form_id, project_id)
    if not form:
        raise NotFoundError("Form not found")

    integ_map = await FormRepository(db).get_integration_map(form_id, project_id)
    gs_cfg = integ_map.get("google_sheets", {})

    # Ensure only ONE sheet is created. If one already exists, do not create another.
    if gs_cfg.get("sheet_url"):
        return temp.TemplateResponse(
            request,
            "form_integrations.html",
            {
                "request": request,
                "form": form,
                "active_tab": "integrations",
                "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
                "tab_labels": TAB_LABELS,
                "user": user,
                "page": "projects",
                "integration_map": integ_map,
            },
            headers=hx_toast_headers(
                "A spreadsheet is already linked to this form.",
                type_=ToastType.INFO,
            ),
            status_code=status.HTTP_200_OK,
        )

    access_token = gs_cfg.get("access_token")
    refresh_token = gs_cfg.get("refresh_token")

    if not access_token and refresh_token:
        access_token = await _refresh_google_token(refresh_token)

    if not access_token:
        return temp.TemplateResponse(
            request,
            "form_integrations.html",
            {
                "request": request,
                "form": form,
                "active_tab": "integrations",
                "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
                "tab_labels": TAB_LABELS,
                "user": user,
                "page": "projects",
                "integration_map": integ_map,
            },
            headers=hx_toast_headers(
                "Please connect your Google account with the drive.file consent screen first.",
                type_=ToastType.WARNING,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://sheets.googleapis.com/v4/spreadsheets",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "properties": {"title": f"{form.name} Submissions (Formdata)"},
                    "sheets": [{"properties": {"title": "Submissions"}}],
                },
            )
            if resp.status_code == 401 and refresh_token:
                access_token = await _refresh_google_token(refresh_token)
                if access_token:
                    resp = await client.post(
                        "https://sheets.googleapis.com/v4/spreadsheets",
                        headers={"Authorization": f"Bearer {access_token}"},
                        json={
                            "properties": {"title": f"{form.name} Submissions (Formdata)"},
                            "sheets": [{"properties": {"title": "Submissions"}}],
                        },
                    )

            if resp.status_code >= 400:
                raise ValueError(f"Could not create Google Sheet ({resp.status_code}): {resp.text}")

            data = resp.json()
            spreadsheet_id = data.get("spreadsheetId")
            sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
            worksheet_name = "Submissions"

            # Add header row
            await client.post(
                f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{worksheet_name}!A1:append?valueInputOption=USER_ENTERED",
                headers={"Authorization": f"Bearer {access_token}"},
                json={"values": [["Submitted At", "Country"]]},
            )

        new_config = {
            "sheet_url": sheet_url,
            "spreadsheet_id": spreadsheet_id,
            "worksheet_name": worksheet_name,
            "access_token": access_token,
        }
        if refresh_token:
            new_config["refresh_token"] = refresh_token

        await FormRepository(db).upsert_form_integration(
            form_id, project_id, IntegrationProvider.GOOGLE_SHEETS, new_config, enabled=True
        )
    except Exception as exc:
        return temp.TemplateResponse(
            request,
            "form_integrations.html",
            {
                "request": request,
                "form": form,
                "active_tab": "integrations",
                "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
                "tab_labels": TAB_LABELS,
                "user": user,
                "page": "projects",
                "integration_map": await FormRepository(db).get_integration_map(form_id, project_id),
            },
            headers=hx_toast_headers(str(exc), type_=ToastType.ERROR),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return temp.TemplateResponse(
        request,
        "form_integrations.html",
        {
            "request": request,
            "form": form,
            "active_tab": "integrations",
            "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
            "tab_labels": TAB_LABELS,
            "user": user,
            "page": "projects",
            "integration_map": await FormRepository(db).get_integration_map(form_id, project_id),
        },
        headers=hx_toast_headers(
            "Google Spreadsheet created and linked successfully!",
            type_=ToastType.SUCCESS,
        ),
        status_code=status.HTTP_200_OK,
    )


@form_router.post(
    "/{project_id}/forms/{form_id}/integrations/notion/disconnect",
    response_class=HTMLResponse,
)
async def handle_disconnect_notion(
    request: Request,
    project_id: str,
    form_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
):
    form = await FormRepository(db).get_by_id_and_project(form_id, project_id)
    if not form:
        raise NotFoundError("Form not found")

    await FormRepository(db).remove_form_integration(
        form_id, project_id, IntegrationProvider.NOTION
    )

    integration_map = await FormRepository(db).get_integration_map(form_id, project_id)
    return temp.TemplateResponse(
        request,
        "form_integrations.html",
        {
            "request": request,
            "form": form,
            "active_tab": "integrations",
            "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
            "tab_labels": TAB_LABELS,
            "user": user,
            "page": "projects",
            "integration_map": integration_map,
        },
        headers=hx_toast_headers("Notion integration disconnected.", type_=ToastType.SUCCESS),
        status_code=status.HTTP_200_OK,
    )


@form_router.post(
    "/{project_id}/forms/{form_id}/integrations/{provider}",
    response_class=HTMLResponse,
)
async def handle_save_form_integration(
    request: Request,
    project_id: str,
    form_id: str,
    provider: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    sheet_url: Annotated[str | None, Form()] = None,
    worksheet_name: Annotated[str | None, Form()] = None,
    google_token: Annotated[str | None, Form()] = None,
    database_id: Annotated[str | None, Form()] = None,
    notion_token: Annotated[str | None, Form()] = None,
):
    form = await FormRepository(db).get_by_id_and_project(form_id, project_id)
    if not form:
        raise NotFoundError("Form not found")

    provider_name = provider.lower().strip()
    try:
        if provider_name == "google_sheets":
            integ_map = await FormRepository(db).get_integration_map(form_id, project_id)
            existing_gs = integ_map.get("google_sheets", {})
            effective_token = (google_token or "").strip() or existing_gs.get("access_token")
            if not effective_token and existing_gs.get("refresh_token"):
                effective_token = await _refresh_google_token(existing_gs["refresh_token"])
            if not effective_token and not existing_gs.get("has_google_account"):
                raise ValueError("Please connect your Google account first.")

            config = validate_google_sheets_config(sheet_url, worksheet_name, effective_token)
            if existing_gs.get("refresh_token"):
                config["refresh_token"] = existing_gs["refresh_token"]

            # Try to fetch spreadsheet title from Google API to confirm access
            if effective_token:
                try:
                    spreadsheet_id = config["spreadsheet_id"]
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        sheet_res = await client.get(
                            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}",
                            headers={"Authorization": f"Bearer {effective_token}"},
                        )
                        if sheet_res.status_code == 401 and existing_gs.get("refresh_token"):
                            effective_token = await _refresh_google_token(existing_gs["refresh_token"])
                            if effective_token:
                                config["access_token"] = effective_token
                                sheet_res = await client.get(
                                    f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}",
                                    headers={"Authorization": f"Bearer {effective_token}"},
                                )
                        if sheet_res.status_code == 200:
                            data = sheet_res.json()
                            config["sheet_title"] = data.get("properties", {}).get("title") or "Google Spreadsheet"
                except Exception as check_err:
                    log.warning(f"Could not fetch spreadsheet title: {check_err}")

            await FormRepository(db).upsert_form_integration(
                form_id,
                project_id,
                IntegrationProvider.GOOGLE_SHEETS,
                config,
                enabled=True,
            )
        elif provider_name == "notion":
            integ_map = await FormRepository(db).get_integration_map(form_id, project_id)
            existing_notion = integ_map.get("notion", {})
            effective_token = (notion_token or "").strip() or existing_notion.get("notion_token")
            config = validate_notion_config(database_id, effective_token)

            # Introspect database via Notion API to verify permissions and get database title
            async with httpx.AsyncClient(timeout=12.0) as client:
                notion_res = await client.get(
                    f"https://api.notion.com/v1/databases/{config['database_id']}",
                    headers={
                        "Authorization": f"Bearer {config['notion_token']}",
                        "Notion-Version": "2022-06-28",
                    },
                )
                if notion_res.status_code == 200:
                    data = notion_res.json()
                    titles = data.get("title", [])
                    db_title = "".join(t.get("plain_text", "") for t in titles).strip()
                    config["database_title"] = db_title or "Notion Database"
                elif notion_res.status_code == 404:
                    raise ValueError(
                        "Notion database not found. Ensure the Database ID or link is correct and you have shared the database with your Notion integration (click '...' -> 'Add connections' in Notion)."
                    )
                elif notion_res.status_code in (401, 403):
                    raise ValueError(
                        "Notion authorization failed. Check your Notion Integration Token and make sure it has access to the target database."
                    )
                else:
                    log.warning(f"Notion API check returned {notion_res.status_code}: {notion_res.text}")

            await FormRepository(db).upsert_form_integration(
                form_id,
                project_id,
                IntegrationProvider.NOTION,
                config,
                enabled=True,
            )
        else:
            raise NotFoundError("Integration not found")
    except ValueError as val_err:
        return temp.TemplateResponse(
            request,
            "form_integrations.html",
            {
                "request": request,
                "form": form,
                "active_tab": "integrations",
                "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
                "tab_labels": TAB_LABELS,
                "user": user,
                "page": "projects",
                "integration_map": await FormRepository(db).get_integration_map(
                    form_id, project_id
                ),
            },
            headers=hx_toast_headers(str(val_err), type_=ToastType.ERROR),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return temp.TemplateResponse(
        request,
        "form_integrations.html",
        {
            "request": request,
            "form": form,
            "active_tab": "integrations",
            "active_tab_template": TAB_TEMPLATES[FormTab.integrations],
            "tab_labels": TAB_LABELS,
            "user": user,
            "page": "projects",
            "integration_map": await FormRepository(db).get_integration_map(
                form_id, project_id
            ),
        },
        headers=hx_toast_headers(
            f"{'Google Sheets' if provider_name == 'google_sheets' else 'Notion'} configuration saved successfully!",
            type_=ToastType.SUCCESS,
        ),
        status_code=status.HTTP_200_OK,
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

    if htmx_req and not request.headers.get("HX-History-Restore-Request"):
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

    if htmx_req and not request.headers.get("HX-History-Restore-Request"):
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

    if htmx_req and not request.headers.get("HX-History-Restore-Request"):
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
