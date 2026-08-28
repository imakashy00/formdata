from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger as log
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
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
async def sitemap_xml(request: Request) -> Response:
    """Dynamically generate a minimal, SEO-friendly XML sitemap.

    Includes publicly accessible pages only. Uses the incoming request's base URL
    so it works across localhost, ngrok, and production.
    """
    base = str(request.base_url).rstrip("/")

    def route_exists(path: str) -> bool:
        try:
            return any(getattr(r, "path", None) == path for r in request.app.routes)
        except ValueError:
            return False

    today = datetime.now(UTC).date().isoformat()

    # Core URLs to include
    url_defs = [
        {"loc": f"{base}/", "changefreq": "daily", "priority": "1.0", "lastmod": today},
    ]

    # Optional pages if present in the app
    optional_paths = [
        ("/help", "monthly", "0.4"),
        ("/blogs", "weekly", "0.5"),
        ("/privacy-policy", "yearly", "0.3"),
        ("/terms-of-service", "yearly", "0.3"),
    ]

    for path, changefreq, priority in optional_paths:
        if route_exists(path):
            url_defs.append(
                {
                    "loc": f"{base}{path}",
                    "changefreq": changefreq,
                    "priority": priority,
                    "lastmod": today,
                }
            )

    # Build XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for u in url_defs:
        lines.append("  <url>")
        lines.append(f"    <loc>{u['loc']}</loc>")
        lines.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        lines.append(f"    <priority>{u['priority']}</priority>")
        lines.append("  </url>")
    lines.append("</urlset>")

    xml = "\n".join(lines) + "\n"
    return Response(content=xml, media_type="application/xml")
