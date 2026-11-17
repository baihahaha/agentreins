"""Budget and usage types (REQUIREMENTS G5).

TODO(maintainer): define fields.
"""

from pydantic import BaseModel


class Budget(BaseModel):
    """Limits: steps, tokens, cost, wall time, runs (for sessions). Placeholder."""


class Usage(BaseModel):
    """Tokens in/out/cached, cost. Placeholder."""
