from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from loguru import logger as log

from app.core.templates import temp
from app.models.user import User
from app.services.dependencies import current_user

page_router = APIRouter()

BLOG_ARTICLES = {
    "how-to-add-a-contact-form-to-a-static-html-website": {
        "slug": "how-to-add-a-contact-form-to-a-static-html-website",
        "title": "How to Add a Contact Form to a Static HTML Website",
        "template": "blog_detail.html",
    }
}


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
    """Blog index page listing articles."""
    return temp.TemplateResponse(
        request=request,
        name="blogs.html",
        context={"request": request},
    )


@page_router.get("/blogs/{blog_id}", response_class=HTMLResponse)
async def blog(request: Request, blog_id: str):
    """Individual blog article page."""
    normalized_slug = blog_id.strip().lower()
    if normalized_slug in BLOG_ARTICLES or normalized_slug in ("1", "how-to-add-a-contact-form"):
        article_key = (
            "how-to-add-a-contact-form-to-a-static-html-website"
            if normalized_slug in ("1", "how-to-add-a-contact-form")
            else normalized_slug
        )
        return temp.TemplateResponse(
            request=request,
            name=BLOG_ARTICLES[article_key]["template"],
            context={
                "request": request,
                "article": BLOG_ARTICLES[article_key],
            },
        )
    return temp.TemplateResponse(
        request=request,
        name="404.html",
        context={"request": request},
        status_code=404,
    )


@page_router.get("/blog", include_in_schema=False)
async def blog_redirect():
    return RedirectResponse(url="/blogs", status_code=301)


@page_router.get("/blog/{blog_id}", include_in_schema=False)
async def blog_detail_redirect(blog_id: str):
    return RedirectResponse(url=f"/blogs/{blog_id}", status_code=301)


@page_router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    """Privacy Policy page"""
    return temp.TemplateResponse(
        request=request, name="privacy_policy.html", context={"request": request}
    )


@page_router.get("/terms-of-service", response_class=HTMLResponse)
async def terms_and_conditions(request: Request):
    """Terms and Conditions page"""
    return temp.TemplateResponse(
        request=request, name="terms_of_service.html", context={"request": request}
    )


@page_router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml() -> FileResponse:
    return FileResponse(
        "app/static/sitemap.xml",
        media_type="application/xml",
    )


@page_router.get("/llms.txt", include_in_schema=False)
async def llms_txt() -> FileResponse:
    return FileResponse("app/static/llms.txt", media_type="text/plain")
