"""Budget and usage types (REQUIREMENTS G5, guarantee #3)."""

from pydantic import Field

from agentreins.types._base import FrozenModel


class Usage(FrozenModel):
    """Tokens consumed, normalized across providers (ADR-0002 D4)."""

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )


class Budget(FrozenModel):
    """Limits for a run or a session. ``None`` means no limit for that dimension.

    ``max_steps`` always has a value, so every run ends even if nothing else is set.
    """

    max_steps: int = Field(default=25, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0)
    max_wall_seconds: float | None = Field(default=None, gt=0)
    max_runs: int | None = Field(default=None, gt=0)
