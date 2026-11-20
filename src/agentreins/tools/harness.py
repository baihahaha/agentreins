"""Tool harness: the only path to run a tool (ADR-0003, ADR-0004, ADR-0008).

Three phases, so the runtime can record events between them and the harness never
touches the event log::

    check(block)      -> Rejected | NeedsApproval | Ready      validate, then policy
    (approval)                                                  runtime, M7
    prepare(ready)    -> Rejected | Prepared                    fetch credentials
    (runtime writes tool.call.started: the intent record)
    execute(prepared) -> Completed | Failed                     run, with timeout

Nothing runs a tool except ``execute``, and ``execute`` only accepts a ``Prepared``,
which only ``prepare`` makes from a ``Ready``, which only ``check`` makes after policy
said Allow. So no tool can skip validation or policy.
"""

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import JsonValue

from agentreins.ports.credentials import CredentialProvider
from agentreins.ports.policy import Policy, ToolVisibility
from agentreins.ports.tool_source import ArgumentValidator, ToolSource
from agentreins.tools.registry import ToolRegistry
from agentreins.tools.schema_check import check_arguments
from agentreins.types.budget import Usage
from agentreins.types.content import TextBlock, ToolUseBlock
from agentreins.types.errors import InvalidToolArguments, PolicyUnavailable
from agentreins.types.events import ToolRejectionReason
from agentreins.types.identity import Credentials, Principal
from agentreins.types.policy import Allow, Deny, PolicyDecision, PolicyRequest
from agentreins.types.tools import ToolCall, ToolContext, ToolResult, ToolSpec

# --- outcomes ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rejected:
    """The tool will not run. ``message`` is what the model is told."""

    reason: ToolRejectionReason
    message: str


@dataclass(frozen=True, slots=True)
class NeedsApproval:
    """Policy wants a human to approve this call first (handled by the runtime, M7)."""

    call: ToolCall
    spec: ToolSpec
    reason: str


@dataclass(frozen=True, slots=True)
class Ready:
    """Validated and allowed. ``call.arguments`` are the cleaned arguments."""

    call: ToolCall
    spec: ToolSpec
    _token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class Prepared:
    """Credentials fetched; hand straight to :meth:`ToolHarness.execute`."""

    call: ToolCall
    spec: ToolSpec
    context: ToolContext
    _token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class Completed:
    """The tool returned a result (which may itself be a handled error)."""

    result: ToolResult
    duration_ms: float


@dataclass(frozen=True, slots=True)
class Failed:
    """The tool raised or timed out. ``error`` is safe to show and store."""

    error: str
    timed_out: bool
    duration_ms: float


# --- harness -------------------------------------------------------------------------


