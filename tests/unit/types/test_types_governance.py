"""Tools, policy, identity and credentials (ADR-0003, ADR-0004, ADR-0008)."""

import copy
import json
import pickle

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from agentreins.types.identity import Credentials, Principal
from agentreins.types.policy import Allow, Deny, PolicyDecision, PolicyRequest, RequireApproval
from agentreins.types.tools import Effect, ToolCall, ToolContext, ToolResult, ToolSpec


def _spec(**overrides: object) -> ToolSpec:
    data: dict[str, object] = {
        "name": "create_po",
        "description": "Create a purchase order",
        "input_schema": {"type": "object"},
        "effect": "side_effecting",
    }
    return ToolSpec.model_validate(data | overrides)


def test_tool_spec_round_trips() -> None:
    spec = _spec(requires=["erp"], timeout_seconds=5)
    assert spec.effect is Effect.SIDE_EFFECTING
    assert ToolSpec.model_validate_json(spec.model_dump_json()) == spec


@pytest.mark.parametrize("name", ["", "has space", "x" * 65, "dots.not.allowed"])
def test_tool_names_follow_provider_rules(name: str) -> None:
    with pytest.raises(ValidationError):
        _spec(name=name)


def test_unknown_effect_and_bad_timeout_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _spec(effect="dangerous")
    with pytest.raises(ValidationError):
        _spec(timeout_seconds=0)


def test_tool_call_and_result_round_trip() -> None:
    call = ToolCall(id="c1", name="create_po", arguments={"qty": 5})
    assert ToolCall.model_validate_json(call.model_dump_json()) == call
    assert ToolResult.text("ok").is_error is False
    error = ToolResult.error("qty must be positive")
    assert error.is_error
    assert ToolResult.model_validate_json(error.model_dump_json()) == error


def test_policy_decisions_are_parsed_by_type() -> None:
    adapter: TypeAdapter[PolicyDecision] = TypeAdapter(PolicyDecision)
    for decision in (Allow(), Deny(reason="no"), RequireApproval(reason="over $10k")):
        assert adapter.validate_json(adapter.dump_json(decision)) == decision
    with pytest.raises(ValidationError):
        adapter.validate_python({"type": "maybe"})


def test_deny_and_approval_need_a_reason() -> None:
    with pytest.raises(ValidationError):
        Deny.model_validate({"type": "deny"})
    with pytest.raises(ValidationError):
        RequireApproval.model_validate({"type": "require_approval"})


def test_policy_request_round_trips() -> None:
    request = PolicyRequest(
        principal=Principal(id="u-1", tenant="acme", roles=["buyer"]),
        tool=_spec(),
        arguments={"qty": 5},
        run_id="r1",
    )
    assert PolicyRequest.model_validate_json(request.model_dump_json()) == request


# --- Credentials must never leak (ADR-0008 D2) --------------------------------------

SECRET = "sk-very-secret"


def test_credentials_reveal_only_on_request() -> None:
    creds = Credentials("erp", SECRET)
    assert creds.reveal() == SECRET
    assert SECRET not in repr(creds)
    assert SECRET not in str(creds)
    assert SECRET not in f"{creds}"


def test_credentials_cannot_be_serialized_or_copied() -> None:
    creds = Credentials("erp", SECRET)
    with pytest.raises(TypeError):
        json.dumps(creds)
    with pytest.raises(TypeError):
        pickle.dumps(creds)
    with pytest.raises(TypeError):
        copy.deepcopy(creds)


def test_credentials_cannot_be_put_in_a_pydantic_model() -> None:
    with pytest.raises(Exception, match="Credentials"):

        class Leaky(BaseModel):  # pyright: ignore[reportUnusedClass]
            creds: Credentials


def test_tool_context_holds_credentials_without_exposing_them() -> None:
    context = ToolContext(
        principal=Principal(id="u-1"),
        run_id="r1",
        idempotency_key="r1:c1",
        credentials={"erp": Credentials("erp", SECRET)},
    )
    assert SECRET not in repr(context)
    assert context.cancellation.is_set() is False


def test_tool_spec_default_timeout_is_300_seconds() -> None:
    assert _spec().timeout_seconds == 300.0
