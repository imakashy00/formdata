from authlib.integrations.starlette_client import OAuth
from fastapi import Request
from urllib.parse import urlparse

from app.core.settings import settings


def google_sheets_redirect_uri() -> str:
    """Return the one Google Sheets callback registered with Google OAuth."""
    return f"{str(settings.BASE_URL).rstrip('/')}/auth/google_sheets/callback"


oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile",
        "prompt": "consent",
        "access_type": "offline",
    },
)

oauth.register(
    name="google_sheets",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile https://www.googleapis.com/auth/drive.file",
        "prompt": "consent",
        "access_type": "offline",
    },
)


def get_oauth_redirect_uri(request: Request, name: str = "auth_callback") -> str:
    """
    Constructs a consistent HTTPS redirect URI for Google OAuth callbacks.
    Guarantees matching scheme and host across authorization redirects and direct token exchanges.
    """
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    base_url_str = str(settings.BASE_URL).rstrip("/")

    # If the app is accessed via a remote domain or BASE_URL is remote, use HTTPS
    if ("localhost" in host or "127.0.0.1" in host) and "localhost" not in base_url_str and "127.0.0.1" not in base_url_str:
        parsed = urlparse(base_url_str)
        if parsed.netloc:
            host = parsed.netloc

    scheme = "https" if ("localhost" not in host and "127.0.0.1" not in host) else (request.headers.get("x-forwarded-proto") or request.url.scheme)

    try:
        path = request.app.url_path_for(name)
    except Exception:
        path = "/auth/callback"

    return f"{scheme}://{host}{path}"
