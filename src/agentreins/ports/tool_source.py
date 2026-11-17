"""ToolSource port (ADR-0003)."""

from typing import Protocol

from agentreins.types.tools import ToolCall, ToolContext, ToolResult, ToolSpec


class ToolSource(Protocol):
    """Supplies tools: Python functions, MCP servers, later agents.

    Calls reach a source only through the tool harness. The "tools changed" signal
    (needed for MCP) is decided when the MCP source is built.
    """

    async def list_tools(self) -> list[ToolSpec]: ...

    async def call(self, call: ToolCall, context: ToolContext) -> ToolResult: ...

    async def close(self) -> None: ...
