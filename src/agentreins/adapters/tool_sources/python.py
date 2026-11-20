"""Tool source for plain Python functions, and the ``@tool`` decorator.

Implements a port; may import only agentreins.types and agentreins.ports.
"""

import asyncio
import inspect
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Generic, Literal, ParamSpec, TypeVar, get_type_hints, overload

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError, create_model

from agentreins.types.errors import InvalidToolArguments
from agentreins.types.tools import Effect, ToolCall, ToolContext, ToolResult, ToolSpec

P = ParamSpec("P")
R = TypeVar("R")

EffectName = Effect | Literal["read_only", "idempotent", "side_effecting"]

_ANY_JSON: TypeAdapter[Any] = TypeAdapter(Any)


class FunctionTool(Generic[P, R]):
    """A Python function plus its ToolSpec. Still callable like the original function."""

    def __init__(
        self, fn: Callable[P, R], spec: ToolSpec, args: type[BaseModel], context_param: str | None
    ) -> None:
        self.fn = fn
        self.spec = spec
        self._args = args
        self._context_param = context_param

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        return self.fn(*args, **kwargs)

    def validate(self, arguments: dict[str, JsonValue]) -> BaseModel:
        """Full pydantic validation (with type conversion, e.g. ``"2"`` -> ``2``)."""
        try:
            return self._args.model_validate(arguments)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}"
                for e in exc.errors(include_url=False)
            )
            raise InvalidToolArguments(problems) from None

    async def run(self, arguments: dict[str, JsonValue], context: ToolContext) -> ToolResult:
        parsed = self.validate(arguments)
        kwargs: dict[str, Any] = {name: getattr(parsed, name) for name in type(parsed).model_fields}
        if self._context_param is not None:
            kwargs[self._context_param] = context
        fn: Callable[..., Any] = self.fn
        if inspect.iscoroutinefunction(fn):
            value = await fn(**kwargs)
        else:
            # Sync functions run in a worker thread so they never block the event loop.
            # A thread cannot be killed: on timeout it keeps running in the background.
            value = await asyncio.to_thread(fn, **kwargs)
        return _to_result(value)


@overload
def tool(fn: Callable[P, R], /) -> FunctionTool[P, R]: ...


@overload
def tool(
    *,
    name: str | None = None,
    description: str | None = None,
    effect: EffectName = Effect.SIDE_EFFECTING,
    timeout_seconds: float = 300.0,
    requires: Sequence[str] = (),
) -> Callable[[Callable[P, R]], FunctionTool[P, R]]: ...


def tool(
    fn: Callable[P, R] | None = None,
    /,
    *,
    name: str | None = None,
    description: str | None = None,
    effect: EffectName = Effect.SIDE_EFFECTING,
    timeout_seconds: float = 300.0,
    requires: Sequence[str] = (),
) -> FunctionTool[P, R] | Callable[[Callable[P, R]], FunctionTool[P, R]]:
    """Turn a function into a tool. Use as ``@tool`` or ``@tool(effect="read_only")``.

    - Name: the function name. Description: its docstring (required).
    - Arguments: from the type hints, validated by pydantic. A parameter annotated
      ``ToolContext`` receives the run context and is hidden from the model.
    - ``effect`` defaults to ``side_effecting`` (safe default: needs approval under the
      default policy). Declare ``read_only`` or ``idempotent`` when true.
    """

    def wrap(f: Callable[P, R]) -> FunctionTool[P, R]:
        return _build(f, name, description, Effect(effect), timeout_seconds, list(requires))

    return wrap(fn) if fn is not None else wrap


class PythonToolSource:
    """Serves ``@tool`` functions to the harness. Also validates their arguments."""

    def __init__(self, tools: Iterable[FunctionTool[..., Any]]) -> None:
        self._tools: dict[str, FunctionTool[..., Any]] = {}
        for t in tools:
            if t.spec.name in self._tools:
                raise ValueError(f"two tools are named {t.spec.name!r}")
            self._tools[t.spec.name] = t

    async def list_tools(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    async def validate(self, name: str, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return self._tools[name].validate(arguments).model_dump(mode="json")

    async def call(self, call: ToolCall, context: ToolContext) -> ToolResult:
        return await self._tools[call.name].run(call.arguments, context)

    async def close(self) -> None:
        return None


# --- internals -----------------------------------------------------------------------


def _build(
    fn: Callable[P, R],
    name: str | None,
    description: str | None,
    effect: Effect,
    timeout_seconds: float,
    requires: list[str],
) -> FunctionTool[P, R]:
    tool_name = name or fn.__name__
    doc = description if description is not None else inspect.getdoc(fn)
    if not doc:
        raise ValueError(
            f"tool {tool_name!r} needs a docstring or description=: the model reads it"
        )
    hints = get_type_hints(fn, include_extras=True)
    fields: dict[str, Any] = {}
    context_param: str | None = None
    for param in inspect.signature(fn).parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise ValueError(f"tool {tool_name!r}: *args and **kwargs are not supported")
        if param.name not in hints:
            raise ValueError(f"tool {tool_name!r}: parameter {param.name!r} needs a type hint")
        if hints[param.name] is ToolContext:
            context_param = param.name
            continue
        default = ... if param.default is param.empty else param.default
        fields[param.name] = (hints[param.name], default)
    args = create_model(  # pyright: ignore[reportCallIssue, reportUnknownVariableType]
        f"{tool_name}_arguments", __config__=ConfigDict(extra="forbid"), **fields
    )
    schema: dict[str, JsonValue] = args.model_json_schema()  # pyright: ignore[reportUnknownMemberType]
    spec = ToolSpec(
        name=tool_name,
        description=doc,
        input_schema=schema,
        effect=effect,
        timeout_seconds=timeout_seconds,
        requires=requires,
    )
    return FunctionTool(fn, spec, args, context_param)  # pyright: ignore[reportUnknownArgumentType]


def _to_result(value: object) -> ToolResult:
    if isinstance(value, ToolResult):
        return value
    if isinstance(value, str):
        return ToolResult.text(value)
    if value is None:
        return ToolResult.text("(no output)")
    return ToolResult.text(_ANY_JSON.dump_json(value).decode())