class ToolHarness:
    """Validates, authorizes and runs tool calls for one agent.

    - ``policy_timeout``: seconds ``decide()`` may take before it counts as failed.
    - ``on_policy_error``: ``"deny"`` (default) tells the model the call was denied and
      the run continues; ``"fail_run"`` raises ``PolicyUnavailable``. Never fails open.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        policy: Policy,
        credentials: CredentialProvider,
        *,
        policy_timeout: float = 10.0,
        on_policy_error: Literal["deny", "fail_run"] = "deny",
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._credentials = credentials
        self._policy_timeout = policy_timeout
        self._on_policy_error = on_policy_error
        self._token = object()  # only this harness can make Ready / Prepared

    async def visible_tools(self, principal: Principal) -> list[ToolSpec]:
        """Tools to show the model. A convenience: ``check`` still calls policy.

        If the policy's filter fails, all tools are shown; that is safe because every
        call is still decided by ``decide()``.
        """
        specs = self._registry.specs
        if isinstance(self._policy, ToolVisibility):
            try:
                return await self._policy.visible_tools(principal, specs)
            except Exception:
                return specs
        return specs

    async def check(
        self,
        block: ToolUseBlock,
        *,
        principal: Principal,
        run_id: str,
        session_id: str | None = None,
        usage: Usage | None = None,
    ) -> Rejected | NeedsApproval | Ready:
        """Phase 1: validate the arguments, then ask policy. Runs nothing."""
        tool = self._registry.get(block.name)
        if tool is None:
            names = ", ".join(sorted(s.name for s in self._registry.specs)) or "none"
            return Rejected("unknown_tool", f"Unknown tool {block.name!r}. Available: {names}.")
        if block.parse_error is not None:
            return Rejected(
                "invalid_arguments", f"Arguments are not valid JSON: {block.parse_error}"
            )

        arguments = await self._validate(tool.source, tool.spec, block.arguments)
        if isinstance(arguments, Rejected):
            return arguments
        call = ToolCall(id=block.id, name=block.name, arguments=arguments)

        decision = await self._decide(
            PolicyRequest(
                principal=principal,
                tool=tool.spec,
                arguments=arguments,
                run_id=run_id,
                session_id=session_id,
                usage=usage or Usage(),
            )
        )
        if isinstance(decision, Allow):
            return Ready(call, tool.spec, self._token)
        if isinstance(decision, Deny):
            return Rejected("policy_denied", decision.reason)
        return NeedsApproval(call, tool.spec, decision.reason)

    async def prepare(
        self,
        ready: Ready,
        *,
        principal: Principal,
        run_id: str,
        cancellation: asyncio.Event | None = None,
    ) -> Rejected | Prepared:
        """Phase 2: fetch credentials for each need in ``spec.requires``. Runs nothing.

        Call it right before running: credentials are fetched per call and must not be
        held across an approval wait (ADR-0008 D3).
        """
        self._own(ready._token)  # pyright: ignore[reportPrivateUsage]
        credentials: dict[str, Credentials] = {}
        for need in ready.spec.requires:
            try:
                credentials[need] = await self._credentials.get(principal, need)
            except Exception:
                # The provider's message is not shown: it might contain a secret.
                return Rejected(
                    "credentials_unavailable",
                    f"Credentials {need!r} for {ready.spec.name} are unavailable.",
                )
        context = ToolContext(
            principal=principal,
            run_id=run_id,
            idempotency_key=f"{run_id}:{ready.call.id}",
            credentials=credentials,
            cancellation=cancellation or asyncio.Event(),
        )
        return Prepared(ready.call, ready.spec, context, self._token)

    async def execute(self, prepared: Prepared) -> Completed | Failed:
        """Phase 3: run the tool with its timeout. Never raises for tool errors."""
        self._own(prepared._token)  # pyright: ignore[reportPrivateUsage]
        tool = self._registry.get(prepared.call.name)
        assert tool is not None  # check() found it; the registry does not change
        secrets = [c.reveal() for c in prepared.context.credentials.values()]
        started = time.perf_counter()
        deadline = asyncio.timeout(prepared.spec.timeout_seconds)
        try:
            async with deadline:
                result = await tool.source.call(prepared.call, prepared.context)
        except TimeoutError as exc:
            if not deadline.expired():  # the tool raised TimeoutError itself
                error = _scrub_text(f"TimeoutError: {exc}", secrets)
                return Failed(error, timed_out=False, duration_ms=_ms(started))
            return Failed(
                f"timed out after {prepared.spec.timeout_seconds:g} s",
                timed_out=True,
                duration_ms=_ms(started),
            )
        except Exception as exc:
            error = _scrub_text(f"{type(exc).__name__}: {exc}", secrets)
            return Failed(error, timed_out=False, duration_ms=_ms(started))
        return Completed(_scrub_result(result, secrets), _ms(started))

    # --- internals -------------------------------------------------------------------

    async def _validate(
        self, source: ToolSource, spec: ToolSpec, arguments: dict[str, JsonValue]
    ) -> dict[str, JsonValue] | Rejected:
        if isinstance(source, ArgumentValidator):
            try:
                return await source.validate(spec.name, arguments)
            except InvalidToolArguments as exc:
                return Rejected("invalid_arguments", f"Invalid arguments: {exc}")
        problem = check_arguments(spec.input_schema, arguments)
        if problem is not None:
            return Rejected("invalid_arguments", f"Invalid arguments: {problem}")
        return arguments

    async def _decide(self, request: PolicyRequest) -> PolicyDecision:
        try:
            async with asyncio.timeout(self._policy_timeout):
                return await self._policy.decide(request)
        except Exception as exc:
            if self._on_policy_error == "fail_run":
                raise PolicyUnavailable(f"policy failed for {request.tool.name}") from exc
            return Deny(reason="policy unavailable")

    def _own(self, token: object) -> None:
        if token is not self._token:
            raise ValueError("this call was not checked by this harness")


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _scrub_text(text: str, secrets: Sequence[str]) -> str:
    """Replace any credential value a tool echoed back, so it cannot reach the log."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _scrub_result(result: ToolResult, secrets: Sequence[str]) -> ToolResult:
    if not any(secrets):
        return result
    content = [
        TextBlock(text=_scrub_text(b.text, secrets)) if isinstance(b, TextBlock) else b
        for b in result.content
    ]
    return result.model_copy(update={"content": content})
