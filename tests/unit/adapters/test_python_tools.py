"""@tool decorator and PythonToolSource."""

import asyncio
from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from agentreins import tool
from agentreins.adapters.tool_sources.python import PythonToolSource
from agentreins.types.errors import InvalidToolArguments
from agentreins.types.identity import Principal
from agentreins.types.tools import Effect, ToolCall, ToolContext, ToolResult


class Item(BaseModel):
    sku: str
    qty: int


@tool(effect="read_only")
def get_stock(sku: str, warehouse: str = "main") -> int:
    """Stock on hand for a product."""
    return {"W1": 7}.get(sku, 0)


@tool
async def create_po(
    items: list[Item], note: Annotated[str, Field(max_length=20)] = ""
) -> dict[str, object]:
    """Create a purchase order."""
    return {"po": "PO-1", "lines": len(items), "note": note}


@tool(effect=Effect.IDEMPOTENT, requires=["erp"], name="whoami", timeout_seconds=5)
def who(ctx: ToolContext) -> str:
    """Report the caller."""
    return f"{ctx.principal.id} via {ctx.idempotency_key}"


def context() -> ToolContext:
    return ToolContext(principal=Principal(id="u1"), run_id="r1", idempotency_key="r1:c1")


def test_spec_from_function() -> None:
    spec = get_stock.spec
    assert spec.name == "get_stock"
    assert spec.description == "Stock on hand for a product."
    assert spec.effect is Effect.READ_ONLY
    assert spec.timeout_seconds == 300.0
    props = spec.input_schema["properties"]
    assert isinstance(props, dict)
    assert set(props) == {"sku", "warehouse"}
    assert spec.input_schema["required"] == ["sku"]
    assert spec.input_schema["additionalProperties"] is False


def test_default_effect_is_side_effecting() -> None:
    assert create_po.spec.effect is Effect.SIDE_EFFECTING


def test_context_parameter_is_hidden_from_the_model() -> None:
    assert who.spec.name == "whoami"
    assert who.spec.requires == ["erp"]
    assert who.spec.timeout_seconds == 5
    assert who.spec.input_schema.get("properties", {}) == {}


def test_decorated_function_is_still_callable() -> None:
    assert get_stock("W1") == 7


def test_requires_a_docstring() -> None:
    def undocumented() -> None:
        pass

    with pytest.raises(ValueError, match="docstring"):
        tool(undocumented)


def test_requires_type_hints_and_no_varargs() -> None:
    def untyped(x):  # type: ignore[no-untyped-def]
        """Doc."""

    def varargs(*names: str) -> None:
        """Doc."""

    with pytest.raises(ValueError, match="type hint"):
        tool(untyped)  # pyright: ignore[reportUnknownArgumentType]
    with pytest.raises(ValueError, match=r"\*args"):
        tool(varargs)


async def test_validate_converts_and_cleans() -> None:
    source = PythonToolSource([create_po])
    cleaned = await source.validate("create_po", {"items": [{"sku": "W1", "qty": "2"}]})
    assert cleaned == {"items": [{"sku": "W1", "qty": 2}], "note": ""}


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"items": [{"sku": "W1", "qty": "lots"}]}, "items.0.qty"),
        ({"items": [], "note": "x" * 30}, "note"),
        ({}, "items: Field required"),
        ({"items": [], "extra": 1}, "extra"),
    ],
)
async def test_validate_rejects_with_a_readable_message(
    arguments: dict[str, object], message: str
) -> None:
    source = PythonToolSource([create_po])
    with pytest.raises(InvalidToolArguments, match=message):
        await source.validate("create_po", arguments)  # pyright: ignore[reportArgumentType]


async def test_call_sync_async_and_context() -> None:
    source = PythonToolSource([get_stock, create_po, who])
    ctx = context()
    assert await source.call(ToolCall(id="c1", name="get_stock", arguments={"sku": "W1"}), ctx) == (
        ToolResult.text("7")
    )
    po = await source.call(
        ToolCall(id="c2", name="create_po", arguments={"items": [{"sku": "W1", "qty": 1}]}), ctx
    )
    assert po == ToolResult.text('{"po":"PO-1","lines":1,"note":""}')
    me = await source.call(ToolCall(id="c3", name="whoami"), ctx)
    assert me == ToolResult.text("u1 via r1:c1")


async def test_return_value_conversion() -> None:
    @tool(effect="read_only")
    def nothing() -> None:
        """Returns nothing."""

    @tool(effect="read_only")
    def explicit() -> ToolResult:
        """Returns a ToolResult."""
        return ToolResult.error("nope")

    source = PythonToolSource([nothing, explicit])
    assert await source.call(ToolCall(id="a", name="nothing"), context()) == ToolResult.text(
        "(no output)"
    )
    assert (await source.call(ToolCall(id="b", name="explicit"), context())).is_error


async def test_sync_tools_do_not_block_the_event_loop() -> None:
    import time

    @tool(effect="read_only")
    def slow() -> str:
        """Sleeps."""
        time.sleep(0.2)
        return "done"

    source = PythonToolSource([slow])
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.02)
            ticks += 1

    await asyncio.gather(source.call(ToolCall(id="a", name="slow"), context()), ticker())
    assert ticks == 5


def test_duplicate_names_rejected() -> None:
    with pytest.raises(ValueError, match="two tools"):
        PythonToolSource([get_stock, get_stock])
