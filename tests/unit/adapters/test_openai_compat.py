"""OpenAI Chat Completions adapter: translation both ways, streaming, errors."""

import json
from typing import Any

import httpx
import pytest

from agentreins.adapters.models.openai_compat import OpenAIChatModel, from_completion, to_payload
from agentreins.types.budget import Usage
from agentreins.types.content import (
    ImageBlock,
    Message,
    ReasoningBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from agentreins.types.errors import (
    AuthFailed,
    BadRequest,
    ContextTooLong,
    ModelError,
    ModelTimeout,
    ProviderUnavailable,
    RateLimited,
)
from agentreins.types.model import (
    ForceTool,
    ModelRequest,
    ResponseComplete,
    TextDelta,
    ToolArgsDelta,
    ToolUseStart,
    UsageUpdate,
)
from agentreins.types.tools import Effect, ToolSpec
from openai_fakes import FakeProvider, Reply

SPEC = ToolSpec(
    name="get_stock",
    description="Stock on hand.",
    input_schema={"type": "object", "properties": {"sku": {"type": "string"}}},
    effect=Effect.READ_ONLY,
)


def request(*messages: Message, **kwargs: Any) -> ModelRequest:
    return ModelRequest(model="gpt-test", messages=list(messages or [Message.user("hi")]), **kwargs)


# --- request translation -------------------------------------------------------------


def test_basic_request() -> None:
    payload = to_payload(request(system="Be brief.", max_tokens=100, temperature=0.2, stop=["END"]))
    assert payload == {
        "model": "gpt-test",
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "hi"},
        ],
        "max_tokens": 100,
        "temperature": 0.2,
        "stop": ["END"],
    }


def test_tool_round_trip_uses_provider_ids_and_puts_results_first() -> None:
    call = ToolUseBlock(
        id="ours-1", provider_id="call_abc", name="get_stock", arguments={"sku": "W1"}
    )
    bad = ToolUseBlock(
        id="ours-2",
        provider_id="call_def",
        name="get_stock",
        raw_arguments="{oops",
        parse_error="x",
    )
    payload = to_payload(
        request(
            Message.user("stock?"),
            Message(
                role="assistant",
                content=[ReasoningBlock(text="thinking"), TextBlock(text="Checking."), call, bad],
            ),
            Message(
                role="user",
                content=[
                    TextBlock(text="also hurry"),
                    ToolResultBlock(tool_use_id="ours-1", content=[TextBlock(text="7")]),
                    ToolResultBlock(
                        tool_use_id="ours-2", content=[TextBlock(text="bad args")], is_error=True
                    ),
                ],
            ),
        )
    )
    assert payload["messages"][1:] == [
        {
            "role": "assistant",
            "content": "Checking.",  # reasoning is not sent back
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {"name": "get_stock", "arguments": '{"sku": "W1"}'},
                },
                {
                    "id": "call_def",
                    "type": "function",
                    "function": {"name": "get_stock", "arguments": "{oops"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_abc", "content": "7"},
        {"role": "tool", "tool_call_id": "call_def", "content": "Error: bad args"},
        {"role": "user", "content": "also hurry"},
    ]


def test_images_become_content_parts() -> None:
    payload = to_payload(
        request(
            Message(
                role="user",
                content=[
                    TextBlock(text="What is this?"),
                    ImageBlock(media_type="image/png", data="AAAA"),
                    ImageBlock(media_type="image/jpeg", url="https://x.test/a.jpg"),
                ],
            )
        )
    )
    assert payload["messages"][0]["content"] == [
        {"type": "text", "text": "What is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "image_url", "image_url": {"url": "https://x.test/a.jpg"}},
    ]


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("auto", "auto"),
        ("required", "required"),
        ("none", "none"),
        (ForceTool(name="get_stock"), {"type": "function", "function": {"name": "get_stock"}}),
    ],
)
def test_tools_and_tool_choice(choice: Any, expected: Any) -> None:
    payload = to_payload(request(tools=[SPEC], tool_choice=choice))
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "get_stock",
                "description": "Stock on hand.",
                "parameters": SPEC.input_schema,
            },
        }
    ]
    assert payload["tool_choice"] == expected


