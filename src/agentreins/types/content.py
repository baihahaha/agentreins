"""Content model: messages made of content blocks (ADR-0002 D3, ADR-0001).

TODO(M1): define Message and the blocks: TextBlock, ToolUseBlock,
ToolResultBlock, ReasoningBlock, ImageBlock.
"""

from pydantic import BaseModel


class Message(BaseModel):
    """A conversation message: role + list of content blocks. Placeholder."""
