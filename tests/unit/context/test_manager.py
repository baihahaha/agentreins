"""Context manager: run the strategy only when the request would not fit."""

import pytest

from agentreins.adapters.context_strategies.keep_all import KeepAll
from agentreins.context.manager import ContextManager, estimate_tokens
from agentreins.types.content import Message
from agentreins.types.tools import Effect, ToolSpec

SPEC = ToolSpec(name="t", description="d" * 400, input_schema={}, effect=Effect.READ_ONLY)


class Recording:
    def __init__(self, keep: int = 1) -> None:
        self.budgets: list[int] = []
        self.keep = keep

    async def select(self, messages: list[Message], token_budget: int) -> list[Message]:
        self.budgets.append(token_budget)
        return messages[-self.keep :]


def test_estimate_counts_system_messages_and_tools() -> None:
    base = estimate_tokens([Message.user("x" * 400)])
    assert 100 <= base <= 130
    assert estimate_tokens([Message.user("x" * 400)], "s" * 400, [SPEC]) > base + 150


async def test_strategy_not_called_when_it_fits() -> None:
    strategy = Recording()
    manager = ContextManager(strategy, max_context_tokens=10_000)
    messages = [Message.user("hi"), Message.assistant("hello")]
    assert await manager.select(messages, system=None, tools=[]) == messages
    assert strategy.budgets == []


async def test_strategy_called_above_the_threshold_with_room_left_for_overhead() -> None:
    strategy = Recording()
    manager = ContextManager(strategy, max_context_tokens=1_000, threshold=0.8)
    messages = [Message.user("x" * 4_000), Message.user("latest")]
    chosen = await manager.select(messages, system="s" * 400, tools=[SPEC])
    assert chosen == messages[-1:]
    [budget] = strategy.budgets
    assert budget < 800  # 80% of the window, minus system prompt and tool specs


async def test_shrink_returns_none_when_nothing_can_be_dropped() -> None:
    manager = ContextManager(KeepAll(), max_context_tokens=1_000)
    messages = [Message.user("a"), Message.user("b")]
    assert await manager.shrink(messages, system=None, tools=[]) is None
    smaller = await ContextManager(Recording(), max_context_tokens=1_000).shrink(
        messages, system=None, tools=[]
    )
    assert smaller == messages[-1:]


def test_threshold_must_be_a_fraction() -> None:
    with pytest.raises(ValueError, match="threshold"):
        ContextManager(KeepAll(), max_context_tokens=1_000, threshold=1.5)
