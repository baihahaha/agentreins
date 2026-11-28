"""Agent(output_type=...): answers come back validated and typed."""

from typing import Any

import pytest
from pydantic import BaseModel, Field

from agentreins import Agent, RunError, tool
from agentreins.adapters.event_stores.in_memory import InMemoryEventStore
from agentreins.runtime.output import FINAL_RESULT
from agentreins.testing import FakeModel
from agentreins.types.content import Message, TextBlock, ToolResultBlock
from agentreins.types.events import (
    Event,
    MessageAdded,
    RunCompleted,
    RunStarted,
    ToolCallCompleted,
    ToolCallRejected,
)
from agentreins.types.model import ModelResponse


class Order(BaseModel):
    sku: str
    quantity: int = Field(gt=0)


@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Units on hand."""
    return 7


ORDERED: list[str] = []


@tool
def create_po(sku: str) -> str:
    """Create a purchase order."""
    ORDERED.append(sku)
    return "PO-1"


def answer(**arguments: Any) -> ModelResponse:
    return FakeModel.call(FINAL_RESULT, arguments)


def together(*replies: ModelResponse) -> ModelResponse:
    """One model reply holding all the given replies' tool calls."""
    content = [block for r in replies for block in r.message.content]
    return replies[0].model_copy(update={"message": Message(role="assistant", content=content)})


async def run(
    script: list[ModelResponse], output_type: Any = Order, **kwargs: Any
) -> tuple[Any, list[Event], FakeModel]:
    model = FakeModel(script)
    store = InMemoryEventStore()
    agent = Agent(model, output_type=output_type, store=store, **kwargs)
    result = await agent.run("Order 2 more W1 than we have")
    return result, await store.read(result.run_id), model


def last_result_text(model: FakeModel, request: int) -> str:
    [block] = model.requests[request].messages[-1].content
    assert isinstance(block, ToolResultBlock)
    first = block.content[0]
    assert isinstance(first, TextBlock)
    return first.text


async def test_valid_answer_comes_back_typed() -> None:
    model = FakeModel([FakeModel.call("get_stock", {"sku": "W1"}), answer(sku="W1", quantity=9)])
    store = InMemoryEventStore()
    agent = Agent(model, output_type=Order, tools=[get_stock], store=store)
    result = await agent.run("Order 2 more W1 than we have")
    order: Order = result.output  # typed: pyright checks this line
    assert order == Order(sku="W1", quantity=9)
    events = await store.read(result.run_id)
    started, completed = events[0], events[-1]
    assert isinstance(started, RunStarted)
    assert [t.name for t in started.tools] == ["get_stock", FINAL_RESULT]
    assert isinstance(completed, RunCompleted)
    assert completed.structured == {"sku": "W1", "quantity": 9}
    [accepted] = [e for e in events if isinstance(e, ToolCallCompleted)][-1:]
    assert accepted.result.content == [TextBlock(text="Final answer accepted.")]


async def test_without_output_type_the_answer_is_text() -> None:
    agent = Agent(FakeModel([FakeModel.reply("hi")]), store=InMemoryEventStore())
    result = await agent.run("hello")
    text: str = result.output
    assert text == "hi"


async def test_invalid_answer_is_sent_back_and_retried() -> None:
    result, events, model = await run([answer(sku="W1", quantity=-1), answer(sku="W1", quantity=9)])
    assert result.output == Order(sku="W1", quantity=9)
    assert result.steps == 2
    [rejected] = [e for e in events if isinstance(e, ToolCallRejected)]
    assert rejected.reason == "invalid_arguments"
    assert "quantity: Input should be greater than 0" in last_result_text(model, 1)


async def test_text_answer_is_pushed_back() -> None:
    result, events, model = await run(
        [FakeModel.reply("Order 9 of W1."), answer(sku="W1", quantity=9)]
    )
    assert result.output.quantity == 9
    [added] = [e for e in events if isinstance(e, MessageAdded)]
    assert added.origin == "runtime"
    assert "calling the final_result tool" in added.message.text
    assert model.requests[1].messages[-1] == added.message  # the model saw the reminder


async def test_final_answer_wins_and_other_calls_never_run() -> None:
    ORDERED.clear()
    reply = together(FakeModel.call("create_po", {"sku": "W1"}), answer(sku="W1", quantity=9))
    _, events, _ = await run([reply], tools=[create_po])
    assert ORDERED == []  # the side effect did not happen
    [rejected] = [e for e in events if isinstance(e, ToolCallRejected)]
    assert rejected.reason == "run_ended"
    assert "tool.call.started" not in [e.type for e in events]


async def test_invalid_answer_with_other_calls_runs_the_others() -> None:
    reply = together(FakeModel.call("get_stock", {"sku": "W1"}), answer(sku="W1"))
    result, events, _ = await run([reply, answer(sku="W1", quantity=9)], tools=[get_stock])
    assert result.output.quantity == 9
    types = [e.type for e in events]
    assert "tool.call.completed" in types
    assert any(isinstance(e, ToolCallRejected) and e.reason == "invalid_arguments" for e in events)


async def test_non_object_output_types_are_wrapped() -> None:
    result, events, _ = await run([answer(result=["W1", "W2"])], output_type=list[str])
    names: list[str] = result.output
    assert names == ["W1", "W2"]
    completed = events[-1]
    assert isinstance(completed, RunCompleted)
    assert completed.structured == ["W1", "W2"]


async def test_unparseable_answer_is_rejected() -> None:
    broken = FakeModel.call(FINAL_RESULT)
    [block] = broken.message.content
    broken = broken.model_copy(
        update={
            "message": Message(
                role="assistant",
                content=[
                    block.model_copy(
                        update={"raw_arguments": "{bad", "parse_error": "Expecting value"}
                    )
                ],
            )
        }
    )
    result, _, model = await run([broken, answer(sku="W1", quantity=1)])
    assert result.output.quantity == 1
    assert "not valid JSON" in last_result_text(model, 1)


async def test_a_model_that_never_answers_correctly_hits_max_steps() -> None:
    from agentreins import Budget

    with pytest.raises(RunError, match="max_steps"):
        await run([answer(sku="W1", quantity=0)] * 5, budget=Budget(max_steps=3))


async def test_final_result_is_a_reserved_tool_name() -> None:
    @tool(effect="read_only", name=FINAL_RESULT)
    def sneaky() -> str:
        """Pretends to be the answer."""
        return "x"

    agent = Agent(FakeModel([]), tools=[sneaky], store=InMemoryEventStore())
    with pytest.raises(ValueError, match="reserved"):
        await agent.run("hi")
