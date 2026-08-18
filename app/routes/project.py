import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger as log
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.templates import temp
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.services.dependencies import current_user

project_router = APIRouter()


class NewProject(BaseModel):
    name: str = Field(..., min_length=3, max_length=50)

    @field_validator("name")
    @classmethod
    def validate_project_name(cls, value: str) -> str:
        # 2. Strip leading/trailing whitespace
        value = value.strip()

        # 3. Reject names that are just special characters or numbers (Optional)
        if value.isdigit():
            raise ValueError("Project name cannot contain only numbers.")

        # 4. Enforce character safety (Alphanumeric, spaces, hyphens, underscores)
        # Prevents XSS, SQL injection risks, and URL breaking
        if not re.match(r"^[a-zA-Z0-9_\-\s]+$", value):
            raise ValueError(
                "Project name can only contain letters, numbers, spaces, hyphens, and underscores."
            )

        return value


@project_router.get("/projects", response_class=HTMLResponse)
async def get_projects(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        projects = await ProjectRepository(db).list_for_user(user.id)
        return temp.TemplateResponse(
            request,
            "projects.html",
            {
                "projects": projects,
                "email": user.email,
                "name": user.name,
                "user_id": user.id,
                "page": "projects",
            },
        )
    except SQLAlchemyError as e:
        log.warning(f"Errror fetching Projects{e}")


@project_router.post("/projects", response_class=HTMLResponse)
async def create_project(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    name: str = Form(...),
):
    try:
        project = NewProject(name=name)
        repository = ProjectRepository(db)
        new_project = await repository.create(project.name, user.id)
        trigger_payload = json.dumps(
            {"showToast": f"Project '{new_project.name}' created successfully!"}
        )
        # return RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)
        return temp.TemplateResponse(
            request,
            "project_card.html",
            {"request": request, "project": new_project, "form_count": 0},
            headers={
                "HX-Trigger": trigger_payload
            },  # 👈 HTMX automatically listens to this
        )

    except ValidationError as exc:
        log.warning(f"Failed to create new Project: {exc}")
        error_msg = exc.errors()[0]["msg"]

        # Check if the Pydantic/database error implies a duplicate
        if "already exists" in error_msg.lower() or "unique" in error_msg.lower():
            display_error = "Duplicate error: This project name is already taken."
        else:
            display_error = f"Validation error: {error_msg}"

        return Response(
            content=display_error,
            status_code=status.HTTP_400_BAD_REQUEST,
            headers={"HX-Trigger": json.dumps({"showErrorToast": display_error})},
            media_type="text/plain",
        )

    except SQLAlchemyError as exc:
        log.error(f"Failed to create new Project due to system error: {exc}")

        # Determine if the DB error itself is a duplicate violation (e.g., IntegrityError)
        error_str = str(exc).lower()
        if "duplicate" in error_str or "unique constraint" in error_str:
            display_error = "Duplicate error: This project name already exists."
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            display_error = "Something went wrong on our end."
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

        return Response(
            content=display_error,
            status_code=status_code,
            headers={"HX-Trigger": json.dumps({"showErrorToast": display_error})},
            media_type="text/plain",
        )


@project_router.get("/projects/{project_id}", response_class=HTMLResponse)
async def get_project(
    request: Request,
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        project = await ProjectRepository(db).get_for_user(project_id, user.id)

        # print(project)
        return temp.TemplateResponse(
            request,
            "project.html",
            {
                "project": project,
                "email": user.email,
                "name": user.name,
                "user_id": user.id,
                "page": "projects",
            },
        )
    except SQLAlchemyError as e:
        log.warning(f"Errror fetching Project{e}")


@project_router.put("/projects/{project_id}/settings", response_class=HTMLResponse)
async def update_project(
    request: Request,
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_name: str = Form(...),
):
    try:
        repository = ProjectRepository(db)
        project = await repository.get_for_user(project_id, user.id)
        if not project:
            log.warning(
                f"Project {project_id} not found or unauthorized for user {user.id}"
            )
            return temp.TemplateResponse(
                request, "404.html", status_code=status.HTTP_404_NOT_FOUND
            )

        # 2. Validate the new name incoming input data
        project_name_validated = NewProject(name=project_name)

        # 3. Commit changes to DB
        project.name = project_name_validated.name
        await db.commit()
        return Response(
            status_code=200, headers={"HX-Redirect": f"/projects/{project_id}"}
        )

    except ValidationError as exc:
        error_msg = exc.errors()[0]["msg"]
        log.warning(f"Validation failed during project update: {error_msg}")
        return temp.TemplateResponse(
            request,
            "edit_project_form.html",
            {
                "request": request,
                "error": error_msg,
                "project": project_name,  # Send back old details so form fields stay populated
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except SQLAlchemyError as exc:
        log.error(f"Failed to update project {project_id}: {exc}")
        return RedirectResponse(
            url="/projects", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# --- DELETE PROJECT ---
@project_router.delete("/projects/{project_id}", response_class=HTMLResponse)
async def delete_project(
    request: Request,
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        deleted = await ProjectRepository(db).delete_for_user(project_id, user.id)
        if not deleted:
            log.warning(
                f"Delete blocked: Project {project_id} does not exist or unauthorized."
            )
            return temp.TemplateResponse(
                request, "404.html", status_code=status.HTTP_404_NOT_FOUND
            )

        return Response(status_code=200, headers={"HX-Redirect": "/projects"})

    except SQLAlchemyError as exc:
        log.error(f"Failed to delete project {project_id}: {exc}")
        return RedirectResponse(
            url="/projects", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
