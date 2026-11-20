"""Default policy (ADR-0004 D4) and environment credentials (ADR-0008)."""

import pickle

import pytest

from agentreins.adapters.credentials.env import EnvCredentialProvider
from agentreins.adapters.policies.default import DefaultPolicy
from agentreins.types.errors import CredentialsUnavailable
from agentreins.types.identity import Principal
from agentreins.types.policy import Allow, PolicyRequest, RequireApproval
from agentreins.types.tools import Effect, ToolSpec

ME = Principal(id="u1")


def request(effect: Effect, name: str = "t") -> PolicyRequest:
    spec = ToolSpec(name=name, description="d", input_schema={}, effect=effect)
    return PolicyRequest(principal=ME, tool=spec, arguments={}, run_id="r1")


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (Effect.READ_ONLY, Allow),
        (Effect.IDEMPOTENT, Allow),
        (Effect.SIDE_EFFECTING, RequireApproval),
    ],
)
async def test_default_policy_by_effect(effect: Effect, expected: type) -> None:
    assert isinstance(await DefaultPolicy().decide(request(effect)), expected)


async def test_allow_list_skips_approval() -> None:
    policy = DefaultPolicy(allow=["create_po"])
    assert isinstance(await policy.decide(request(Effect.SIDE_EFFECTING, "create_po")), Allow)
    assert isinstance(
        await policy.decide(request(Effect.SIDE_EFFECTING, "delete_po")), RequireApproval
    )


async def test_env_credentials() -> None:
    provider = EnvCredentialProvider(environ={"AGENTREINS_CRED_ERP_EU": "s3cret"})
    creds = await provider.get(ME, "erp-eu")
    assert creds.reveal() == "s3cret"
    assert "s3cret" not in repr(creds)
    with pytest.raises(TypeError):
        pickle.dumps(creds)


async def test_missing_env_credential_names_the_variable_not_a_secret() -> None:
    with pytest.raises(CredentialsUnavailable, match="AGENTREINS_CRED_CRM is not set"):
        await EnvCredentialProvider(environ={}).get(ME, "crm")


async def test_reads_real_environment_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_ERP", "live-value")
    creds = await EnvCredentialProvider(prefix="MY_").get(ME, "erp")
    assert creds.reveal() == "live-value"
