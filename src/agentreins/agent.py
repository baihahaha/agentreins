"""``Agent``: the public entry point. Builds the runtime and plugs in default adapters.

This module is part of the public API layer (ARCHITECTURE.md, layer 4): it is the one
place allowed to choose adapters, so the engines below never depend on any of them.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agentreins.adapters.context_strategies.keep_all import KeepAll
from agentreins.adapters.credentials.env import EnvCredentialProvider
from agentreins.adapters.event_stores.sqlite import SQLiteEventStore
from agentreins.adapters.models.fake import FakeModel
from agentreins.adapters.policies.default import DefaultPolicy
from agentreins.adapters.redactors.passthrough import PassThroughRedactor
from agentreins.adapters.tool_sources.python import FunctionTool, PythonToolSource
from agentreins.context.manager import ContextManager
from agentreins.ledger.ledger import Ledger
from agentreins.ports.context import ContextStrategy
from agentreins.ports.credentials import CredentialProvider
from agentreins.ports.event_store import EventStore
from agentreins.ports.hooks import Hooks
from agentreins.ports.model import ModelAdapter
from agentreins.ports.policy import Policy
from agentreins.ports.redactor import Redactor
from agentreins.ports.tool_source import ToolSource
from agentreins.runtime.hooks import HookDispatcher
from agentreins.runtime.loop import ModelSettings, RetryPolicy, RunResult, Runtime
from agentreins.tools.harness import ToolHarness
from agentreins.tools.registry import ToolRegistry
from agentreins.types.budget import Budget
from agentreins.types.content import Message
from agentreins.types.identity import Principal

DEFAULT_DB = "agentreins.db"
PROVIDERS = ("openai",)


class Agent:
    """An agent: a model, instructions, tools, and the governance around them.

    >>> agent = Agent("openai:gpt-4.1-mini", tools=[get_stock])
    >>> result = await agent.run("How many W1 do we have?")

    ``model`` is either ``"provider:model-name"`` (today: ``openai:…``, which also
    reads ``OPENAI_API_KEY``) or an adapter object such as ``OpenAIChatModel(...)`` with
    ``model_name=``. ``tools`` mixes ``@tool`` functions and tool sources.

    Everything else has a safe default:

    =============  ==========================================================
    ``store``      ``SQLiteEventStore("agentreins.db")``: durable, created on first run
    ``policy``     ``DefaultPolicy()``: reads allowed, side effects need approval
    ``credentials``  ``EnvCredentialProvider()``: same key for everyone, dev only
    ``redactor``   ``PassThroughRedactor()``: stores events unchanged
    ``context``    ``KeepAll()``: sends the whole conversation
    ``budget``     ``Budget()``: 25 steps
    =============  ==========================================================

    One ``Agent`` can serve many runs, also concurrently. Call :meth:`close` (or use
    ``async with``) to release the database and network connections.
    """

    def __init__(
        self,
        model: str | ModelAdapter,
        *,
        model_name: str | None = None,
        instructions: str | None = None,
        tools: Sequence[FunctionTool[..., Any] | ToolSource] = (),
        policy: Policy | None = None,
        credentials: CredentialProvider | None = None,
        store: EventStore | None = None,
        redactor: Redactor | None = None,
        context: ContextStrategy | None = None,
        hooks: Sequence[Hooks] = (),
        budget: Budget | None = None,
        retry: RetryPolicy | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> None:
        self._model, self._model_name = _resolve_model(model, model_name)
        self._owns_model = isinstance(model, str)
        self._instructions = instructions
        self._tools = list(tools)
        self._policy = policy or DefaultPolicy()
        self._credentials = credentials or EnvCredentialProvider()
        self._store = store
        self._owns_store = store is None
        self._redactor = redactor or PassThroughRedactor()
        self._strategy = context or KeepAll()
        self._hooks = list(hooks)
        self._budget = budget or Budget()
        if self._budget.max_cost_usd is not None:
            raise ValueError(
                "max_cost_usd is not supported yet: agentreins has no model prices. "
                "Use max_tokens to bound a run."
            )
        self._retry = retry
        self._settings = ModelSettings(max_tokens=max_tokens, temperature=temperature)
        self._runtime: Runtime | None = None
        self._registry: ToolRegistry | None = None
        self._building = asyncio.Lock()

    @property
    def model_name(self) -> str:
        """The model name sent with every request."""
        return self._model_name

    async def run(
        self,
        task: str | Sequence[Message],
        *,
        principal: Principal | None = None,
        session_id: str | None = None,
        run_key: str | None = None,
    ) -> RunResult:
        """Run the agent on ``task`` until it answers.

        ``principal`` is who the run acts for: policy, credentials and the audit log
        refer to it. Without one, ``Principal(id="local")`` is used: fine on a laptop,
        never in production. Raises ``RunError`` if the run ends without an answer.
        """
        runtime = await self._build()
        return await runtime.run(task, principal=principal, session_id=session_id, run_key=run_key)

    def run_sync(
        self,
        task: str | Sequence[Message],
        *,
        principal: Principal | None = None,
        session_id: str | None = None,
        run_key: str | None = None,
    ) -> RunResult:
        """:meth:`run` for plain scripts: starts an event loop, runs, closes the agent.

        Inside async code (a notebook, a web server), use ``await agent.run(...)``.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("run_sync() cannot be used inside async code: use await agent.run()")

        async def once() -> RunResult:
            try:
                return await self.run(
                    task, principal=principal, session_id=session_id, run_key=run_key
                )
            finally:
                await self.close()

        return asyncio.run(once())

    async def close(self) -> None:
        """Release connections. Safe to call twice.

        Closes the tool sources, plus the model client and database *if the agent created
        them* (from a model string, or the default store). Objects you passed in may be
        shared, so they stay open: close them yourself.
        """
        if self._registry is not None:
            await self._registry.close()
        if self._owns_model:
            await _close(self._model)
        if self._owns_store and self._store is not None:
            await _close(self._store)
            self._store = None
        self._runtime, self._registry, self._building = None, None, asyncio.Lock()

    async def __aenter__(self) -> "Agent":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def _build(self) -> Runtime:
        """Build the runtime on first use: tool sources may need to connect (MCP)."""
        async with self._building:
            if self._runtime is not None:
                return self._runtime
            functions = [t for t in self._tools if isinstance(t, FunctionTool)]
            sources: list[ToolSource] = [t for t in self._tools if not isinstance(t, FunctionTool)]
            if functions:
                sources.insert(0, PythonToolSource(functions))
            self._registry = await ToolRegistry.from_sources(sources)
            if self._store is None:
                self._store = SQLiteEventStore(DEFAULT_DB)
            self._runtime = Runtime(
                model=self._model,
                model_name=self._model_name,
                harness=ToolHarness(self._registry, self._policy, self._credentials),
                ledger=Ledger(self._store, self._redactor),
                context=ContextManager(self._strategy, self._model.capabilities.max_context_tokens),
                instructions=self._instructions,
                hooks=HookDispatcher(self._hooks),
                budget=self._budget,
                retry=self._retry,
                settings=self._settings,
            )
            return self._runtime


