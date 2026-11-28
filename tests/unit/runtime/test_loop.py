"""The agent loop, end to end with FakeModel: every path through a run."""

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

from agentreins import tool
from agentreins.adapters.context_strategies.keep_all import KeepAll
from agentreins.adapters.credentials.env import EnvCredentialProvider
from agentreins.adapters.event_stores.in_memory import InMemoryEventStore
from agentreins.adapters.models.fake import FakeModel
from agentreins.adapters.policies.default import DefaultPolicy
from agentreins.adapters.redactors.passthrough import PassThroughRedactor
from agentreins.adapters.tool_sources.python import FunctionTool, PythonToolSource
from agentreins.context.manager import ContextManager
from agentreins.ledger.ledger import Ledger
from agentreins.ledger.projections import project_messages
from agentreins.ports.policy import Policy
from agentreins.runtime.hooks import HookDispatcher
from agentreins.runtime.loop import RetryPolicy, Runtime
from agentreins.tools.harness import ToolHarness
from agentreins.tools.registry import ToolRegistry
from agentreins.types.budget import Budget, Usage
from agentreins.types.content import Message, TextBlock, ToolResultBlock
from agentreins.types.errors import (
    AuthFailed,
    ContextTooLong,
    PolicyUnavailable,
    ProviderUnavailable,
    RateLimited,
    RunError,
)
from agentreins.types.events import (
    Event,
    ModelFailed,
    ModelRequested,
    RunCompleted,
    RunFailed,
    RunStarted,
    ToolCallRejected,
)
from agentreins.types.model import ModelStreamEvent, TextDelta
from agentreins.types.policy import Deny, PolicyDecision, PolicyRequest

# --- tools -----------------------------------------------------------------------------


@tool(effect="read_only")
def get_stock(sku: str) -> int:
    """Stock on hand."""
    return {"W1": 7, "W2": 3}.get(sku, 0)


@tool(effect="read_only")
def broken() -> str:
    """Always fails."""
    raise ValueError("database offline")


@tool
def create_po(sku: str, qty: int) -> str:
    """Create a purchase order (side-effecting: needs approval by default)."""
    return f"PO for {qty} x {sku}"


# --- test wiring -----------------------------------------------------------------------


class Clock:
    """A fake clock: tests move time forward explicitly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Setup:
    def __init__(
        self,
        script: Sequence[Any],
        tools: Sequence[FunctionTool[..., Any]] = (get_stock,),
        *,
        policy: Policy | None = None,
        budget: Budget | None = None,
        hooks: Sequence[Any] = (),
        strategy: Any = None,
        on_policy_error: Any = "deny",
    ) -> None:
        self.model = FakeModel(script)
        self.store = InMemoryEventStore()
        self.clock = Clock()
        self.policy = policy or DefaultPolicy()
        self.tools = list(tools)
        self.budget = budget
        self.hooks = list(hooks)
        self.strategy = strategy or KeepAll()
        self.on_policy_error = on_policy_error

    async def runtime(self) -> Runtime:
        registry = await ToolRegistry.from_sources([PythonToolSource(self.tools)])
        harness = ToolHarness(
            registry,
            self.policy,
            EnvCredentialProvider(environ={}),
            on_policy_error=self.on_policy_error,
        )
        return Runtime(
            model=self.model,
            model_name="fake",
            harness=harness,
            ledger=Ledger(self.store, PassThroughRedactor()),
            context=ContextManager(self.strategy, max_context_tokens=100_000),
            instructions="You are a stock clerk.",
            hooks=HookDispatcher(self.hooks, timeout=0.05),
            budget=self.budget,
            retry=RetryPolicy(),
            sleep=self.clock.sleep,
            clock=self.clock,
        )

    async def run(self, task: str = "How many W1?") -> Any:
        return await (await self.runtime()).run(task)

    async def log(self, run_id: str) -> list[Event]:
        events = await self.store.read(run_id)
        assert_valid_log(events)
        return events


def result_text(block: object) -> str:
    """The text of a tool result block (asserting that is what it is)."""
    assert isinstance(block, ToolResultBlock)
    first = block.content[0]
    assert isinstance(first, TextBlock)
    return first.text


def assert_valid_log(events: list[Event]) -> None:
    """Every run's log: seq 0..n-1, starts with run.started, ends finished, projects."""
    assert [e.seq for e in events] == list(range(len(events)))
    assert isinstance(events[0], RunStarted)
    assert isinstance(events[-1], RunCompleted | RunFailed)
    project_messages(events)  # raises if the conversation is broken


def types(events: Sequence[Event]) -> list[str]:
    return [e.type for e in events]


