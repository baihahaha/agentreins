"""ContextStrategy and Retriever ports (ADR-0009, ADR-0010)."""

from collections.abc import Mapping
from typing import Protocol

from agentreins.types.content import Message
from agentreins.types.identity import Credentials
from agentreins.types.knowledge import Document


class ContextStrategy(Protocol):
    """Chooses what to send to the model this turn; never modifies the log.

    Every strategy must keep the four rules of ADR-0009 D2 (checked by contract tests).
    """

    async def select(self, messages: list[Message], token_budget: int) -> list[Message]: ...


class Retriever(Protocol):
    """Vector or keyword search. No permission logic: the search system filters
    using the principal's credentials (ADR-0010 D3)."""

    async def search(
        self,
        query: str,
        credentials: Credentials | None,
        top_k: int,
        filters: Mapping[str, object] | None,
    ) -> list[Document]: ...
