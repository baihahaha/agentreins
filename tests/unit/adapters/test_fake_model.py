"""FakeModel: scripted replies for tests and examples."""

import pytest

from agentreins.adapters.models.fake import FakeModel, stream_events
from agentreins.types.content import Message, ToolUseBlock
from agentreins.types.errors import RateLimited
from agentreins.types.model import (
    ModelRequest,
    ModelResponse,
    ResponseComplete,
    TextDelta,
    ToolArgsDelta,
    ToolUseStart,
    UsageUpdate,
)


def ask(text: str = "hi") -> ModelRequest:
    return ModelRequest(model="fake", messages=[Message.user(text)])


async def test_replies_in_script_order_and_records_requests() -> None:
    model = FakeModel([FakeModel.call("get_stock", {"sku": "W1"}), FakeModel.reply("7 in stock")])
    first = await model.get_response(ask("stock?"))
    assert first.stop_reason == "tool_use"
    [call] = [b for b in first.message.content if isinstance(b, ToolUseBlock)]
    assert (call.name, call.arguments) == ("get_stock", {"sku": "W1"})
    second = await model.get_response(ask("and?"))
    assert second.message.text == "7 in stock"
    assert [r.messages[0].text for r in model.requests] == ["stock?", "and?"]
    assert model.remaining == 0


async def test_scripted_errors_and_functions() -> None:
    def echo(request: ModelRequest) -> ModelResponse:
        return FakeModel.reply(f"you said {request.messages[-1].text}")

    model = FakeModel([RateLimited("slow down", retry_after=1), echo])
    with pytest.raises(RateLimited):
        await model.get_response(ask())
    assert (await model.get_response(ask("ping"))).message.text == "you said ping"


async def test_exhausted_script_says_so() -> None:
    model = FakeModel([FakeModel.reply("only one")])
    await model.get_response(ask())
    with pytest.raises(RuntimeError, match="exhausted after 1 calls"):
        await model.get_response(ask())


async def test_stream_is_derived_from_the_same_script() -> None:
    reply = FakeModel.call("get_stock", {"sku": "W1"}, text="Let me check the stock.")
    events = [e async for e in FakeModel([reply], chunk_size=4).stream_response(ask())]
    assert isinstance(events[-1], ResponseComplete)
    assert events[-1].response == reply
    assert isinstance(events[-2], UsageUpdate)
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text == "Let me check the stock."
    [start] = [e for e in events if isinstance(e, ToolUseStart)]
    args = "".join(e.delta for e in events if isinstance(e, ToolArgsDelta) and e.id == start.id)
    assert args == '{"sku": "W1"}'


def test_stream_events_end_with_the_response() -> None:
    reply = FakeModel.reply("")
    assert stream_events(reply) == [
        UsageUpdate(usage=reply.usage),
        ResponseComplete(response=reply),
    ]
