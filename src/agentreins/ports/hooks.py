"""Hooks port (ADR-0007)."""

from typing import Protocol

from agentreins.types.events import Event
from agentreins.types.model import ModelStreamEvent


class Hooks(Protocol):
    """Observes every event and stream delta. Optional; cannot change or stop a run.
    Failures are logged and the run continues (D2, D3)."""

    async def on_event(self, event: Event | ModelStreamEvent) -> None:
        """Called for every stored event and every stream delta. Must not raise."""
        ...
