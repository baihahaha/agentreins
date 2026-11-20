"""Tool harness: every path through check -> prepare -> execute."""

import asyncio
from dataclasses import replace

import pytest
from pydantic import JsonValue

from agentreins import tool
from agentreins.adapters.credentials.env import EnvCredentialProvider
from agentreins.adapters.policies.default import DefaultPolicy
from agentreins.adapters.tool_sources.python import PythonToolSource
from agentreins.tools.harness import (
    Completed,
    Failed,
    NeedsApproval,
    Prepared,
    Ready,
    Rejected,
    ToolHarness,
)
from agentreins.tools.registry import ToolRegistry
from agentreins.types.content import ToolUseBlock
from agentreins.types.errors import PolicyUnavailable
from agentreins.types.identity import Principal
from agentreins.types.policy import Allow, Deny, PolicyDecision, PolicyRequest
from agentreins.types.tools import Effect, ToolCall, ToolContext, ToolResult, ToolSpec

ME = Principal(id="u1", roles=["buyer"])
SECRET = "sk-very-secret"


@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Stock on hand."""
    return 7


@tool
def create_po(qty: int) -> str:
    """Create a purchase order."""
    return f"PO for {qty}"


@tool(effect="read_only", requires=["erp"])
def erp_lookup(ctx: ToolContext) -> str:
    """Echoes its credential (a badly written tool)."""
    return f"used token {ctx.credentials['erp'].reveal()}"


@tool(effect="read_only", requires=["erp"])
def erp_crash(ctx: ToolContext) -> str:
    """Leaks its credential in an exception."""
    raise RuntimeError(f"auth failed for {ctx.credentials['erp'].reveal()}")


@tool(effect="read_only", timeout_seconds=0.05)
async def slow() -> str:
    """Never finishes in time."""
    await asyncio.sleep(5)
    return "late"


@tool(effect="read_only")
async def raises_timeout() -> str:
    """Raises TimeoutError itself."""
    raise TimeoutError("upstream gave up")


class RecordingPolicy:
    def __init__(self, decision: PolicyDecision) -> None:
        self.decision = decision
        self.requests: list[PolicyRequest] = []

    async def decide(self, request: PolicyRequest) -> PolicyDecision:
        self.requests.append(request)
        return self.decision


class CrashingPolicy:
    async def decide(self, request: PolicyRequest) -> PolicyDecision:
        raise RuntimeError("OPA is down")


class HangingPolicy:
    async def decide(self, request: PolicyRequest) -> PolicyDecision:
        await asyncio.sleep(5)
        return Allow()


async def harness(policy: object = None, **kwargs: object) -> ToolHarness:
    source = PythonToolSource([get_stock, create_po, erp_lookup, erp_crash, slow, raises_timeout])
    registry = await ToolRegistry.from_sources([source])
    creds = EnvCredentialProvider(environ={"AGENTREINS_CRED_ERP": SECRET})
    return ToolHarness(registry, policy or DefaultPolicy(), creds, **kwargs)  # pyright: ignore[reportArgumentType]


def use(name: str, arguments: dict[str, JsonValue] | None = None, **extra: object) -> ToolUseBlock:
    return ToolUseBlock(id="c1", name=name, arguments=arguments or {}, **extra)  # pyright: ignore[reportArgumentType]


async def run_through(h: ToolHarness, block: ToolUseBlock) -> Rejected | Completed | Failed:
    checked = await h.check(block, principal=ME, run_id="r1")
    assert isinstance(checked, Ready | Rejected), checked
    if isinstance(checked, Rejected):
        return checked
    prepared = await h.prepare(checked, principal=ME, run_id="r1")
    if isinstance(prepared, Rejected):
        return prepared
    return await h.execute(prepared)


# --- check: validation ---------------------------------------------------------------


async def test_unknown_tool() -> None:
    out = await (await harness()).check(use("nope"), principal=ME, run_id="r1")
    assert isinstance(out, Rejected)
    assert out.reason == "unknown_tool"
    assert "get_stock" in out.message


async def test_unparseable_arguments() -> None:
    block = use("get_stock", raw_arguments="{bad", parse_error="Expecting value")
    out = await (await harness()).check(block, principal=ME, run_id="r1")
    assert out == Rejected("invalid_arguments", "Arguments are not valid JSON: Expecting value")


async def test_invalid_arguments_never_reach_policy() -> None:
    policy = RecordingPolicy(Allow())
    out = await (await harness(policy)).check(
        use("create_po", {"qty": "many"}), principal=ME, run_id="r1"
    )
    assert isinstance(out, Rejected)
    assert out.reason == "invalid_arguments"
    assert "qty" in out.message
    assert policy.requests == []


async def test_policy_sees_cleaned_arguments_and_context() -> None:
    policy = RecordingPolicy(Allow())
    out = await (await harness(policy)).check(
        use("create_po", {"qty": "3"}), principal=ME, run_id="r1", session_id="s1"
    )
    assert isinstance(out, Ready)
    assert out.call.arguments == {"qty": 3}
    [request] = policy.requests
    assert request.arguments == {"qty": 3}
    assert (request.principal, request.run_id, request.session_id) == (ME, "r1", "s1")
    assert request.tool.effect is Effect.SIDE_EFFECTING


# --- check: policy -------------------------------------------------------------------


async def test_read_only_tools_also_go_through_policy() -> None:
    policy = RecordingPolicy(Deny(reason="no stock data for you"))
    out = await (await harness(policy)).check(
        use("get_stock", {"sku": "W1"}), principal=ME, run_id="r1"
    )
    assert out == Rejected("policy_denied", "no stock data for you")


async def test_default_policy_asks_approval_for_side_effects() -> None:
    out = await (await harness()).check(use("create_po", {"qty": 1}), principal=ME, run_id="r1")
    assert isinstance(out, NeedsApproval)
    assert "DefaultPolicy(allow=['create_po'])" in out.reason


@pytest.mark.parametrize("policy", [CrashingPolicy(), HangingPolicy()], ids=["crash", "hang"])
async def test_policy_failure_denies_by_default(policy: object) -> None:
    h = await harness(policy, policy_timeout=0.05)
    out = await h.check(use("get_stock", {"sku": "W1"}), principal=ME, run_id="r1")
    assert out == Rejected("policy_denied", "policy unavailable")


async def test_policy_failure_can_fail_the_run() -> None:
    h = await harness(CrashingPolicy(), on_policy_error="fail_run")
    with pytest.raises(PolicyUnavailable):
        await h.check(use("get_stock", {"sku": "W1"}), principal=ME, run_id="r1")


# --- prepare: credentials ------------------------------------------------------------


async def test_prepare_builds_context_with_stable_idempotency_key() -> None:
    h = await harness()
    ready = await h.check(use("erp_lookup"), principal=ME, run_id="r1")
    assert isinstance(ready, Ready)
    prepared = await h.prepare(ready, principal=ME, run_id="r1")
    assert isinstance(prepared, Prepared)
    assert prepared.context.idempotency_key == "r1:c1"
    assert prepared.context.credentials["erp"].reveal() == SECRET
    assert SECRET not in repr(prepared)


async def test_missing_credentials_reject_without_running() -> None:
    source = PythonToolSource([erp_lookup])
    h = ToolHarness(
        await ToolRegistry.from_sources([source]),
        DefaultPolicy(),
        EnvCredentialProvider(environ={}),
    )
    ready = await h.check(use("erp_lookup"), principal=ME, run_id="r1")
    assert isinstance(ready, Ready)
    out = await h.prepare(ready, principal=ME, run_id="r1")
    assert out == Rejected(
        "credentials_unavailable", "Credentials 'erp' for erp_lookup are unavailable."
    )


# --- execute -------------------------------------------------------------------------


async def test_success() -> None:
    out = await run_through(await harness(), use("get_stock", {"sku": "W1"}))
    assert isinstance(out, Completed)
    assert out.result == ToolResult.text("7")
    assert out.duration_ms >= 0


async def test_tool_exception_becomes_failed() -> None:
    @tool(effect="read_only")
    def broken() -> str:
        """Always fails."""
        raise ValueError("bad sku")

    h = ToolHarness(
        await ToolRegistry.from_sources([PythonToolSource([broken])]),
        DefaultPolicy(),
        EnvCredentialProvider(environ={}),
    )
    out = await run_through(h, use("broken"))
    assert isinstance(out, Failed)
    assert (out.error, out.timed_out) == ("ValueError: bad sku", False)


async def test_timeout() -> None:
    out = await run_through(await harness(), use("slow"))
    assert isinstance(out, Failed)
    assert (out.error, out.timed_out) == ("timed out after 0.05 s", True)


async def test_tool_raising_timeout_error_is_not_our_timeout() -> None:
    out = await run_through(await harness(), use("raises_timeout"))
    assert isinstance(out, Failed)
    assert (out.error, out.timed_out) == ("TimeoutError: upstream gave up", False)


async def test_credentials_are_scrubbed_from_results_and_errors() -> None:
    h = await harness()
    ok = await run_through(h, use("erp_lookup"))
    assert isinstance(ok, Completed)
    assert ok.result == ToolResult.text("used token ***")
    bad = await run_through(h, use("erp_crash"))
    assert isinstance(bad, Failed)
    assert bad.error == "RuntimeError: auth failed for ***"


# --- no bypass -----------------------------------------------------------------------


async def test_cannot_execute_without_check() -> None:
    h = await harness()
    spec = get_stock.spec
    forged_ready = Ready(
        ToolCall(id="c1", name="get_stock", arguments={"sku": "W1"}), spec, object()
    )
    with pytest.raises(ValueError, match="not checked by this harness"):
        await h.prepare(forged_ready, principal=ME, run_id="r1")
    ctx = ToolContext(principal=ME, run_id="r1", idempotency_key="k")
    forged = Prepared(forged_ready.call, spec, ctx, object())
    with pytest.raises(ValueError, match="not checked by this harness"):
        await h.execute(forged)


async def test_ready_from_another_harness_is_refused() -> None:
    one, two = await harness(), await harness()
    ready = await one.check(use("get_stock", {"sku": "W1"}), principal=ME, run_id="r1")
    assert isinstance(ready, Ready)
    with pytest.raises(ValueError, match="not checked"):
        await two.prepare(ready, principal=ME, run_id="r1")
    with pytest.raises(ValueError, match="not checked"):
        await one.prepare(replace(ready, _token=object()), principal=ME, run_id="r1")


# --- visibility ----------------------------------------------------------------------


class HidesWrites:
    async def decide(self, request: PolicyRequest) -> PolicyDecision:
        return Allow()

    async def visible_tools(self, principal: Principal, tools: list[ToolSpec]) -> list[ToolSpec]:
        return [t for t in tools if t.effect is not Effect.SIDE_EFFECTING]


class BrokenVisibility(HidesWrites):
    async def visible_tools(self, principal: Principal, tools: list[ToolSpec]) -> list[ToolSpec]:
        raise RuntimeError("boom")


async def test_visible_tools() -> None:
    names = {t.name for t in await (await harness(HidesWrites())).visible_tools(ME)}
    assert "create_po" not in names
    assert "get_stock" in names
    everything = await (await harness(BrokenVisibility())).visible_tools(ME)
    assert len(everything) == 6
    assert len(await (await harness()).visible_tools(ME)) == 6


# --- sources without their own validation (e.g. MCP) ---------------------------------


class SchemaOnlySource:
    """Like an MCP server: a JSON Schema, no validate() method."""

    spec = ToolSpec(
        name="remote_search",
        description="Search a remote system.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        effect=Effect.READ_ONLY,
    )

    async def list_tools(self) -> list[ToolSpec]:
        return [self.spec]

    async def call(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return ToolResult.text(f"results for {call.arguments['query']}")

    async def close(self) -> None:
        return None


async def test_source_without_validate_gets_the_basic_check() -> None:
    h = ToolHarness(
        await ToolRegistry.from_sources([SchemaOnlySource()]),
        DefaultPolicy(),
        EnvCredentialProvider(environ={}),
    )
    bad = await h.check(use("remote_search", {"query": 5}), principal=ME, run_id="r1")
    assert bad == Rejected("invalid_arguments", "Invalid arguments: arguments.query must be string")
    good = await run_through(h, use("remote_search", {"query": "widgets"}))
    assert isinstance(good, Completed)
    assert good.result == ToolResult.text("results for widgets")
