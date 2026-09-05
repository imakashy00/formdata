from authlib.integrations.starlette_client import OAuth

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
