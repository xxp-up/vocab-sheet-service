from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import httpx

from app.models.settings import Settings
from app.services.audio import AudioService


def _make_test_dir() -> Path:
    root = Path("D:/workspace/vocab-sheet-service/.runtime/test-audio") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_transcribe_feedback_audio_uses_remote_transcription() -> None:
    root = _make_test_dir()
    try:
        audio_path = root / "lesson.m4a"
        audio_path.write_bytes(b"fake-audio")

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/v1/audio/transcriptions"
            assert request.headers["Authorization"] == "Bearer test-key"
            return httpx.Response(
                200,
                json={"text": "\u4eca\u5929\u590d\u4e60\u4e00\u822c\u7591\u95ee\u53e5\u548c\u5426\u5b9a\u53e5\uff0c\u8bfe\u540e\u5b8c\u6210\u7ffb\u8bd1\u9898\u3002"},
            )

        service = AudioService(
            Settings(
                request_timeout_seconds=30,
                runtime_root=str(root / "runtime"),
                vision_api_key="test-key",
                vision_base_url="https://api.example.com/v1",
                vision_model="model-a",
                vision_timeout_seconds=30,
            ),
            transport=httpx.MockTransport(handler),
        )

        result = asyncio.run(service.transcribe_feedback_audio(audio_path))

        assert (
            result.transcript_text
            == "\u4eca\u5929\u590d\u4e60\u4e00\u822c\u7591\u95ee\u53e5\u548c\u5426\u5b9a\u53e5\uff0c\u8bfe\u540e\u5b8c\u6210\u7ffb\u8bd1\u9898\u3002"
        )
        assert result.candidate_words == []
    finally:
        shutil.rmtree(root, ignore_errors=True)
