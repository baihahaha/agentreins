"""ModelAdapter port (ADR-0002)."""

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from agentreins.types.model import ModelCapabilities, ModelRequest, ModelResponse, ModelStreamEvent


class ModelAdapter(Protocol):
    """Talks to one model provider.

    Adapters never retry: they raise normalized errors and the runtime retries (D5).
    For the same request, both methods must produce the same final response (D1).
    """

    @property
    def capabilities(self) -> ModelCapabilities:
        """What this adapter supports; checked by the core before sending (D8)."""
        ...

    async def get_response(self, request: ModelRequest) -> ModelResponse:
        """Send the request and return the complete response."""
        ...

    def stream_response(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        """Send the request and yield events; the last one is the complete response (D7)."""
        ...


@runtime_checkable
class TokenCounter(Protocol):
    """Optional: exact token counting. Without it the core estimates (D9)."""

    async def count_tokens(self, request: ModelRequest) -> int: ...
