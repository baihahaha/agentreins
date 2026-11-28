"""ContextStrategy contract (ADR-0009 D2). Every strategy must pass every test here.

The strategy gets a long conversation and a small budget, and must keep:
1. tool calls together with their results, 2. (system instructions are not in the
messages; the context manager always sends them), 3. the first user message,
4. the latest message. To check a new strategy, add it to the ``strategy`` fixture.
"""

import pytest

from agentreins.adapters.context_strategies.keep_all import KeepAll
from agentreins.ports.context import ContextStrategy
from agentreins.types.content import Message, TextBlock, ToolResultBlock, ToolUseBlock


def conversation(turns: int = 20) -> list[Message]:
    messages = [Message.user("Original task: reconcile inventory.")]
    for i in range(turns):
        messages.append(
            Message(
                role="assistant",
                content=[ToolUseBlock(id=f"c{i}", name="lookup", arguments={"i": i})],
            )
        )
        messages.append(
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id=f"c{i}", content=[TextBlock(text="x" * 200)])],
            )
        )
    messages.append(Message.assistant("Summary so far."))
    messages.append(Message.user("Latest question?"))
    return messages


@pytest.fixture(params=[KeepAll()], ids=lambda s: type(s).__name__)
def strategy(request: pytest.FixtureRequest) -> ContextStrategy:
    return request.param


@pytest.mark.parametrize("budget", [50, 500, 100_000])
async def test_keeps_first_user_message_and_latest(strategy: ContextStrategy, budget: int) -> None:
    messages = conversation()
    chosen = await strategy.select(messages, budget)
    assert chosen[0] == messages[0]
    assert chosen[-1] == messages[-1]


@pytest.mark.parametrize("budget", [50, 500, 100_000])
async def test_never_separates_a_tool_call_from_its_result(
    strategy: ContextStrategy, budget: int
) -> None:
    chosen = await strategy.select(conversation(), budget)
    calls = {b.id for m in chosen for b in m.content if isinstance(b, ToolUseBlock)}
    results = {b.tool_use_id for m in chosen for b in m.content if isinstance(b, ToolResultBlock)}
    assert calls == results


async def test_only_chooses_never_invents(strategy: ContextStrategy) -> None:
    messages = conversation()
    chosen = await strategy.select(messages, 500)
    assert all(m in messages for m in chosen)
    assert [messages.index(m) for m in chosen] == sorted(messages.index(m) for m in chosen)
