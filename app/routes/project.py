from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse
from loguru import logger as log
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import DuplicateError, NotFoundError
from app.core.htmx import hx_toast_headers
from app.core.templates import temp
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import NewProject
from app.services.dependencies import current_user

project_router = APIRouter()


@project_router.get("/projects", response_class=HTMLResponse)
async def get_projects(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):

    projects = await ProjectRepository(db).list_for_user(user.id)
    return temp.TemplateResponse(
        request,
        "projects.html",
        {
            "projects": projects,
            "user": user,
            "page": "projects",
        },
    )


@project_router.post("/projects", response_class=HTMLResponse)
async def create_project(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
    name: str = Form(...),
):
    project = NewProject(name=name)
    repository = ProjectRepository(db)
    # check duplicate also in projects
    if await repository.get_for_user_project_name(
        project_name=project.name, user_id=user.id
    ):
        raise DuplicateError(message="Project with this name alraedy exists")
    new_project = await repository.create(project.name, user.id)
    return temp.TemplateResponse(
        request,
        "project_card.html",
        {"request": request, "project": new_project, "form_count": 0},
        headers=hx_toast_headers(
            f"Project '{new_project.name}' created successfully!", "success"
        ),
    )


@project_router.get("/projects/{project_id}", response_class=HTMLResponse)
async def get_project(
    request: Request,
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):

    project = await ProjectRepository(db).get_for_user(project_id, user.id)
    if not project:
        log.debug(f"Project not found. Id : {project_id}")
        raise NotFoundError(
            message="Project not found",
        )
    return temp.TemplateResponse(
        request,
        "project.html",
        {
            "project": project,
            "user": user,
            "page": "projects",
        },
    )


@project_router.put("/projects/{project_id}/settings", response_class=HTMLResponse)
async def update_project(
    request: Request,
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    project_name: str = Form(...),
):

    repository = ProjectRepository(db)
    project = await repository.get_for_user(project_id, user.id)
    if not project:
        log.warning(
            f"Project {project_id} not found or unauthorized for user {user.id}"
        )
        raise NotFoundError("Project not found")
    project_name_validated = NewProject(name=project_name)
    new_clean_name = project_name_validated.name

    # check duplicate also in projects
    if project.name != new_clean_name and await repository.get_for_user_project_name(
        project_name=new_clean_name, user_id=user.id
    ):
        raise DuplicateError("You already have a project with this name")
    project.name = project_name_validated.name
    await db.commit()
    await db.refresh(project)
    return temp.TemplateResponse(
        request,
        "partials/project_setting_form.html",
        context={"project": project},
        headers=hx_toast_headers("Project name updated", "success"),
        status_code=200,
    )


# --- DELETE PROJECT ---
@project_router.delete("/projects/{project_id}", response_class=HTMLResponse)
async def delete_project(
    request: Request,
    project_id: str,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):

    deleted = await ProjectRepository(db).delete_for_user(project_id, user.id)
    if not deleted:
        log.warning(
            f"Delete blocked: Project {project_id} does not exist or unauthorized."
        )
        raise NotFoundError("Failed to delete project")

    return Response(
        status_code=status.HTTP_200_OK,
        headers=hx_toast_headers(
            "Project deleted successfully", type_="sucess", redirect="/projects"
        ),
    )
