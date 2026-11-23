"""Replay real OpenAI responses offline (recorded by tests/live/test_openai_live.py).

Each replay checks both directions: the request the adapter sends today must equal
the recorded one (catches translation drift), and the recorded real response must
parse into the expected answer.
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentreins.adapters.models.openai_compat import OpenAIChatModel
from agentreins.types.model import ModelResponse, ResponseComplete
from model_cases import CASES, case, check

RECORDINGS = Path(__file__).resolve().parent / "openai"


def load(name: str) -> dict[str, Any]:
    path = RECORDINGS / f"{name}.json"
    if not path.exists():
        pytest.fail(f"missing recording {path.name}: run AGENTREINS_RECORD=1 pytest -m live")
    return json.loads(path.read_text())


@pytest.mark.parametrize("name", CASES)
async def test_replay(name: str) -> None:
    fixture = load(name)
    sent: list[dict[str, Any]] = []

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            fixture["status"],
            content=fixture["body"].encode(),
            headers={"content-type": fixture["content_type"]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    model = OpenAIChatModel(api_key="sk-test", client=client)
    request = case(name, model=fixture["request"]["model"])
    response: ModelResponse
    if name.startswith("stream_"):
        events = [e async for e in model.stream_response(request)]
        final = events[-1]
        assert isinstance(final, ResponseComplete)
        response = final.response
    else:
        response = await model.get_response(request)
    assert sent == [fixture["request"]]
    check(name, response)


def test_recordings_contain_no_secrets() -> None:
    for path in RECORDINGS.glob("*.json"):
        text = path.read_text()
        assert "sk-" not in text, path.name
        assert "Bearer" not in text, path.name
