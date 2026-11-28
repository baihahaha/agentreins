"""Context manager: decides what the model sees each turn (ADR-0009).

History comes from the event log (``project_messages``); this module only decides
whether it fits, and asks the strategy to choose when it does not. Retrieved documents
and memories join in later milestones (ADR-0010, ADR-0011).
"""

import json
from collections.abc import Sequence

from agentreins.ports.context import ContextStrategy
from agentreins.types.content import Message
from agentreins.types.tools import ToolSpec

CHARS_PER_TOKEN = 4
"""Rough estimate used when the adapter cannot count tokens (ADR-0002 D9)."""


def estimate_tokens(
    messages: Sequence[Message], system: str | None = None, tools: Sequence[ToolSpec] = ()
) -> int:
    """Estimate the input tokens of a request: about 4 characters per token."""
    chars = len(system or "")
    chars += sum(len(m.model_dump_json()) for m in messages)
    chars += sum(len(json.dumps(t.model_dump(mode="json"))) for t in tools)
    return chars // CHARS_PER_TOKEN + 1


class ContextManager:
    """Runs the strategy only when the request would pass ``threshold`` of the window.

    The log is never shortened: the strategy chooses what is *sent* this turn.
    """

    def __init__(
        self, strategy: ContextStrategy, max_context_tokens: int, threshold: float = 0.8
    ) -> None:
        if not 0 < threshold <= 1:
            raise ValueError("threshold must be between 0 and 1")
        self._strategy = strategy
        self._budget = int(max_context_tokens * threshold)

    async def select(
        self, messages: list[Message], *, system: str | None, tools: Sequence[ToolSpec]
    ) -> list[Message]:
        """The messages to send this turn: all of them if they fit, else the strategy's pick."""
        if estimate_tokens(messages, system, tools) <= self._budget:
            return messages
        return await self._choose(messages, system, tools)

    async def shrink(
        self, messages: list[Message], *, system: str | None, tools: Sequence[ToolSpec]
    ) -> list[Message] | None:
        """After the provider said ``ContextTooLong``: a smaller pick, or None if the
        strategy cannot make it smaller (then retrying is pointless)."""
        chosen = await self._choose(messages, system, tools, factor=0.5)
        return chosen if len(chosen) < len(messages) else None

    async def _choose(
        self,
        messages: list[Message],
        system: str | None,
        tools: Sequence[ToolSpec],
        factor: float = 1.0,
    ) -> list[Message]:
        overhead = estimate_tokens([], system, tools)
        return await self._strategy.select(messages, max(int(self._budget * factor) - overhead, 0))
