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
    """The provider is throttling us. Retry, after ``retry_after`` seconds if given."""

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
    """The provider is down or returned a server error. Retry."""

    retryable = True


class ModelTimeout(ModelError):
    """Named ``Timeout`` in ADR-0002; renamed to avoid confusion with ``TimeoutError``."""

    retryable = True


class ContextTooLong(ModelError):
    """Not retryable as-is: the context manager must shrink the request first."""


class AuthFailed(ModelError):
    """The API key is missing, wrong or lacks permission. Not retryable."""

    pass


class BadRequest(ModelError):
    """The provider rejected the request as malformed. Not retryable."""

    pass


# --- other errors ------------------------------------------------------------------


class CapabilityError(AgentReinsError):
    """A request needs something the adapter does not support (ADR-0002 D8)."""


class ConflictError(AgentReinsError):
    """Another writer appended to the run first (ADR-0005 D2)."""


class RedactionError(AgentReinsError):
    """The redactor failed or broke its contract; the event was not stored (ADR-0006 D3)."""


# --- tool errors (ADR-0003, ADR-0004, ADR-0008) --------------------------------------


class InvalidToolArguments(AgentReinsError):
    """A tool source rejected the arguments; the message is shown to the model."""


class CredentialsUnavailable(AgentReinsError):
    """A CredentialProvider could not supply a credential. Never include the secret."""


class PolicyUnavailable(AgentReinsError):
    """The policy raised or timed out and the harness is set to fail the run (ADR-0004 D3)."""
