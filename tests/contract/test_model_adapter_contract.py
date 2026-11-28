"""ModelAdapter contract (ADR-0002 D1, D7). Every adapter must pass every test here.

Each adapter is set up to give the same scripted answer twice: once for
``get_response`` and once for ``stream_response``. To check a new adapter, add it to
the ``adapter`` fixture.
"""

import json
from collections.abc import Callable

import pytest

from agentreins.adapters.models.fake import FakeModel
from agentreins.ports.model import ModelAdapter
from agentreins.types.content import Message, ReasoningBlock, TextBlock, ToolUseBlock
from agentreins.types.model import (
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ReasoningDelta,
    ResponseComplete,
    TextDelta,
    ToolArgsDelta,
    ToolUseStart,
)
from openai_fakes import FakeProvider, Reply

REQUEST = ModelRequest(model="test", messages=[Message.user("Check stock for W1 and W2.")])

# The same answer, described for each adapter: some reasoning, text, two tool calls.
ANSWER = Reply(
    text="Checking both.",
    reasoning="Two lookups needed.",
    calls=[("call_1", "get_stock", '{"sku": "W1"}'), ("call_2", "get_stock", '{"sku": "W2"}')],
    finish="tool_calls",
)


def fake_model() -> ModelAdapter:
    reply = ModelResponse(
        message=Message(
            role="assistant",
            content=[
                ReasoningBlock(text=ANSWER.reasoning),
                TextBlock(text=ANSWER.text),
                ToolUseBlock(id="a", name="get_stock", arguments={"sku": "W1"}),
                ToolUseBlock(id="b", name="get_stock", arguments={"sku": "W2"}),
            ],
        ),
        stop_reason="tool_use",
        usage=FakeModel.reply("").usage,
        model="fake",
    )
    return FakeModel([reply, reply], chunk_size=3)


def openai_model() -> ModelAdapter:
    return FakeProvider(ANSWER).model()


ADAPTERS: dict[str, Callable[[], ModelAdapter]] = {
    "fake": fake_model,
    "openai_compat": openai_model,
}


@pytest.fixture(params=list(ADAPTERS))
def adapter(request: pytest.FixtureRequest) -> ModelAdapter:
    return ADAPTERS[request.param]()


def normalized(response: ModelResponse) -> ModelResponse:
    """Tool-call IDs are freshly minted per call; compare everything else."""
    content = [
        b.model_copy(update={"id": f"call-{i}"}) if isinstance(b, ToolUseBlock) else b
        for i, b in enumerate(response.message.content)
    ]
    return response.model_copy(update={"message": Message(role="assistant", content=content)})


async def collect(adapter: ModelAdapter) -> list[ModelStreamEvent]:
    return [event async for event in adapter.stream_response(REQUEST)]


async def test_stream_and_get_response_agree(adapter: ModelAdapter) -> None:
    whole = await adapter.get_response(REQUEST)
    events = await collect(adapter)
    final = events[-1]
    assert isinstance(final, ResponseComplete)
    assert normalized(final.response) == normalized(whole)


async def test_stream_ends_with_exactly_one_complete_response(adapter: ModelAdapter) -> None:
    events = await collect(adapter)
    assert isinstance(events[-1], ResponseComplete)
    assert sum(isinstance(e, ResponseComplete) for e in events) == 1


async def test_deltas_add_up_to_the_final_response(adapter: ModelAdapter) -> None:
    events = await collect(adapter)
    final = events[-1]
    assert isinstance(final, ResponseComplete)
    content = final.response.message.content
    text = "".join(b.text for b in content if isinstance(b, TextBlock))
    reasoning = "".join(b.text for b in content if isinstance(b, ReasoningBlock))
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == text
    assert "".join(e.text for e in events if isinstance(e, ReasoningDelta)) == reasoning
    calls = [b for b in content if isinstance(b, ToolUseBlock)]
    starts = [e for e in events if isinstance(e, ToolUseStart)]
    assert [(s.id, s.name) for s in starts] == [(c.id, c.name) for c in calls]
    for call in calls:
        args = "".join(e.delta for e in events if isinstance(e, ToolArgsDelta) and e.id == call.id)
        assert json.loads(args) == call.arguments


async def test_response_is_well_formed(adapter: ModelAdapter) -> None:
    response = await adapter.get_response(REQUEST)
    assert response.message.role == "assistant"
    assert response.stop_reason == "tool_use"
    calls = [b for b in response.message.content if isinstance(b, ToolUseBlock)]
    assert [c.arguments for c in calls] == [{"sku": "W1"}, {"sku": "W2"}]
    assert len({c.id for c in calls}) == 2  # agentreins call IDs are unique


def test_capabilities_are_declared(adapter: ModelAdapter) -> None:
    assert adapter.capabilities.max_context_tokens > 0
