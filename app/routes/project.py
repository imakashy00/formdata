import re
import json

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from loguru import logger as log
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from app.core.db import get_db
from app.models.user import Project, User
from app.routes.page import get_current_user
from app.core.templates import temp

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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(
            select(Project)
            .where(Project.user_id == user.id)
            .order_by(desc(Project.updated_at), desc(Project.created_at))
        )
        projects = result.scalars().all()
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
    except Exception as e:
        log.warning(f"Errror fetching Projects{e}")


@project_router.post("/projects", response_class=HTMLResponse)
async def create_project(
    request: Request,
    name: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        project = NewProject(name=name)
        new_project = Project(name=project.name, user_id=user.id)
        db.add(new_project)
        await db.commit()

        result = await db.execute(
            select(Project)
            .where(Project.user_id == user.id)
            .order_by(desc(Project.updated_at), desc(Project.created_at))
        )
        projects = result.scalars().all()
        trigger_payload = json.dumps(
            {"showToast": f"Project '{new_project.name}' created successfully!"}
        )
        # return RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)
        return temp.TemplateResponse(
            request,
            "projects.html",
            {"request": request, "projects": projects},
            headers={
                "HX-Trigger": trigger_payload
            },  # 👈 HTMX automatically listens to this
        )

    except ValidationError as exc:
        log.warning(f"Failed to create new Project: {exc}")
        error_msg = exc.errors()[0]["msg"]
        log.warning(f"Validation failed for new project: {error_msg}")
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
    except Exception as exc:
        log.error(f"Failed to create new Project due to system error: {exc}")
        return temp.TemplateResponse(
            request,
            "projects.html",
            {"request": request, "error": "Something went wrong on our end."},
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@project_router.get("/projects/{project_id}", response_class=HTMLResponse)
async def get_project(
    request: Request,
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(
            select(Project)
            .options(selectinload(Project.forms))
            .where(Project.user_id == user.id)
            .where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        # print(project)
        return temp.TemplateResponse(
            request,
            "forms.html",
            {
                "project": project,
                "email": user.email,
                "name": user.name,
                "user_id": user.id,
                "page": "projects",
            },
        )
    except Exception as e:
        log.warning(f"Errror fetching Project{e}")


@project_router.get("/projects/{project_id}/update", response_class=HTMLResponse)
async def get_project(
    request: Request,
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await db.execute(
            select(Project)
            .options(selectinload(Project.forms))
            .where(Project.user_id == user.id)
            .where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        # print(project)
        return temp.TemplateResponse(
            request,
            "forms.html",
            {
                "project": project,
                "email": user.email,
                "name": user.name,
                "user_id": user.id,
                "page": "projects",
            },
        )
    except Exception as e:
        log.warning(f"Errror fetching Project{e}")


@project_router.put("/projects/{project_id}", response_class=HTMLResponse)
async def update_project(
    request: Request,
    project_id: str,
    name: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        # 1. Fetch project and verify ownership security
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user.id)
        )
        project = result.scalars().first()

        if not project:
            log.warning(
                f"Project {project_id} not found or unauthorized for user {user.id}"
            )
            return temp.TemplateResponse(
                request, "404.html", status_code=status.HTTP_404_NOT_FOUND
            )

        # 2. Validate the new name incoming input data
        project_name_validated = NewProject(name=name)

        # 3. Commit changes to DB
        project.name = project_name_validated.name
        await db.commit()

        return RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)

    except ValidationError as exc:
        error_msg = exc.errors()[0]["msg"]
        log.warning(f"Validation failed during project update: {error_msg}")
        return temp.TemplateResponse(
            request,
            "edit_project_form.html",
            {
                "request": request,
                "error": error_msg,
                "project": name,  # Send back old details so form fields stay populated
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        log.error(f"Failed to update project {project_id}: {exc}")
        return RedirectResponse(
            url="/projects", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# --- DELETE PROJECT ---
@project_router.delete("/projects/{project_id}", response_class=HTMLResponse)
async def delete_project(
    request: Request,
    project_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Find project ensuring ownership validation
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user.id)
        )
        project = result.scalars().first()

        if not project:
            log.warning(
                f"Delete blocked: Project {project_id} does not exist or unauthorized."
            )
            return temp.TemplateResponse(
                request, "404.html", status_code=status.HTTP_404_NOT_FOUND
            )

        await db.delete(project)
        await db.commit()

        return RedirectResponse(url="/projects", status_code=status.HTTP_303_SEE_OTHER)

    except Exception as exc:
        log.error(f"Failed to delete project {project_id}: {exc}")
        return RedirectResponse(
            url="/projects", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
