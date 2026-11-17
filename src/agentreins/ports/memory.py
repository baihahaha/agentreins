"""MemoryStore port (ADR-0011)."""

from typing import Protocol

from agentreins.types.identity import Credentials
from agentreins.types.knowledge import MemoryItem


class MemoryStore(Protocol):
    """Long-term memory. The store keeps namespaces separate; agentreins adds no
    permission logic (D3)."""

    async def save(
        self, namespace: str, item: MemoryItem, credentials: Credentials | None
    ) -> str: ...

    async def search(
        self, namespace: str, query: str, top_k: int, credentials: Credentials | None
    ) -> list[MemoryItem]: ...

    async def delete(
        self, namespace: str, item_id: str, credentials: Credentials | None
    ) -> None: ...

    async def delete_all(self, namespace: str, credentials: Credentials | None) -> None: ...
