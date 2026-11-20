"""ToolSource port (ADR-0003)."""

from typing import Protocol, runtime_checkable

from pydantic import JsonValue

from agentreins.types.tools import ToolCall, ToolContext, ToolResult, ToolSpec


class ToolSource(Protocol):
    """Supplies tools: Python functions, MCP servers, later agents.

    Calls reach a source only through the tool harness. The "tools changed" signal
    (needed for MCP) is decided when the MCP source is built.
    """

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, call: ToolCall, context: ToolContext) -> ToolResult: ...

    async def close(self) -> None: ...


@runtime_checkable
class ArgumentValidator(Protocol):
    """Optional: a source that can check a tool's arguments fully (ADR-0003 D4).

    Return the cleaned arguments (JSON values; policy and the event log see these), or
    raise ``InvalidToolArguments`` with a message for the model. Sources without this
    method get the harness's built-in basic check against ``input_schema``.
    """

    async def validate(
        self, name: str, arguments: dict[str, JsonValue]
    ) -> dict[str, JsonValue]: ...
