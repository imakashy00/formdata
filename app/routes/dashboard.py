from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.models.user import User
from app.routes.page import get_current_user
from app.core.templates import temp

dash_router = APIRouter()


@dash_router.get("/", response_class=HTMLResponse)
async def home(request: Request, user: User | None = Depends(get_current_user)):
    if not user:
        return temp.TemplateResponse(request, "index.html")
    return temp.TemplateResponse(
        request,
        "dashboard.html",
        {
            "email": user.email,
            "name": user.name,
            "user_id": user.id,
            "page": "dashboard",
        },
    )
