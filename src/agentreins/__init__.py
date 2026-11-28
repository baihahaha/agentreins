"""agentreins: a small, durable, provider-neutral agent runtime.

The public API is whatever is re-exported from this module. Anything imported
from a submodule directly may change without notice.
"""

from agentreins.adapters.tool_sources.python import tool
from agentreins.agent import Agent
from agentreins.runtime.loop import RunResult
from agentreins.types.budget import Budget, Usage
from agentreins.types.content import Message
from agentreins.types.errors import RunError
from agentreins.types.identity import Principal
from agentreins.types.policy import Allow, Deny, RequireApproval
from agentreins.types.tools import ToolContext, ToolResult

__version__ = "0.1.0.dev0"

__all__ = [
    "Agent",
    "Allow",
    "Budget",
    "Deny",
    "Message",
    "Principal",
    "RequireApproval",
    "RunError",
    "RunResult",
    "ToolContext",
    "ToolResult",
    "Usage",
    "__version__",
    "tool",
]
