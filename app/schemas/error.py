class AuthenticationError(Exception):
    """Base exception for authentication failures."""

    pass


class TokenGenerationError(AuthenticationError):
    """Exception for token creation failures."""

    pass