def test_no_tools_means_no_tool_choice() -> None:
    assert "tool_choice" not in to_payload(request())


def test_streaming_flags_and_provider_options_win() -> None:
    payload = to_payload(
        request(max_tokens=10, provider_options={"max_completion_tokens": 10, "max_tokens": None}),
        stream=True,
    )
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["max_completion_tokens"] == 10
    assert payload["max_tokens"] is None


# --- response translation ------------------------------------------------------------


def test_text_response() -> None:
    response = from_completion(Reply(text="Paris.", usage=(20, 3, 8)).completion())
    assert response.message == Message.assistant("Paris.")
    assert response.stop_reason == "end_turn"
    assert response.usage == Usage(input_tokens=20, output_tokens=3, cache_read_tokens=8)
    assert (response.model, response.request_id) == ("gpt-test", "chatcmpl-1")


def test_tool_calls_get_our_own_ids() -> None:
    reply = Reply(
        calls=[("call_a", "get_stock", '{"sku": "W1"}'), ("call_b", "get_stock", '{"sku": "W2"}')],
        finish="tool_calls",
    )
    response = from_completion(reply.completion())
    calls = [b for b in response.message.content if isinstance(b, ToolUseBlock)]
    assert [c.provider_id for c in calls] == ["call_a", "call_b"]
    assert [c.arguments for c in calls] == [{"sku": "W1"}, {"sku": "W2"}]
    assert len({c.id for c in calls}) == 2
    assert not any(c.id.startswith("call_") for c in calls)
    assert response.stop_reason == "tool_use"


@pytest.mark.parametrize(
    ("arguments", "error"),
    [("{not json", "Expecting"), ("[1, 2]", "must be a JSON object")],
)
def test_bad_tool_arguments_are_kept_and_flagged(arguments: str, error: str) -> None:
    response = from_completion(Reply(calls=[("c", "get_stock", arguments)]).completion())
    [call] = [b for b in response.message.content if isinstance(b, ToolUseBlock)]
    assert call.raw_arguments == arguments
    assert call.parse_error is not None
    assert error in call.parse_error


def test_empty_arguments_mean_no_arguments() -> None:
    response = from_completion(Reply(calls=[("c", "ping", "")]).completion())
    [call] = [b for b in response.message.content if isinstance(b, ToolUseBlock)]
    assert (call.arguments, call.parse_error) == ({}, None)


@pytest.mark.parametrize(
    ("finish", "stop"),
    [
        ("stop", "end_turn"),
        ("length", "max_tokens"),
        ("content_filter", "refusal"),
        ("tool_calls", "tool_use"),
        ("weird", "end_turn"),
    ],
)
def test_stop_reasons(finish: str, stop: str) -> None:
    assert from_completion(Reply(text="x", finish=finish).completion()).stop_reason == stop


def test_tool_calls_with_finish_stop_still_mean_tool_use() -> None:
    reply = Reply(calls=[("c", "get_stock", "{}")], finish="stop")
    assert from_completion(reply.completion()).stop_reason == "tool_use"


def test_reasoning_and_refusal() -> None:
    data = Reply(text="Answer", reasoning="Step 1").completion()
    response = from_completion(data)
    assert response.message.content == [ReasoningBlock(text="Step 1"), TextBlock(text="Answer")]
    data["choices"][0]["message"] = {
        "role": "assistant",
        "content": None,
        "refusal": "I can't help.",
    }
    refused = from_completion(data)
    assert (refused.stop_reason, refused.message.text) == ("refusal", "I can't help.")


def test_response_without_choices_is_a_provider_error() -> None:
    with pytest.raises(ProviderUnavailable):
        from_completion({"id": "x", "choices": []})


# --- over HTTP -----------------------------------------------------------------------


async def test_get_response_over_http_sends_key_and_url() -> None:
    provider = FakeProvider(Reply(text="Paris."))
    model = provider.model(base_url="https://llm.example/v1/")
    response = await model.get_response(request())
    assert response.message.text == "Paris."
    assert provider.headers[0]["authorization"] == "Bearer sk-test"
    await model.close()


