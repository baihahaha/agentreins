"""Structured output: the hidden ``final_result`` tool (ADR-0002 D4).

The model gives its final answer by calling ``final_result``, whose arguments are the
requested output type. This works with every provider that supports tools, and the
answer is validated like any tool call.
"""

from typing import Any, Generic, TypeVar, cast

from pydantic import JsonValue, TypeAdapter, ValidationError

from agentreins.types.tools import Effect, ToolSpec

T = TypeVar("T")

FINAL_RESULT = "final_result"
"""Reserved tool name: no other tool may use it."""


class InvalidOutput(ValueError):
    """The model's final answer did not match the output type; the message is for it."""


class OutputSchema(Generic[T]):
    """Turns an output type into the ``final_result`` tool, and validates answers.

    Types that are JSON objects (pydantic models, dataclasses, TypedDicts) become the
    tool's arguments directly. Anything else (``int``, ``list[str]``…) is wrapped as
    ``{"result": ...}``, because tool arguments must be an object.
    """

    def __init__(self, output_type: type[T] | Any) -> None:
        self.output_type = output_type
        self._adapter: TypeAdapter[T] = TypeAdapter(output_type)
        schema = cast(dict[str, JsonValue], self._adapter.json_schema())
        self.wrapped = schema.get("type") != "object"
        if self.wrapped:
            defs = schema.pop("$defs", None)
            properties: dict[str, JsonValue] = {"result": schema}
            outer: dict[str, JsonValue] = {
                "type": "object",
                "properties": properties,
                "required": ["result"],
                "additionalProperties": False,
            }
            if defs is not None:
                outer["$defs"] = defs  # references stay valid at the top level
            schema = outer
        self.spec = ToolSpec(
            name=FINAL_RESULT,
            description=(
                "Give your final answer. Call this once, when you are done; "
                "the run ends when the answer is valid."
            ),
            input_schema=schema,
            effect=Effect.READ_ONLY,
        )

    def validate(self, arguments: dict[str, JsonValue]) -> T:
        """The answer as ``output_type``, or :class:`InvalidOutput` explaining why not."""
        data: object = arguments
        if self.wrapped:
            if "result" not in arguments:
                raise InvalidOutput("result: Field required")
            data = arguments["result"]
        try:
            return self._adapter.validate_python(data)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in e['loc']) or 'result'}: {e['msg']}"
                for e in exc.errors(include_url=False)
            )
            raise InvalidOutput(problems) from None

    def dump(self, value: T) -> JsonValue:
        """``value`` as JSON, for the ``run.completed`` event."""
        return cast(JsonValue, self._adapter.dump_python(value, mode="json"))
