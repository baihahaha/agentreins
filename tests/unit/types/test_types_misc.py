"""IDs, budgets, knowledge types and errors."""

import uuid
from datetime import UTC

import pytest
from pydantic import ValidationError

from agentreins.types import errors
from agentreins.types.budget import Budget, Usage
from agentreins.types.ids import _uuid7_fallback, new_id  # pyright: ignore[reportPrivateUsage]
from agentreins.types.knowledge import Document, MemoryItem


def test_new_id_is_a_unique_uuid7() -> None:
    ids = {new_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert all(uuid.UUID(i).version == 7 for i in ids)


def test_fallback_uuid7_has_correct_layout_and_sorts_by_time() -> None:
    earlier = _uuid7_fallback(now_ns=1_700_000_000_000_000_000)
    later = _uuid7_fallback(now_ns=1_700_000_000_001_000_000)  # 1 ms later
    assert earlier.version == 7
    assert earlier.variant == uuid.RFC_4122
    assert int.from_bytes(earlier.bytes[:6], "big") == 1_700_000_000_000
    assert str(earlier) < str(later)


def test_usage_adds_up() -> None:
    total = Usage(input_tokens=10, output_tokens=2) + Usage(input_tokens=5, cache_read_tokens=4)
    assert total == Usage(input_tokens=15, output_tokens=2, cache_read_tokens=4)
    with pytest.raises(ValidationError):
        Usage(input_tokens=-1)


def test_budget_always_bounds_steps() -> None:
    assert Budget().max_steps == 25
    with pytest.raises(ValidationError):
        Budget(max_steps=0)
    with pytest.raises(ValidationError):
        Budget(max_cost_usd=-1)


def test_knowledge_types_round_trip() -> None:
    doc = Document(
        id="d1", content="Supplier B ships in 3 days", score=0.9, source="erp://suppliers/B"
    )
    assert Document.model_validate_json(doc.model_dump_json()) == doc
    memory = MemoryItem(content="Prefers supplier B")
    assert uuid.UUID(memory.id).version == 7
    assert memory.created_at.tzinfo is UTC
    assert MemoryItem.model_validate_json(memory.model_dump_json()) == memory


@pytest.mark.parametrize(
    ("cls", "retryable"),
    [
        (errors.RateLimited, True),
        (errors.ProviderUnavailable, True),
        (errors.ModelTimeout, True),
        (errors.ContextTooLong, False),
        (errors.AuthFailed, False),
        (errors.BadRequest, False),
    ],
)
def test_model_errors_declare_retryability(cls: type[errors.ModelError], retryable: bool) -> None:
    error = cls("boom", provider="openai", status_code=500)
    assert isinstance(error, errors.AgentReinsError)
    assert error.retryable is retryable
    assert error.provider == "openai"


def test_rate_limited_carries_retry_after() -> None:
    assert errors.RateLimited("slow down", retry_after=2.5).retry_after == 2.5
