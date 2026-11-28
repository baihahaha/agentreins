"""OpenAI Chat Completions adapter (also Kimi, DeepSeek, Qwen, vLLM, Ollama...).

Needs the ``providers`` extra (``httpx``). Speaks HTTP directly: no vendor SDK.

Implements a port; may import only agentreins.types and agentreins.ports.
"""

import json
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from typing import Any, NoReturn, cast

import httpx

from agentreins.types.budget import Usage
from agentreins.types.content import (
    ContentBlock,
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
from agentreins.types.ids import new_id
from agentreins.types.model import (
    ForceTool,
    ModelCapabilities,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ReasoningDelta,
    ResponseComplete,
    StopReason,
    TextDelta,
    ToolArgsDelta,
    ToolUseStart,
    UsageUpdate,
)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
PROVIDER = "openai_compat"

_STOP_REASONS: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
    "content_filter": "refusal",
}

Json = dict[str, Any]


def _obj(value: object) -> Json:
    """``value`` if it is a JSON object, else ``{}``: provider JSON is untrusted."""
    return cast(Json, value) if isinstance(value, dict) else {}


def _arr(value: object) -> list[object]:
    """``value`` if it is a JSON array, else ``[]``."""
    return cast(list[object], value) if isinstance(value, list) else []


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


class OpenAIChatModel:
    """Calls any server that speaks the OpenAI Chat Completions API.

    - ``base_url``: e.g. ``http://localhost:11434/v1`` for Ollama.
    - ``api_key``: defaults to the ``OPENAI_API_KEY`` environment variable; local
      servers that need no key work without one.
    - ``max_context_tokens``: the model's context window (default 128k); the context
      manager uses it to decide when to trim.
    - ``client``: pass your own ``httpx.AsyncClient`` to share connections or, in
      tests, to plug in a mock transport.

    The model name comes from each ``ModelRequest``. The adapter never retries: it
    raises normalized errors and the runtime decides (ADR-0002 D5).
    """

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        max_context_tokens: int = 128_000,
        images: bool = False,
        parallel_tool_calls: bool = True,
        timeout: float = 120.0,
        headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY")
        self._headers = {"Content-Type": "application/json", **(headers or {})}
        if key:
            self._headers["Authorization"] = f"Bearer {key}"
        self._timeout = timeout
        self._client = client or httpx.AsyncClient()
        self._capabilities = ModelCapabilities(
            max_context_tokens=max_context_tokens,
            images=images,
            parallel_tool_calls=parallel_tool_calls,
        )

    @property
    def capabilities(self) -> ModelCapabilities:
        return self._capabilities

    async def get_response(self, request: ModelRequest) -> ModelResponse:
        payload = to_payload(request)
        try:
            response = await self._client.post(
                self._url, json=payload, headers=self._headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            _raise_transport_error(exc)
        if response.status_code >= 400:
            raise to_error(response.status_code, response.text, response.headers)
        try:
            data: Json = response.json()
        except ValueError as exc:
            raise ProviderUnavailable("provider returned invalid JSON", provider=PROVIDER) from exc
        return from_completion(data)

    async def stream_response(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        payload = to_payload(request, stream=True)
        state = _StreamState()
        try:
            async with self._client.stream(
                "POST", self._url, json=payload, headers=self._headers, timeout=self._timeout
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode(errors="replace")
                    raise to_error(response.status_code, body, response.headers)
                async for line in response.aiter_lines():
                    for event in state.feed(line):
                        yield event
        except httpx.HTTPError as exc:
            _raise_transport_error(exc)
        yield ResponseComplete(response=state.finish())

    async def close(self) -> None:
        """Close the HTTP client (also one you passed in)."""
        await self._client.aclose()


# --- request: our types -> Chat Completions JSON --------------------------------------


def to_payload(request: ModelRequest, *, stream: bool = False) -> Json:
    """Translate a ``ModelRequest`` into a Chat Completions request body."""
    messages: list[Json] = []
    if request.system:
        messages.append({"role": "system", "content": request.system})
    provider_ids: dict[str, str] = {}  # our call ID -> the provider's, for tool results
    for message in request.messages:
        if message.role == "assistant":
            messages.append(_assistant_message(message, provider_ids))
        else:
            messages.extend(_user_messages(message, provider_ids))

    payload: Json = {"model": request.model, "messages": messages}
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.input_schema,
                },
            }
            for spec in request.tools
        ]
        choice = request.tool_choice
        payload["tool_choice"] = (
            {"type": "function", "function": {"name": choice.name}}
            if isinstance(choice, ForceTool)
            else choice
        )
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.stop:
        payload["stop"] = request.stop
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    payload.update(request.provider_options)  # provider-specific settings win
    return payload


def _assistant_message(message: Message, provider_ids: dict[str, str]) -> Json:
    text = "".join(b.text for b in message.content if isinstance(b, TextBlock))
    out: Json = {"role": "assistant", "content": text or None}
    calls: list[Json] = []
    for block in message.content:
        if isinstance(block, ToolUseBlock):
            provider_id = block.provider_id or block.id
            provider_ids[block.id] = provider_id
            arguments = block.raw_arguments if block.parse_error else json.dumps(block.arguments)
            calls.append(
                {
                    "id": provider_id,
                    "type": "function",
                    "function": {"name": block.name, "arguments": arguments},
                }
            )
    if calls:
        out["tool_calls"] = calls
    # ReasoningBlocks are not sent back: Chat Completions providers do not accept them.
    return out


