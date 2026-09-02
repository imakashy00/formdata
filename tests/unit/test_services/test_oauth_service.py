import pytest

from app.services.oauth import oauth


def test_oauth_registry():
    """Verify OAuth registry contains configured Google provider."""
    assert oauth is not None
    assert "google" in oauth._clients or hasattr(oauth, "google")
