from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.models.settings import Settings
from app.services.vision import SiliconFlowVisionClient, VisionServiceError


def _make_client(handler) -> SiliconFlowVisionClient:
    transport = httpx.MockTransport(handler)
    settings = Settings(vision_api_key="test-key")
    return SiliconFlowVisionClient(settings, transport=transport)


def test_extract_page_returns_structured_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"].startswith("Bearer ")
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "Qwen/Qwen3-VL-32B-Instruct"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"page_text":"This apple is red.","marked_words":["apple"]}'
                        }
                    }
                ]
            },
        )

    client = _make_client(handler)
    result = asyncio.run(client.extract_page(b"png-bytes", 1))

    assert result.page_text == "This apple is red."
    assert result.marked_words == ["apple"]


def test_extract_page_rejects_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    client = _make_client(handler)

    with pytest.raises(VisionServiceError) as excinfo:
        asyncio.run(client.extract_page(b"png-bytes", 2))

    assert "invalid JSON" in str(excinfo.value)


def test_extract_page_requires_expected_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"page_text":"Only text"}'}}]})

    client = _make_client(handler)

    with pytest.raises(VisionServiceError) as excinfo:
        asyncio.run(client.extract_page(b"png-bytes", 3))

    assert "marked_words" in str(excinfo.value)


def test_extract_page_surfaces_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    client = _make_client(handler)

    with pytest.raises(VisionServiceError) as excinfo:
        asyncio.run(client.extract_page(b"png-bytes", 4))

    assert "HTTP 429" in str(excinfo.value)


def test_extract_page_surfaces_timeouts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client = _make_client(handler)

    with pytest.raises(VisionServiceError) as excinfo:
        asyncio.run(client.extract_page(b"png-bytes", 5))

    assert "timed out" in str(excinfo.value).lower()
