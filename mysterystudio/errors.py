class AuthError(RuntimeError):
    """Credentials expired/revoked: a human must re-authorise. Never retried automatically."""


class QuotaError(RuntimeError):
    """Daily API quota exhausted. Retrying cannot help today."""
