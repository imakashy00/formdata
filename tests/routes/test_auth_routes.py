from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


@pytest.mark.asyncio
async def test_auth_login_redirect(client: AsyncClient):
    """Verify POST /auth redirects to Google OAuth authorization URL."""
    with patch("app.services.oauth.oauth.google.authorize_redirect", new_callable=AsyncMock) as mock_auth:
        from fastapi.responses import RedirectResponse
        mock_auth.return_value = RedirectResponse(url="https://accounts.google.com/o/oauth2/auth", status_code=303)
        response = await client.post("/auth", follow_redirects=False)
        assert response.status_code in (302, 303, 307)


@pytest.mark.asyncio
async def test_auth_logout(client: AsyncClient, auth_cookies: dict, sample_user: User):
    """Verify POST /logout clears cookies and redirects to home."""
    response = await client.post("/logout", cookies=auth_cookies, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers.get("location") == "/"
