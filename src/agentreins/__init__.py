"""agentreins: a small, durable, provider-neutral agent runtime.

The public API is whatever is re-exported from this module. Anything imported
from a submodule directly may change without notice.
"""

from agentreins.adapters.tool_sources.python import tool

__version__ = "0.1.0.dev0"

__all__ = ["__version__", "tool"]
