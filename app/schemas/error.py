class AuthenticationError(Exception):
    """Base exception for authentication failures."""



class TokenGenerationError(AuthenticationError):
    """Exception for token creation failures."""

