"""Build fake Chat Completions responses (JSON and streamed) for offline tests."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from agentreins.adapters.models.openai_compat import OpenAIChatModel

Json = dict[str, Any]


@dataclass
class Reply:
    """What the fake provider answers, independent of streamed or not."""

    text: str = ""
    reasoning: str = ""
    calls: Sequence[tuple[str, str, str]] = ()  # (provider id, name, arguments JSON text)
    finish: str = "stop"
    usage: tuple[int, int, int] = (12, 7, 0)  # prompt, completion, cached
    model: str = "gpt-test"

    def completion(self) -> Json:
        message: Json = {"role": "assistant", "content": self.text or None}
        if self.reasoning:
            message["reasoning_content"] = self.reasoning
        if self.calls:
            message["tool_calls"] = [
                {"id": pid, "type": "function", "function": {"name": name, "arguments": args}}
                for pid, name, args in self.calls
            ]
        return {
            "id": "chatcmpl-1",
            "model": self.model,
            "choices": [{"index": 0, "message": message, "finish_reason": self.finish}],
            "usage": self._usage(),
        }

    def sse(self, chunk: int = 5) -> str:
        def event(choices: list[Json], **extra: Any) -> str:
            return (
                "data: "
                + json.dumps({"id": "chatcmpl-1", "model": self.model, "choices": choices, **extra})
                + "\n\n"
            )

        def delta(d: Json) -> str:
            return event([{"index": 0, "delta": d}])

        out = [": keep-alive comment\n\n", delta({"role": "assistant", "content": ""})]
        out += [delta({"reasoning_content": p}) for p in _pieces(self.reasoning, chunk)]
        out += [delta({"content": p}) for p in _pieces(self.text, chunk)]
        for i, (pid, name, args) in enumerate(self.calls):
            first = {
                "index": i,
                "id": pid,
                "type": "function",
                "function": {"name": name, "arguments": ""},
            }
            out.append(delta({"tool_calls": [first]}))
            out += [
                delta({"tool_calls": [{"index": i, "function": {"arguments": p}}]})
                for p in _pieces(args, chunk)
            ]
        out.append(event([{"index": 0, "delta": {}, "finish_reason": self.finish}]))
        out.append(event([], usage=self._usage()))
        out.append("data: [DONE]\n\n")
        return "".join(out)

    def _usage(self) -> Json:
        prompt, completion, cached = self.usage
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": cached},
        }


@dataclass
class FakeProvider:
    """An httpx transport that answers every request with ``reply`` and keeps the bodies."""

    reply: Reply | Callable[[httpx.Request], httpx.Response] = field(default_factory=Reply)
    sent: list[Json] = field(default_factory=list[Json])
    headers: list[httpx.Headers] = field(default_factory=list[httpx.Headers])

    def handle(self, request: httpx.Request) -> httpx.Response:
        body: Json = json.loads(request.content)
        self.sent.append(body)
        self.headers.append(request.headers)
        if callable(self.reply):
            return self.reply(request)
        if body.get("stream"):
            return httpx.Response(
                200,
                content=self.reply.sse().encode(),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json=self.reply.completion())

    def model(self, **kwargs: Any) -> OpenAIChatModel:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        return OpenAIChatModel(api_key="sk-test", client=client, **kwargs)


def _pieces(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]