# --- happy paths -------------------------------------------------------------------


async def test_plain_answer() -> None:
    s = Setup([FakeModel.reply("Hello!")])
    result = await s.run("hi")
    assert (result.output, result.steps) == ("Hello!", 1)
    events = await s.log(result.run_id)
    assert types(events) == ["run.started", "model.requested", "model.responded", "run.completed"]
    started = events[0]
    assert isinstance(started, RunStarted)
    assert started.principal.id == "local"
    assert started.system == "You are a stock clerk."
    assert [t.name for t in started.tools] == ["get_stock"]


async def test_one_tool_call_then_answer() -> None:
    s = Setup([FakeModel.call("get_stock", {"sku": "W1"}), FakeModel.reply("7 in stock.")])
    result = await s.run()
    assert result.output == "7 in stock."
    assert result.steps == 2
    assert result.usage == Usage(input_tokens=20, output_tokens=8)
    assert types(await s.log(result.run_id)) == [
        "run.started",
        "model.requested",
        "model.responded",
        "tool.call.requested",
        "tool.call.started",
        "tool.call.completed",
        "model.requested",
        "model.responded",
        "run.completed",
    ]
    # The second model call saw the tool result, rebuilt from the log.
    last = s.model.requests[1].messages[-1]
    [block] = last.content
    assert isinstance(block, ToolResultBlock)
    assert result_text(block) == "7"


async def test_parallel_tool_calls_really_run_together() -> None:
    a_waiting = asyncio.Event()
    b_done = asyncio.Event()

    @tool(effect="read_only")
    async def slow_a() -> str:
        """Waits for b."""
        a_waiting.set()
        await asyncio.wait_for(b_done.wait(), 1)  # deadlocks if run one after another
        return "a"

    @tool(effect="read_only")
    async def slow_b() -> str:
        """Finishes first."""
        await a_waiting.wait()
        b_done.set()
        return "b"

    two_calls = FakeModel.call("slow_a")
    two_calls = two_calls.model_copy(
        update={
            "message": Message(
                role="assistant",
                content=[*two_calls.message.content, *FakeModel.call("slow_b").message.content],
            )
        }
    )
    s = Setup([two_calls, FakeModel.reply("done")], tools=[slow_a, slow_b])
    result = await s.run()
    events = await s.log(result.run_id)
    # Both intent records are written before either tool finishes; b finishes first.
    tool_events = [
        e for e in events if e.type.startswith("tool.call.") and e.type != "tool.call.requested"
    ]
    assert types(tool_events) == [
        "tool.call.started",
        "tool.call.started",
        "tool.call.completed",
        "tool.call.completed",
    ]
    # Results go back to the model in call order (a, b), not completion order.
    [a, b] = s.model.requests[1].messages[-1].content
    assert isinstance(a, ToolResultBlock)
    assert isinstance(b, ToolResultBlock)
    assert [result_text(a), result_text(b)] == ["a", "b"]


# --- tools that do not run -----------------------------------------------------------


class DenyAll:
    async def decide(self, request: PolicyRequest) -> PolicyDecision:
        return Deny(reason="not during inventory count")


async def test_denied_call_is_rejected_and_the_model_is_told() -> None:
    s = Setup(
        [FakeModel.call("get_stock", {"sku": "W1"}), FakeModel.reply("Sorry, blocked.")],
        policy=DenyAll(),
    )
    result = await s.run()
    events = await s.log(result.run_id)
    assert "tool.call.started" not in types(events)
    [rejected] = [e for e in events if isinstance(e, ToolCallRejected)]
    assert (rejected.reason, rejected.message) == ("policy_denied", "not during inventory count")
    [block] = s.model.requests[1].messages[-1].content
    assert isinstance(block, ToolResultBlock)
    assert block.is_error


async def test_unknown_tool_is_rejected() -> None:
    s = Setup([FakeModel.call("delete_everything"), FakeModel.reply("ok")])
    events = await s.log((await s.run()).run_id)
    [rejected] = [e for e in events if isinstance(e, ToolCallRejected)]
    assert rejected.reason == "unknown_tool"


async def test_missing_credentials_reject_the_call_and_the_run_continues() -> None:
    @tool(effect="read_only", requires=["erp"])
    def erp_stock(sku: str) -> int:
        """Stock from the ERP."""
        return 7

    s = Setup(
        [FakeModel.call("erp_stock", {"sku": "W1"}), FakeModel.reply("ERP unreachable.")],
        tools=[erp_stock],
    )
    events = await s.log((await s.run()).run_id)
    [rejected] = [e for e in events if isinstance(e, ToolCallRejected)]
    assert rejected.reason == "credentials_unavailable"
    assert "tool.call.started" not in types(events)


