"""The agent loop: model -> tools -> model ..., with budgets and retries (ADR-0002 D5).

One :class:`Runtime` holds an agent's wiring (model, harness, ledger, context, hooks,
limits). Each :meth:`Runtime.run` is one run: it writes every step to the event log
*before* taking the next one, so the log alone explains what happened.
"""

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import JsonValue

from agentreins.context.manager import ContextManager
from agentreins.ledger.ledger import Ledger
from agentreins.ledger.projections import project_messages
from agentreins.ports.model import ModelAdapter
from agentreins.runtime.hooks import HookDispatcher
from agentreins.tools.harness import (
    Completed,
    NeedsApproval,
    Prepared,
    Ready,
    Rejected,
    ToolHarness,
)
from agentreins.types.budget import Budget, Usage
from agentreins.types.content import Message, ToolUseBlock
from agentreins.types.errors import (
    ContextTooLong,
    ModelError,
    PolicyUnavailable,
    RateLimited,
    RunError,
)
from agentreins.types.events import (
    Event,
    ModelFailed,
    ModelRequested,
    ModelResponded,
    RunCompleted,
    RunFailed,
    RunFailureReason,
    RunStarted,
    ToolCallCompleted,
    ToolCallFailed,
    ToolCallRejected,
    ToolCallRequested,
    ToolCallStarted,
)
from agentreins.types.identity import Principal
from agentreins.types.ids import new_id
from agentreins.types.model import ModelRequest, ModelResponse, ResponseComplete
from agentreins.types.tools import ToolSpec

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How the runtime retries retryable model errors (ADR-0002 D5).

    Attempt ``n`` waits ``base_delay * 2**(n-1)`` seconds, at most ``max_delay``; a
    provider's ``retry_after`` is honoured instead when given (also capped).
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0

    def delay(self, attempt: int, error: ModelError) -> float:
        """Seconds to wait after failed attempt number ``attempt`` (1-based)."""
        if isinstance(error, RateLimited) and error.retry_after is not None:
            return min(error.retry_after, self.max_delay)
        return min(self.base_delay * 2 ** (attempt - 1), self.max_delay)