def _user_messages(message: Message, provider_ids: dict[str, str]) -> list[Json]:
    out: list[Json] = []
    # Tool results first: they must directly follow the assistant's tool calls.
    for block in message.content:
        if isinstance(block, ToolResultBlock):
            text = "\n".join(c.text for c in block.content if isinstance(c, TextBlock))
            if any(isinstance(c, ImageBlock) for c in block.content):
                text += "\n[image omitted: tool messages cannot carry images]"
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": provider_ids.get(block.tool_use_id, block.tool_use_id),
                    "content": f"Error: {text}" if block.is_error else text,
                }
            )
    parts = [p for b in message.content if (p := _user_part(b)) is not None]
    if parts:
        only_text = all(p["type"] == "text" for p in parts)
        content: Any = "".join(p["text"] for p in parts) if only_text else parts
        out.append({"role": "user", "content": content})
    return out


def _user_part(block: ContentBlock) -> Json | None:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ImageBlock):
        url = block.url or f"data:{block.media_type};base64,{block.data}"
        return {"type": "image_url", "image_url": {"url": url}}
    return None


# --- response: Chat Completions JSON -> our types -------------------------------------


def from_completion(data: Json) -> ModelResponse:
    """Translate a (non-streamed) Chat Completions response into a ``ModelResponse``."""
    choices = _arr(data.get("choices"))
    if not choices:
        raise ProviderUnavailable("provider response has no choices", provider=PROVIDER)
    choice = _obj(choices[0])
    message = _obj(choice.get("message"))
    calls: list[_Call] = []
    for item in _arr(message.get("tool_calls")):
        call, function = _obj(item), _obj(_obj(item).get("function"))
        calls.append(
            _Call(
                our_id=new_id(),
                provider_id=_str(call.get("id")),
                name=_str(function.get("name")),
                arguments=_str(function.get("arguments")),
            )
        )
    return _build_response(
        text=_str(message.get("content")),
        reasoning=_str(message.get("reasoning_content")),
        refusal=_str(message.get("refusal")),
        calls=calls,
        finish_reason=_str(choice.get("finish_reason")) or None,
        usage=_obj(data.get("usage")),
        model=_str(data.get("model")),
        request_id=_str(data.get("id")) or None,
    )


@dataclass
class _Call:
    our_id: str
    provider_id: str
    name: str
    arguments: str = ""


def _build_response(
    *,
    text: str,
    reasoning: str,
    refusal: str,
    calls: list[_Call],
    finish_reason: str | None,
    usage: Json | None,
    model: str,
    request_id: str | None,
) -> ModelResponse:
    blocks: list[ContentBlock] = []
    if reasoning:
        blocks.append(ReasoningBlock(text=reasoning))
    if text:
        blocks.append(TextBlock(text=text))
    if refusal:
        blocks.append(TextBlock(text=refusal))
    blocks += [_tool_use(c) for c in calls]

    stop = _STOP_REASONS.get(finish_reason or "", "end_turn")
    if refusal:
        stop = "refusal"
    elif calls and stop == "end_turn":
        stop = "tool_use"  # some compatible servers say "stop" even when calling tools
    return ModelResponse(
        message=Message(role="assistant", content=blocks),
        stop_reason=stop,
        usage=_usage(usage),
        model=model,
        request_id=request_id,
    )


def _tool_use(call: _Call) -> ToolUseBlock:
    arguments, error = _parse_arguments(call.arguments)
    if arguments is None:
        return ToolUseBlock(
            id=call.our_id,
            provider_id=call.provider_id or None,
            name=call.name,
            raw_arguments=call.arguments,
            parse_error=error,
        )
    return ToolUseBlock(
        id=call.our_id, provider_id=call.provider_id or None, name=call.name, arguments=arguments
    )


def _parse_arguments(raw: str) -> tuple[Json | None, str]:
    """The arguments as a dict, or None and why. Bad JSON is kept, not fatal (ADR-0002 D3)."""
    try:
        value: object = json.loads(raw if raw.strip() else "{}")
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(value, dict):
        return None, "arguments must be a JSON object"
    return cast(Json, value), ""


def _usage(usage: Json | None) -> Usage:
    """``input_tokens`` counts all input, cached included; ``cache_read_tokens`` is the
    cached part of it."""
    if not usage:
        return Usage()
    details = _obj(usage.get("prompt_tokens_details"))
    return Usage(
        input_tokens=int(usage.get("prompt_tokens") or 0),
        output_tokens=int(usage.get("completion_tokens") or 0),
        cache_read_tokens=int(details.get("cached_tokens") or 0),
    )


# --- streaming ----------------------------------------------------------------------