def test_api_key_from_environment_or_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert OpenAIChatModel()._headers["Authorization"] == "Bearer sk-env"  # pyright: ignore[reportPrivateUsage]
    monkeypatch.delenv("OPENAI_API_KEY")
    assert "Authorization" not in OpenAIChatModel()._headers  # pyright: ignore[reportPrivateUsage]


async def test_stream_deltas_and_final_response() -> None:
    reply = Reply(
        text="Checking stock.",
        reasoning="Need the tool.",
        calls=[("call_a", "get_stock", '{"sku": "W1"}')],
        finish="tool_calls",
    )
    provider = FakeProvider(reply)
    events = [e async for e in provider.model().stream_response(request())]
    assert provider.sent[0]["stream"] is True
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Checking stock."
    [start] = [e for e in events if isinstance(e, ToolUseStart)]
    assert start.name == "get_stock"
    args = "".join(e.delta for e in events if isinstance(e, ToolArgsDelta))
    assert args == '{"sku": "W1"}'
    assert isinstance(events[-2], UsageUpdate)
    final = events[-1]
    assert isinstance(final, ResponseComplete)
    [call] = [b for b in final.response.message.content if isinstance(b, ToolUseBlock)]
    assert (call.id, call.provider_id, call.arguments) == (start.id, "call_a", {"sku": "W1"})
    assert final.response.usage == Usage(input_tokens=12, output_tokens=7)


async def test_mid_stream_error_event() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"index":0,"delta":{"content":"Hi"}}]}\n\n'
            'data: {"error": {"message": "overloaded"}}\n\n'
        )
        return httpx.Response(200, content=body.encode())

    with pytest.raises(ProviderUnavailable, match="overloaded"):
        _ = [e async for e in FakeProvider(broken).model().stream_response(request())]


# --- errors --------------------------------------------------------------------------


def status(code: int, body: Any = None, headers: dict[str, str] | None = None) -> FakeProvider:
    content = json.dumps(body if body is not None else {"error": {"message": "nope"}})
    return FakeProvider(lambda _: httpx.Response(code, content=content.encode(), headers=headers))


def raising(exc: Exception) -> FakeProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return FakeProvider(handler)


ERRORS: list[tuple[str, FakeProvider, type[ModelError]]] = [
    ("429", status(429, headers={"retry-after": "2.5"}), RateLimited),
    ("401", status(401), AuthFailed),
    ("403", status(403), AuthFailed),
    ("500", status(500), ProviderUnavailable),
    ("503", status(503), ProviderUnavailable),
    (
        "context",
        status(
            400,
            {
                "error": {
                    "message": "This model's maximum context length is 8192 tokens",
                    "code": "context_length_exceeded",
                }
            },
        ),
        ContextTooLong,
    ),
    (
        "400",
        status(400, {"error": {"message": "Unknown parameter", "type": "invalid_request_error"}}),
        BadRequest,
    ),
    ("404-text", FakeProvider(lambda _: httpx.Response(404, content=b"not found")), BadRequest),
    ("408", status(408), ModelTimeout),
    ("timeout", raising(httpx.ReadTimeout("slow")), ModelTimeout),
    ("connect", raising(httpx.ConnectError("refused")), ProviderUnavailable),
    (
        "bad-json",
        FakeProvider(lambda _: httpx.Response(200, content=b"<html>")),
        ProviderUnavailable,
    ),
]


@pytest.mark.parametrize(("case", "provider", "error"), ERRORS, ids=[e[0] for e in ERRORS])
async def test_errors_are_normalized(
    case: str, provider: FakeProvider, error: type[ModelError]
) -> None:
    with pytest.raises(error) as caught:
        await provider.model().get_response(request())
    assert caught.value.provider == "openai_compat"
    if case == "429":
        assert isinstance(caught.value, RateLimited)
        assert caught.value.retry_after == 2.5
        assert caught.value.retryable


@pytest.mark.parametrize(("case", "provider", "error"), ERRORS, ids=[e[0] for e in ERRORS])
async def test_stream_errors_are_normalized(
    case: str, provider: FakeProvider, error: type[ModelError]
) -> None:
    with pytest.raises(error):
        _ = [e async for e in provider.model().stream_response(request())]
