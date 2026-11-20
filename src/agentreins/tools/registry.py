"""Tool registry: which tools exist for an agent, collected from its ToolSources."""

from collections.abc import Sequence
from dataclasses import dataclass

from agentreins.ports.tool_source import ToolSource
from agentreins.types.tools import ToolSpec


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    source: ToolSource


class ToolRegistry:
    """Maps each tool name to its spec and the source that runs it.

    Built once per agent with :meth:`from_sources`. Two tools with the same name are an
    error, even from different sources: the model only sees names, so a clash would
    make it ambiguous which tool runs.
    """

    def __init__(
        self, tools: Sequence[RegisteredTool] = (), sources: Sequence[ToolSource] = ()
    ) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for tool in tools:
            if tool.spec.name in self._tools:
                raise ValueError(
                    f"two tools are named {tool.spec.name!r}; tool names must be unique"
                )
            self._tools[tool.spec.name] = tool
        self._sources: list[ToolSource] = []
        for source in [*sources, *(t.source for t in tools)]:
            if not any(source is known for known in self._sources):
                self._sources.append(source)

    @classmethod
    async def from_sources(cls, sources: Sequence[ToolSource]) -> "ToolRegistry":
        tools = [RegisteredTool(spec, s) for s in sources for spec in await s.list_tools()]
        return cls(tools, sources)

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    @property
    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    async def close(self) -> None:
        """Close every source (e.g. MCP server connections)."""
        for source in self._sources:
            await source.close()
