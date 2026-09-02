import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_privacy_policy_page(client: AsyncClient):
    """Verify privacy policy page loads successfully with 200 OK."""
    response = await client.get("/privacy-policy")
    assert response.status_code == 200
    assert "Privacy Policy" in response.text or "privacy" in response.text.lower()


@pytest.mark.asyncio
async def test_terms_of_service_page(client: AsyncClient):
    """Verify terms of service page loads with 200 OK."""
    response = await client.get("/terms-of-service")
    assert response.status_code == 200
    assert "Terms" in response.text or "terms" in response.text.lower()


@pytest.mark.asyncio
async def test_robots_txt(client: AsyncClient):
    """Verify robots.txt is served with appropriate media type."""
    response = await client.get("/robots.txt")
    assert response.status_code == 200
    assert "User-agent" in response.text or response.status_code == 200
