"""Default policy: reads allowed, side-effecting tools require approval (ADR-0004 D4).

Implements a port; may import only agentreins.types and agentreins.ports.
"""

from collections.abc import Iterable

from agentreins.types.policy import Allow, PolicyDecision, PolicyRequest, RequireApproval
from agentreins.types.tools import Effect


class DefaultPolicy:
    """``read_only`` and ``idempotent`` tools: Allow. ``side_effecting``: RequireApproval,
    unless the tool is named in ``allow``."""

    def __init__(self, allow: Iterable[str] = ()) -> None:
        self._allow = frozenset(allow)

    async def decide(self, request: PolicyRequest) -> PolicyDecision:
        name = request.tool.name
        if request.tool.effect is not Effect.SIDE_EFFECTING or name in self._allow:
            return Allow()
        return RequireApproval(
            reason=(
                f"{name} has side effects and needs approval. To run it without approval, "
                f"use DefaultPolicy(allow=[{name!r}])."
            )
        )
