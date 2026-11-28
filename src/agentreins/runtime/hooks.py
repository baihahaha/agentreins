"""Hook dispatch: calls registered hooks; failures are logged, never stop the run (ADR-0007)."""

import asyncio
import logging
from collections.abc import Sequence

from agentreins.ports.hooks import Hooks
from agentreins.types.events import Event
from agentreins.types.model import ModelStreamEvent

logger = logging.getLogger("agentreins.hooks")


class HookDispatcher:
    """Sends every event and stream delta to each hook, in registration order.

    Each call has ``timeout`` seconds. A hook that raises or times out is logged and
    skipped: hooks observe a run, they never change or stop it (ADR-0007 D2, D3).
    """

    def __init__(self, hooks: Sequence[Hooks] = (), *, timeout: float = 1.0) -> None:
        self._hooks = list(hooks)
        self._timeout = timeout

    @property
    def active(self) -> bool:
        """True if any hook is registered (then the runtime streams model replies)."""
        return bool(self._hooks)

    async def emit(self, event: Event | ModelStreamEvent) -> None:
        """Deliver ``event`` to every hook. Never raises."""
        for hook in self._hooks:
            try:
                async with asyncio.timeout(self._timeout):
                    await hook.on_event(event)
            except Exception:
                logger.warning(
                    "hook %s failed on %s; continuing",
                    type(hook).__name__,
                    event.type,
                    exc_info=True,
                )
