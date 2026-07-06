from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from loguru import logger as log
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.templates import temp
from app.models.user import User
from app.schemas.user import DBUser
from app.services.auth import AuthService
from app.services.dependencies import current_user

page_router = APIRouter()


async def get_authenticated_user(request: Request, db: AsyncSession):
    """Helper function to reuse your authentication logic across routes."""
    access_token = request.cookies.get("access_token")
    if not access_token:
        return None

    try:
        payload = await AuthService.validate_access(access_token)
        result = await db.execute(select(User).filter(User.id == payload["sub"]))
        return result.scalars().first()
    except Exception:
        return None


@page_router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    user_db = await get_authenticated_user(request, db)
    if not user_db:
        return temp.TemplateResponse(request, "index.html")

    return temp.TemplateResponse(
        request,
        "dashboard.html",
        {
            "email": user_db.email,
            "name": user_db.name,
            "user_id": user_db.id,
            "page": "dashboard",
        },
    )


@page_router.get("/projects", response_class=HTMLResponse)
async def projects(request: Request, db: AsyncSession = Depends(get_db)):
    user_db = await get_authenticated_user(request, db)
    if not user_db:
        return temp.TemplateResponse(request, "index.html")

    return temp.TemplateResponse(
        request,
        "projects.html",
        {
            "email": user_db.email,
            "name": user_db.name,
            "user_id": user_db.id,
            "page": "projects",
        },
    )


@page_router.get("/account", response_class=HTMLResponse)
async def account(request: Request, db: AsyncSession = Depends(get_db)):
    user_db = await get_authenticated_user(request, db)
    if not user_db:
        return temp.TemplateResponse(request, "index.html")

    return temp.TemplateResponse(
        request,
        "account.html",
        {
            "email": user_db.email,
            "name": user_db.name,
            "user_id": user_db.id,
            "page": "account",
        },
    )


@page_router.get("/billing", response_class=HTMLResponse)
async def billing(request: Request, db: AsyncSession = Depends(get_db)):
    user_db = await get_authenticated_user(request, db)
    if not user_db:
        return temp.TemplateResponse(request, "index.html")

    return temp.TemplateResponse(
        request,
        "billing.html",
        {
            "email": user_db.email,
            "name": user_db.name,
            "user_id": user_db.id,
            "page": "billing",
        },
    )


@page_router.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    return FileResponse("app/static/favicon.svg")


@page_router.get("/robots.txt", include_in_schema=False)
def robots_txt():
    return FileResponse("app/static/robots.txt", media_type="text/plain")


@page_router.get("/help", response_class=HTMLResponse)
async def help_page(
    request: Request,
    user: DBUser = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    log.info("Help page sending")
    return temp.TemplateResponse(
        request,
        "help.html",
    )


@page_router.get("/blogs", response_class=HTMLResponse)
async def blogs(request: Request):
    log.info("Blogs")


@page_router.get("/blogs/{blog_id}", response_class=HTMLResponse)
async def blog(req: Request, blog_id: str):
    log.info(f"Blog with id {blog_id}")


@page_router.get("/privacy-policy", response_class=HTMLResponse)
async def privacy_policy(request: Request):
    """Privacy Policy page"""
    return temp.TemplateResponse(request, "privacy.html")


@page_router.get("/terms", response_class=HTMLResponse)
async def terms_and_conditions(request: Request):
    """Terms and Conditions page"""
    return temp.TemplateResponse(request, "terms.html")


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
        except Exception:
            return False

    today = datetime.now(timezone.utc).date().isoformat()

    # Core URLs to include
    url_defs = [
        {"loc": f"{base}/", "changefreq": "daily", "priority": "1.0", "lastmod": today},
    ]

    # Optional pages if present in the app
    optional_paths = [
        ("/help", "monthly", "0.4"),
        ("/blogs", "weekly", "0.5"),
        ("/privacy-policy", "yearly", "0.3"),
        ("/terms", "yearly", "0.3"),
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
