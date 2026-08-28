from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger as log

from app.core.templates import temp
from app.models.user import User
from app.services.dependencies import current_user

page_router = APIRouter()


@page_router.get("/billing", response_class=HTMLResponse)
async def billing(request: Request, user: Annotated[User, Depends(current_user)]):

    return temp.TemplateResponse(
        request,
        "billing.html",
        {
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "billing",
        },
    )


@page_router.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    return FileResponse("app/static/favicon.svg")


@page_router.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return FileResponse("app/static/robots.txt", media_type="text/plain")


@page_router.get("/blogs", response_class=HTMLResponse)
async def blogs(request: Request):
    log.info("Blogs")


@page_router.get("/blogs/{blog_id}", response_class=HTMLResponse)
async def blog(req: Request, blog_id: str):
    log.info(f"Blog with id {blog_id}")


@page_router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    """Privacy Policy page"""
    return temp.TemplateResponse(request, "privacy_policy.html")


@page_router.get("/terms-of-service", response_class=HTMLResponse)
async def terms_and_conditions(request: Request):
    """Terms and Conditions page"""
    return temp.TemplateResponse(request, "terms_of_service.html")


@page_router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml() -> FileResponse:
    return FileResponse(
        "app/static/sitemap.xml",
        media_type="application/xml",
    )


@page_router.get("/llms.txt", include_in_schema=False)
async def llms_txt() -> FileResponse:
    return FileResponse("app/static/llms.txt", media_type="text/plain")