@dataclass
class _StreamState:
    """Accumulates server-sent events into deltas and, at the end, the full response."""

    text: str = ""
    reasoning: str = ""
    refusal: str = ""
    calls: dict[int, _Call] = field(default_factory=dict[int, _Call])
    finish_reason: str | None = None
    usage: Json | None = None
    model: str = ""
    request_id: str | None = None
    received: bool = False

    def feed(self, line: str) -> list[ModelStreamEvent]:
        """Process one line of the event stream; return the deltas it produced."""
        if not line.startswith("data:"):
            return []  # blank separators, comments, "event:" lines
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            return []
        try:
            chunk = _obj(json.loads(data))
        except json.JSONDecodeError as exc:
            raise ProviderUnavailable("provider sent an invalid stream event") from exc
        self.received = True
        if "error" in chunk:
            error = _obj(chunk["error"])
            raise ProviderUnavailable(
                f"provider error mid-stream: {_str(error.get('message')) or chunk['error']}",
                provider=PROVIDER,
            )
        self.model = _str(chunk.get("model")) or self.model
        self.request_id = _str(chunk.get("id")) or self.request_id
        usage = _obj(chunk.get("usage"))
        if usage:
            self.usage = usage
        events: list[ModelStreamEvent] = []
        for choice in _arr(chunk.get("choices")):
            events += self._feed_choice(_obj(choice))
        if usage:
            events.append(UsageUpdate(usage=_usage(usage)))
        return events

    def _feed_choice(self, choice: Json) -> list[ModelStreamEvent]:
        delta = _obj(choice.get("delta"))
        events: list[ModelStreamEvent] = []
        if piece := _str(delta.get("reasoning_content")):
            self.reasoning += piece
            events.append(ReasoningDelta(text=piece))
        if piece := _str(delta.get("content")):
            self.text += piece
            events.append(TextDelta(text=piece))
        if piece := _str(delta.get("refusal")):
            self.refusal += piece
        for tc in _arr(delta.get("tool_calls")):
            events += self._feed_tool_call(_obj(tc))
        if finish := _str(choice.get("finish_reason")):
            self.finish_reason = finish
        return events

    def _feed_tool_call(self, tc: Json) -> list[ModelStreamEvent]:
        raw_index = tc.get("index")
        index = raw_index if isinstance(raw_index, int) else len(self.calls)
        function = _obj(tc.get("function"))
        events: list[ModelStreamEvent] = []
        call = self.calls.get(index)
        if call is None:
            call = _Call(our_id=new_id(), provider_id=_str(tc.get("id")), name="")
            self.calls[index] = call
        if (provider_id := _str(tc.get("id"))) and not call.provider_id:
            call.provider_id = provider_id
        if (name := _str(function.get("name"))) and not call.name:
            call.name = name
            events.append(ToolUseStart(id=call.our_id, name=call.name))
        if piece := _str(function.get("arguments")):
            call.arguments += piece
            events.append(ToolArgsDelta(id=call.our_id, delta=piece))
        return events

    def finish(self) -> ModelResponse:
        """The complete response, identical to what ``get_response`` would build."""
        if not self.received:
            raise ProviderUnavailable("provider sent no stream events", provider=PROVIDER)
        return _build_response(
            text=self.text,
            reasoning=self.reasoning,
            refusal=self.refusal,
            calls=[self.calls[i] for i in sorted(self.calls)],
            finish_reason=self.finish_reason,
            usage=self.usage,
            model=self.model,
            request_id=self.request_id,
        )


# --- errors ---------------------------------------------------------------------------


def to_error(status: int, body: str, headers: Mapping[str, str]) -> ModelError:
    """Translate an HTTP error response into one of the normalized errors."""
    message, code = _error_details(body)
    text = f"HTTP {status}: {message}"
    if status == 429:
        return RateLimited(
            text,
            retry_after=_retry_after(headers.get("retry-after")),
            provider=PROVIDER,
            status_code=status,
        )
    if status in (401, 403):
        return AuthFailed(text, provider=PROVIDER, status_code=status)
    if status >= 500:
        return ProviderUnavailable(text, provider=PROVIDER, status_code=status)
    lowered = f"{code} {message}".lower()
    if "context_length" in lowered or "maximum context" in lowered or "too long" in lowered:
        return ContextTooLong(text, provider=PROVIDER, status_code=status)
    if status == 408:
        return ModelTimeout(text, provider=PROVIDER, status_code=status)
    return BadRequest(text, provider=PROVIDER, status_code=status)


def _error_details(body: str) -> tuple[str, str]:
    try:
        data: Any = json.loads(body)
    except ValueError:
        return body[:500], ""
    error: object = _obj(data).get("error")
    details = _obj(error)
    if details:
        code = _str(details.get("code")) or _str(details.get("type"))
        return _str(details.get("message")), code
    if isinstance(error, str):
        return error, ""
    return body[:500], ""


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # an HTTP date; rare for model APIs, ignored


def _raise_transport_error(exc: httpx.HTTPError) -> NoReturn:
    if isinstance(exc, httpx.TimeoutException):
        raise ModelTimeout(f"request timed out: {exc}", provider=PROVIDER) from exc
    raise ProviderUnavailable(f"could not reach the provider: {exc}", provider=PROVIDER) from exc
