"""Tool registry."""

import pytest

from agentreins import tool
from agentreins.adapters.tool_sources.python import PythonToolSource
from agentreins.tools.registry import ToolRegistry


@tool(effect="read_only")
def ping() -> str:
    """Ping."""
    return "pong"


class CountsClose(PythonToolSource):
    closed = 0

    async def close(self) -> None:
        CountsClose.closed += 1


async def test_collects_tools_from_sources() -> None:
    registry = await ToolRegistry.from_sources([PythonToolSource([ping])])
    assert [s.name for s in registry.specs] == ["ping"]
    found = registry.get("ping")
    assert found is not None
    assert found.spec.name == "ping"
    assert registry.get("nope") is None


async def test_same_name_in_two_sources_is_an_error() -> None:
    with pytest.raises(ValueError, match="unique"):
        await ToolRegistry.from_sources([PythonToolSource([ping]), PythonToolSource([ping])])


async def test_close_closes_every_source_once_even_without_tools() -> None:
    a, empty = CountsClose([ping]), CountsClose([])
    registry = await ToolRegistry.from_sources([a, empty])
    await registry.close()
    assert CountsClose.closed == 2
