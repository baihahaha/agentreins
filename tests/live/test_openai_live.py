"""Real calls to OpenAI Chat Completions. Run with ``pytest -m live``.

Set ``AGENTREINS_RECORD=1`` to also save each raw response into
``tests/recorded/openai/``, which the offline recorded tests replay. Only the request
body and the response body are saved: never headers, so never the API key.
"""

import json
import os
from pathlib import Path

import httpx
import pytest

from agentreins.adapters.models.openai_compat import OpenAIChatModel
from agentreins.types.model import ModelResponse, ResponseComplete
from model_cases import CASES, case, check

pytestmark = pytest.mark.live

RECORDINGS = Path(__file__).resolve().parents[1] / "recorded" / "openai"


class RecordingTransport(httpx.AsyncBaseTransport):
    """Passes requests to the real network; optionally saves request and response bodies."""

    def __init__(self, name: str, record: bool) -> None:
        self._inner = httpx.AsyncHTTPTransport()
        self._name = name
        self._record = record

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        body = await response.aread()
        content_type = response.headers.get("content-type", "application/json")
        if self._record:
            RECORDINGS.mkdir(parents=True, exist_ok=True)
            fixture = {
                "request": json.loads(request.content),
                "status": response.status_code,
                "content_type": content_type,
                "body": body.decode(),
            }
            path = RECORDINGS / f"{self._name}.json"
            path.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + "\n")
        # Body is already decoded; pass only the content type, not encoding headers.
        return httpx.Response(
            response.status_code,
            content=body,
            headers={"content-type": content_type},
            request=request,
        )

    async def aclose(self) -> None:
        await self._inner.aclose()


@pytest.mark.parametrize("name", CASES)
async def test_openai_live(name: str, openai_api_key: str) -> None:
    record = os.environ.get("AGENTREINS_RECORD") == "1"
    client = httpx.AsyncClient(transport=RecordingTransport(name, record))
    model = OpenAIChatModel(api_key=openai_api_key, client=client)
    request = case(name)
    response: ModelResponse
    if name.startswith("stream_"):
        events = [e async for e in model.stream_response(request)]
        final = events[-1]
        assert isinstance(final, ResponseComplete)
        response = final.response
    else:
        response = await model.get_response(request)
    await model.close()
    check(name, response)
