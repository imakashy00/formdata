import pytest
from starlette.responses import Response

from app.services.cookies import clear_auth_cookies, set_auth_cookies


def test_set_auth_cookies():
    """Verify set_auth_cookies sets access_token and refresh_token cookies with httponly flags."""
    resp = Response()
    set_auth_cookies(resp, access="access_123", refresh="refresh_456")
    
    cookies = [h[1] for h in resp.raw_headers if h[0] == b"set-cookie"]
    cookie_str = " ; ".join(cookies)
    assert "access_token=access_123" in cookie_str
    assert "refresh_token=refresh_456" in cookie_str
    assert "HttpOnly" in cookie_str or "httponly" in cookie_str


def test_clear_auth_cookies():
    """Verify clear_auth_cookies issues cookie deletion headers."""
    resp = Response()
    clear_auth_cookies(resp)
    
    cookies = [h[1] for h in resp.raw_headers if h[0] == b"set-cookie"]
    cookie_str = " ; ".join(cookies)
    assert 'access_token=""' in cookie_str or "Max-Age=0" in cookie_str or "expires=" in cookie_str
    assert 'refresh_token=""' in cookie_str or "Max-Age=0" in cookie_str or "expires=" in cookie_str