@dataclass(frozen=True, slots=True)
class ModelSettings:
    """Per-call model settings copied into every ``ModelRequest``."""

    max_tokens: int | None = None
    temperature: float | None = None
    provider_options: dict[str, JsonValue] = field(default_factory=dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class RunResult:
    """A finished run: the answer and what it cost."""

    run_id: str
    output: str
    """The final answer's text."""
    message: Message
    """The final answer, with all its content blocks."""
    usage: Usage
    steps: int
    """Number of model calls (turns)."""


DEFAULT_PRINCIPAL = Principal(id="local")
"""Used when ``run`` gets no principal. Fine on a laptop; in production always pass the
real user, so policy, credentials and the audit log refer to the right person."""


class Runtime:
    """An agent's wiring. Call :meth:`run` once per task; runs are independent."""

    def __init__(
        self,
        *,
        model: ModelAdapter,
        model_name: str,
        harness: ToolHarness,
        ledger: Ledger,
        context: ContextManager,
        instructions: str | None = None,
        hooks: HookDispatcher | None = None,
        budget: Budget | None = None,
        retry: RetryPolicy | None = None,
        settings: ModelSettings | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
    ) -> None:
        self.budget = budget or Budget()
        if self.budget.max_cost_usd is not None:
            raise ValueError(
                "max_cost_usd is not supported yet: agentreins has no model prices. "
                "Use max_tokens to bound a run."
            )
        self.model = model
        self.model_name = model_name
        self.harness = harness
        self.ledger = ledger
        self.context = context
        self.instructions = instructions
        self.hooks = hooks or HookDispatcher()
        self.retry = retry or RetryPolicy()
        self.settings = settings or ModelSettings()
        self.sleep = sleep
        self.clock = clock

    async def run(
        self,
        task: str | Sequence[Message],
        *,
        principal: Principal | None = None,
        session_id: str | None = None,
        run_key: str | None = None,
        governance_lifted: bool = False,
    ) -> RunResult:
        """Run the agent on ``task`` until it answers. Raises :class:`RunError` if the run
        ends without an answer (budget, error, approval needed, cancellation)."""
        messages = [Message.user(task)] if isinstance(task, str) else list(task)
        run = _Run(self, principal or DEFAULT_PRINCIPAL, session_id)
        return await run.execute(messages, run_key, governance_lifted)


class _Stop(Exception):
    """Internal: end the run with ``run.failed``."""

    reason: RunFailureReason

    def __init__(self, reason: RunFailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


Maker = Callable[[int], Event]
"""Builds one event once its ``seq`` is known."""


class _Run:
    """The state of one run. Only this class writes to the ledger for the run."""

    def __init__(self, rt: Runtime, principal: Principal, session_id: str | None) -> None:
        self.rt = rt
        self.principal = principal
        self.session_id = session_id
        self.run_id = new_id()
        self.events: list[Event] = []
        self.usage = Usage()
        self.steps = 0
        self.started_at = rt.clock()
        self._lock = asyncio.Lock()  # parallel tools record concurrently

    # --- recording -----------------------------------------------------------------

    def ev(self, kind: Callable[..., Event], **fields: Any) -> Maker:
        """An event of class ``kind`` for this run; ``seq`` is filled in when recorded.

        All field values are bound now, so the event records the state at this moment.
        """
        return lambda seq: kind(run_id=self.run_id, seq=seq, **fields)

    async def record(self, *makers: Maker) -> list[Event]:
        """Append the events atomically, each with the next ``seq``.

        Returns the events as stored (redacted); only those are used from here on.
        """
        async with self._lock:
            last = len(self.events) - 1
            batch = [make(last + i) for i, make in enumerate(makers, start=1)]
            stored = await self.rt.ledger.append(self.run_id, batch, expected_seq=last)
            self.events.extend(stored)
        for event in stored:
            await self.rt.hooks.emit(event)
        return stored

    # --- the loop ------------------------------------------------------------------

    async def execute(
        self, task: list[Message], run_key: str | None, governance_lifted: bool
    ) -> RunResult:
        tools = await self.rt.harness.visible_tools(self.principal)
        await self.record(
            self.ev(
                RunStarted,
                input=task,
                system=self.rt.instructions,
                model=self.rt.model_name,
                tools=tools,
                budget=self.rt.budget,
                principal=self.principal,
                session_id=self.session_id,
                run_key=run_key,
                governance_lifted=governance_lifted,
            )
        )
        try:
            while True:
                self.check_budget()
                response = await self.model_turn(tools)
                calls = [b for b in response.message.content if isinstance(b, ToolUseBlock)]
                if not calls:
                    return await self.complete(response.message)
                await self.tool_turn(calls)
        except _Stop as stop:
            await self.fail(stop.reason, stop.message)
            raise RunError(stop.message, run_id=self.run_id, reason=stop.reason) from None
        except asyncio.CancelledError:
            await asyncio.shield(self.fail("cancelled", "the run was cancelled"))
            raise
        except PolicyUnavailable as exc:
            await self.fail("error", str(exc))
            raise RunError(str(exc), run_id=self.run_id, reason="error") from exc

    def check_budget(self) -> None:
        """Before each model call. A tool that ran over has already finished and been
        recorded: correct first, then bounded (REQUIREMENTS conflict rules)."""
        budget = self.rt.budget
        if self.steps >= budget.max_steps:
            raise _Stop("max_steps", f"stopped after {self.steps} steps (max_steps)")
        total = self.usage.input_tokens + self.usage.output_tokens
        if budget.max_tokens is not None and total >= budget.max_tokens:
            raise _Stop("budget_exceeded", f"used {total} tokens (max_tokens {budget.max_tokens})")
        self.check_wall_time()

    def check_wall_time(self) -> None:
        """Also checked before a retry: failed attempts count against wall time too."""
        limit = self.rt.budget.max_wall_seconds
        elapsed = self.rt.clock() - self.started_at
        if limit is not None and elapsed >= limit:
            raise _Stop("budget_exceeded", f"ran for {elapsed:.1f} s (max_wall_seconds {limit:g})")

    async def complete(self, message: Message) -> RunResult:
        await self.record(self.ev(RunCompleted, output=message, usage=self.usage))
        return RunResult(
            run_id=self.run_id,
            output=message.text,
            message=message,
            usage=self.usage,
            steps=self.steps,
        )

    async def fail(self, reason: RunFailureReason, message: str) -> None:
        await self.record(self.ev(RunFailed, reason=reason, message=message, usage=self.usage))

    # --- one model turn ------------------------------------------------------------

    async def model_turn(self, tools: list[ToolSpec]) -> ModelResponse:
        """One model call, retried on retryable errors. Returns the reply as stored."""
        self.steps += 1
        step = self.steps
        system = self.rt.instructions
        history = project_messages(self.events)
        messages = await self.rt.context.select(history, system=system, tools=tools)
        shrunk = False
        attempt = 0
        while True:
            attempt += 1
            request = self.request(messages, tools)
            await self.record(
                self.ev(
                    ModelRequested,
                    step=step,
                    message_count=len(request.messages),
                    input_fingerprint=_fingerprint(request),
                )
            )
            began = self.rt.clock()
            try:
                response = await self.call_model(request)
            except ModelError as exc:
                await self.record(
                    self.ev(
                        ModelFailed,
                        step=step,
                        attempt=attempt,
                        error=type(exc).__name__,
                        message=str(exc),
                        retryable=exc.retryable,
                    )
                )
                if isinstance(exc, ContextTooLong) and not shrunk:
                    smaller = await self.rt.context.shrink(messages, system=system, tools=tools)
                    if smaller is not None:  # one retry with less context (ADR-0009 D3)
                        messages, shrunk = smaller, True
                        continue
                if not exc.retryable or attempt >= self.rt.retry.max_attempts:
                    message = f"model call failed: {type(exc).__name__}: {exc}"
                    raise _Stop("error", message) from exc
                self.check_wall_time()
                await self.rt.sleep(self.rt.retry.delay(attempt, exc))
                continue
            latency_ms = max((self.rt.clock() - began) * 1000, 0.0)
            [stored] = await self.record(
                self.ev(ModelResponded, step=step, response=response, latency_ms=latency_ms)
            )
            assert isinstance(stored, ModelResponded)
            self.usage = self.usage + stored.response.usage
            return stored.response  # the redacted version: what the log holds

    def request(self, messages: list[Message], tools: list[ToolSpec]) -> ModelRequest:
        settings = self.rt.settings
        return ModelRequest(
            model=self.rt.model_name,
            messages=messages,
            system=self.rt.instructions,
            tools=tools,
            max_tokens=settings.max_tokens,
            temperature=settings.temperature,
            provider_options=settings.provider_options,
        )

    async def call_model(self, request: ModelRequest) -> ModelResponse:
        """Stream when someone is watching (hooks get every delta), else one call."""
        if not self.rt.hooks.active:
            return await self.rt.model.get_response(request)
        final: ModelResponse | None = None
        async for event in self.rt.model.stream_response(request):
            await self.rt.hooks.emit(event)
            if isinstance(event, ResponseComplete):
                final = event.response
        if final is None:
            raise RuntimeError("model stream ended without a complete response")
        return final

    # --- one tool turn -------------------------------------------------------------

    async def tool_turn(self, calls: list[ToolUseBlock]) -> None:
        """Check every call, stop if one needs approval, run the rest in parallel."""
        await self.record(
            *[
                self.ev(ToolCallRequested, call_id=c.id, name=c.name, arguments=c.arguments)
                for c in calls
            ]
        )
        checked = [await self.check(c) for c in calls]
        approvals = [c for c in checked if isinstance(c, NeedsApproval)]
        if approvals:
            name, reason = approvals[0].spec.name, approvals[0].reason
            raise _Stop(
                "error",
                f"{name} needs approval ({reason}). Approvals arrive in M7; "
                f"to allow it now, use DefaultPolicy(allow=[{name!r}]).",
            )
        prepared: list[Prepared] = []
        for call, outcome in zip(calls, checked, strict=True):
            if isinstance(outcome, Ready):
                ready = await self.rt.harness.prepare(
                    outcome, principal=self.principal, run_id=self.run_id
                )
                if isinstance(ready, Prepared):
                    prepared.append(ready)
                    continue
                outcome = ready
            assert isinstance(outcome, Rejected)
            await self.record(
                self.ev(
                    ToolCallRejected,
                    call_id=call.id,
                    reason=outcome.reason,
                    message=outcome.message,
                )
            )
        if not prepared:
            return
        # Intent records first, in one batch: nothing runs before all are on disk.
        await self.record(
            *[
                self.ev(
                    ToolCallStarted,
                    call_id=p.call.id,
                    effect=p.spec.effect,
                    idempotency_key=p.context.idempotency_key,
                )
                for p in prepared
            ]
        )
        await asyncio.gather(*[self.run_tool(p) for p in prepared])

    async def check(self, call: ToolUseBlock) -> Rejected | NeedsApproval | Ready:
        return await self.rt.harness.check(
            call,
            principal=self.principal,
            run_id=self.run_id,
            session_id=self.session_id,
            usage=self.usage,
        )

    async def run_tool(self, prepared: Prepared) -> None:
        """Run one tool and record its outcome as soon as it finishes."""
        outcome = await self.rt.harness.execute(prepared)
        if isinstance(outcome, Completed):
            await self.record(
                self.ev(
                    ToolCallCompleted,
                    call_id=prepared.call.id,
                    result=outcome.result,
                    duration_ms=outcome.duration_ms,
                )
            )
        else:
            await self.record(
                self.ev(
                    ToolCallFailed,
                    call_id=prepared.call.id,
                    error=outcome.error,
                    timed_out=outcome.timed_out,
                    duration_ms=outcome.duration_ms,
                )
            )


def _fingerprint(request: ModelRequest) -> str:
    """SHA-256 of the exact request, so a resumed run can detect a different projection."""
    return hashlib.sha256(request.model_dump_json().encode()).hexdigest()
