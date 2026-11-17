"""Policy port (ADR-0004)."""

from typing import Protocol, runtime_checkable

from agentreins.types.identity import Principal
from agentreins.types.policy import PolicyDecision, PolicyRequest
from agentreins.types.tools import ToolSpec


class Policy(Protocol):
    """Decides every tool call. Called after argument validation, for every tool.

    Never modifies arguments. If it raises or times out, the harness treats the answer
    as Deny("policy unavailable") by default (D3).
    """

    async def decide(self, request: PolicyRequest) -> PolicyDecision: ...


@runtime_checkable
class ToolVisibility(Protocol):
    """Optional: hide tools a principal can never use. A convenience, not a security
    boundary: decide() is still called for every call (D1)."""

    async def visible_tools(
        self, principal: Principal, tools: list[ToolSpec]
    ) -> list[ToolSpec]: ...
