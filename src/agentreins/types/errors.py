"""agentreins exceptions."""

from typing import ClassVar


class AgentReinsError(Exception):
    """Base class for all agentreins errors."""


# --- model errors (ADR-0002 D5): adapters raise these, the runtime decides on retries ---


class ModelError(AgentReinsError):
    """A model call failed. ``retryable`` tells the runtime whether to try again."""

    retryable: ClassVar[bool] = False

    def __init__(
        self, message: str, *, provider: str | None = None, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class RateLimited(ModelError):
    retryable = True

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        provider: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message, provider=provider, status_code=status_code)
        self.retry_after = retry_after
        """Seconds the provider asked us to wait, if it said."""


class ProviderUnavailable(ModelError):
    retryable = True


class ModelTimeout(ModelError):
    """Named ``Timeout`` in ADR-0002; renamed to avoid confusion with ``TimeoutError``."""

    retryable = True


class ContextTooLong(ModelError):
    """Not retryable as-is: the context manager must shrink the request first."""


class AuthFailed(ModelError):
    pass


class BadRequest(ModelError):
    pass


# --- other errors ------------------------------------------------------------------


class CapabilityError(AgentReinsError):
    """A request needs something the adapter does not support (ADR-0002 D8)."""


class ConflictError(AgentReinsError):
    """Another writer appended to the run first (ADR-0005 D2)."""