async def test_failing_tool_is_recorded_and_the_run_continues() -> None:
    s = Setup([FakeModel.call("broken"), FakeModel.reply("The database is down.")], tools=[broken])
    result = await s.run()
    events = await s.log(result.run_id)
    assert "tool.call.failed" in types(events)
    [block] = s.model.requests[1].messages[-1].content
    assert isinstance(block, ToolResultBlock)
    assert result_text(block) == "Tool failed: ValueError: database offline"


async def test_approval_needed_stops_the_run_cleanly() -> None:
    s = Setup([FakeModel.call("create_po", {"sku": "W1", "qty": 2})], tools=[create_po])
    with pytest.raises(
        RunError, match=r"approval required: create_po has side effects.*allow=\['create_po'\]"
    ) as caught:
        await s.run("Order 2 W1")
    assert caught.value.reason == "error"
    events = await s.log(caught.value.run_id)
    assert "tool.call.started" not in types(events)
    assert isinstance(events[-1], RunFailed)


async def test_allow_list_lets_the_side_effect_run() -> None:
    s = Setup(
        [FakeModel.call("create_po", {"sku": "W1", "qty": 2}), FakeModel.reply("Ordered.")],
        tools=[create_po],
        policy=DefaultPolicy(allow=["create_po"]),
    )
    assert (await s.run()).output == "Ordered."


async def test_policy_failure_can_fail_the_run() -> None:
    class Broken:
        async def decide(self, request: PolicyRequest) -> PolicyDecision:
            raise RuntimeError("OPA down")

    s = Setup(
        [FakeModel.call("get_stock", {"sku": "W1"})], policy=Broken(), on_policy_error="fail_run"
    )
    with pytest.raises(RunError) as caught:
        await s.run()
    assert isinstance(caught.value.__cause__, PolicyUnavailable)
    await s.log(caught.value.run_id)


# --- model failures and retries ------------------------------------------------------


async def test_retry_then_success() -> None:
    s = Setup([ProviderUnavailable("503"), FakeModel.reply("ok")])
    result = await s.run()
    assert s.clock.sleeps == [1.0]
    events = await s.log(result.run_id)
    assert types(events)[1:6] == [
        "model.requested",
        "model.failed",
        "model.requested",
        "model.responded",
        "run.completed",
    ]
    [failed] = [e for e in events if isinstance(e, ModelFailed)]
    assert (failed.attempt, failed.error, failed.retryable) == (1, "ProviderUnavailable", True)
    assert result.steps == 1  # a retry is not a new step


async def test_retry_after_is_honoured() -> None:
    s = Setup([RateLimited("slow", retry_after=5), FakeModel.reply("ok")])
    await s.run()
    assert s.clock.sleeps == [5.0]


async def test_retries_run_out() -> None:
    s = Setup([ProviderUnavailable("503")] * 3)
    with pytest.raises(RunError, match="ProviderUnavailable") as caught:
        await s.run()
    assert s.clock.sleeps == [1.0, 2.0]
    events = await s.log(caught.value.run_id)
    assert [e.attempt for e in events if isinstance(e, ModelFailed)] == [1, 2, 3]


async def test_non_retryable_error_fails_at_once() -> None:
    s = Setup([AuthFailed("bad key")])
    with pytest.raises(RunError, match="AuthFailed"):
        await s.run()
    assert s.clock.sleeps == []


async def test_context_too_long_with_keep_all_fails_without_retry() -> None:
    s = Setup([ContextTooLong("too long"), FakeModel.reply("never")])
    with pytest.raises(RunError, match="ContextTooLong"):
        await s.run()
    assert s.model.remaining == 1


async def test_context_too_long_retries_once_with_a_smaller_context() -> None:
    class DropOldest:
        async def select(self, messages: list[Message], token_budget: int) -> list[Message]:
            return messages[-1:]

    s = Setup([ContextTooLong("too long"), FakeModel.reply("ok")], strategy=DropOldest())
    runtime = await s.runtime()
    history = [Message.user("old"), Message.assistant("old answer"), Message.user("new")]
    result = await runtime.run(history)
    assert result.output == "ok"
    assert [m.text for m in s.model.requests[1].messages] == ["new"]
    assert s.clock.sleeps == []  # shrinking is not a backoff retry


# --- budgets ---------------------------------------------------------------------------


async def test_max_steps() -> None:
    looping = [FakeModel.call("get_stock", {"sku": "W1"}) for _ in range(5)]
    s = Setup(looping, budget=Budget(max_steps=2))
    with pytest.raises(RunError, match="max_steps") as caught:
        await s.run()
    assert caught.value.reason == "max_steps"
    events = await s.log(caught.value.run_id)
    assert sum(isinstance(e, ModelRequested) for e in events) == 2