async def _close(thing: object) -> None:
    """Await ``thing.close()`` if it has one (adapters are not required to)."""
    close: Callable[[], Awaitable[object]] | None = getattr(thing, "close", None)
    if close is not None:
        await close()


def _resolve_model(model: str | ModelAdapter, model_name: str | None) -> tuple[ModelAdapter, str]:
    """``"openai:gpt-4.1-mini"`` -> an adapter and a model name."""
    if not isinstance(model, str):
        if model_name is None:
            if isinstance(model, FakeModel):
                return model, "fake"
            raise ValueError(
                "pass model_name= with a model adapter, e.g. model_name='gpt-4.1-mini'"
            )
        return model, model_name
    provider, sep, name = model.partition(":")
    if not sep or not name:
        raise ValueError(f"model must look like 'provider:model-name', got {model!r}")
    if model_name is not None:
        raise ValueError("model_name= is only for adapter objects; the string already names it")
    if provider == "openai":
        try:
            from agentreins.adapters.models.openai_compat import OpenAIChatModel
        except ImportError as exc:  # httpx is in the providers extra
            raise ImportError(
                "the openai provider needs httpx: pip install 'agentreins[providers]'"
            ) from exc
        return OpenAIChatModel(), name
    raise ValueError(
        f"unknown provider {provider!r}; supported: {', '.join(PROVIDERS)}. "
        "For any other server, pass an adapter object, e.g. OpenAIChatModel(base_url=...)."
    )
