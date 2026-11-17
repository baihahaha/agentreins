"""Redactor port (ADR-0006)."""

from typing import Protocol

from agentreins.types.events import Event


class Redactor(Protocol):
    """Applied by the ledger before every append. May change content only; IDs,
    sequence number and type must stay unchanged. If it raises, the run fails (D3)."""

    async def redact(self, event: Event) -> Event: ...
