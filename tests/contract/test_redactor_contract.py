"""Redactor contract (ADR-0006 D1): content may change; identity may not.

To check a new redactor, add it to the ``redactor`` fixture.
"""

import pytest

from agentreins.adapters.redactors.passthrough import PassThroughRedactor
from agentreins.ports.redactor import Redactor
from builders import simple_run


@pytest.fixture(params=[PassThroughRedactor()], ids=lambda r: type(r).__name__)
def redactor(request: pytest.FixtureRequest) -> Redactor:
    return request.param


async def test_identity_is_preserved(redactor: Redactor) -> None:
    for event in simple_run("r1"):
        out = await redactor.redact(event)
        assert type(out) is type(event)
        assert (out.event_id, out.run_id, out.seq, out.type) == (
            event.event_id,
            event.run_id,
            event.seq,
            event.type,
        )


async def test_pass_through_changes_nothing() -> None:
    for event in simple_run("r1"):
        assert await PassThroughRedactor().redact(event) == event
