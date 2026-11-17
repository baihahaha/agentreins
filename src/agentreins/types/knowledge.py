"""Knowledge types: retrieved documents and memories (ADR-0010, ADR-0011).

TODO(maintainer): define fields.
"""

from pydantic import BaseModel


class Document(BaseModel):
    """id, content, score, source, metadata. Placeholder."""


class MemoryItem(BaseModel):
    """id, content, metadata, created_at. Placeholder."""