async def test_max_tokens() -> None:
    big = FakeModel.call("get_stock", {"sku": "W1"})
    big = big.model_copy(update={"usage": Usage(input_tokens=900, output_tokens=200)})
    s = Setup([big, FakeModel.reply("never")], budget=Budget(max_tokens=1000))
    with pytest.raises(RunError, match="max_tokens") as caught:
        await s.run()
    assert caught.value.reason == "budget_exceeded"
    events = await s.log(caught.value.run_id)
    assert "tool.call.completed" in types(events)  # the tool finished first


async def test_wall_time_runs_out_mid_tool_the_tool_finishes_first() -> None:
    clock_holder: list[Clock] = []

    @tool(effect="read_only")
    def slow_lookup() -> str:
        """Takes a minute."""
        clock_holder[0].now += 60
        return "done"

    s = Setup(
        [FakeModel.call("slow_lookup"), FakeModel.reply("never")],
        tools=[slow_lookup],
        budget=Budget(max_wall_seconds=30),
    )
    clock_holder.append(s.clock)
    with pytest.raises(RunError, match="max_wall_seconds") as caught:
        await s.run()
    events = await s.log(caught.value.run_id)
    assert types(events)[-2:] == ["tool.call.completed", "run.failed"]


def test_cost_budget_is_refused_until_prices_exist() -> None:
    s = Setup([], budget=Budget(max_cost_usd=1.0))
    with pytest.raises(ValueError, match="max_cost_usd"):
        asyncio.run(s.runtime())


# --- cancellation ----------------------------------------------------------------------


async def test_cancelled_run_is_recorded() -> None:
    started = asyncio.Event()

    @tool(effect="read_only")
    async def forever() -> str:
        """Never returns."""
        started.set()
        await asyncio.sleep(3600)
        return "x"

    s = Setup([FakeModel.call("forever")], tools=[forever])
    task = asyncio.create_task(s.run())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    run_id = next(iter(s.store._runs))  # pyright: ignore[reportPrivateUsage]
    events = await s.log(run_id)
    assert isinstance(events[-1], RunFailed)
    assert events[-1].reason == "cancelled"


# --- hooks -----------------------------------------------------------------------------


class Recorder:
    def __init__(self) -> None:
        self.seen: list[Event | ModelStreamEvent] = []

    async def on_event(self, event: Event | ModelStreamEvent) -> None:
        self.seen.append(event)


class Exploding:
    async def on_event(self, event: Event | ModelStreamEvent) -> None:
        raise RuntimeError("hook bug")


class Hanging:
    async def on_event(self, event: Event | ModelStreamEvent) -> None:
        await asyncio.sleep(10)


async def test_hooks_see_events_and_stream_deltas() -> None:
    recorder = Recorder()
    s = Setup([FakeModel.reply("Hello there, how are you?")], hooks=[recorder])
    result = await s.run()
    events = await s.log(result.run_id)
    stored = [e.type for e in recorder.seen if hasattr(e, "seq")]  # events, not deltas
    assert stored == types(events)
    deltas = [e for e in recorder.seen if isinstance(e, TextDelta)]
    assert "".join(d.text for d in deltas) == "Hello there, how are you?"


async def test_failing_and_hanging_hooks_never_stop_a_run(caplog: pytest.LogCaptureFixture) -> None:
    recorder = Recorder()
    s = Setup([FakeModel.reply("fine")], hooks=[Exploding(), Hanging(), recorder])
    result = await s.run()
    assert result.output == "fine"
    assert any(e.type == "run.completed" for e in recorder.seen)
    assert "hook Exploding failed" in caplog.text
    assert "hook Hanging failed" in caplog.text


# --- the log is the truth ---------------------------------------------------------------


async def test_model_requested_fingerprints_the_exact_request() -> None:
    s = Setup([FakeModel.call("get_stock", {"sku": "W1"}), FakeModel.reply("7")])
    events = await s.log((await s.run()).run_id)
    prints = [e.input_fingerprint for e in events if isinstance(e, ModelRequested)]
    assert len(prints) == 2
    assert all(len(p) == 64 for p in prints)
    assert prints[0] != prints[1]


async def test_final_message_is_the_one_in_the_log() -> None:
    s = Setup([FakeModel.reply("Answer")])
    result = await s.run()
    events = await s.log(result.run_id)
    completed = events[-1]
    assert isinstance(completed, RunCompleted)
    assert completed.output == result.message
