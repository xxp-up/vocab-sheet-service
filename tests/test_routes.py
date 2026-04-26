from __future__ import annotations

import asyncio
import io
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile
from fastapi.testclient import TestClient

from app.api import routes
from app.api.routes import _has_selected_file, _save_optional_upload
from app.main import app
from app.models.domain import PipelineResult
from app.models.settings import ConfigurationError
from app.services.vision import VisionServiceError


def _make_test_dir() -> Path:
    root = Path("D:/workspace/vocab-sheet-service/.runtime/test-routes") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_has_selected_file_rejects_blank_filename() -> None:
    upload = UploadFile(file=io.BytesIO(b""), filename="   ")
    assert _has_selected_file(upload) is False


def test_save_optional_upload_skips_blank_filename() -> None:
    root = _make_test_dir()
    try:
        upload = UploadFile(file=io.BytesIO(b""), filename="")
        saved = asyncio.run(_save_optional_upload(upload, root))

        assert saved is None
        assert list(root.iterdir()) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_save_optional_upload_persists_selected_file() -> None:
    root = _make_test_dir()
    try:
        upload = UploadFile(file=io.BytesIO(b"audio"), filename="clip.wav")
        saved = asyncio.run(_save_optional_upload(upload, root))

        assert saved == root / "clip.wav"
        assert saved.read_bytes() == b"audio"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_index_removes_template_upload_control() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "template_file" not in response.text
    assert "test 6" in response.text


def test_fill_route_uses_fixed_template_and_teaching_filename(monkeypatch) -> None:
    class _Pipeline:
        async def process(self, teaching_path: Path, output_path: Path, *, audio_path: Path | None = None, words_text: str | None = None):
            output_path.write_bytes(b"fake-xlsx")
            return PipelineResult(output_path=str(output_path), rows_written=1, skipped_words={})

    monkeypatch.setattr(routes, "build_pipeline", lambda settings: _Pipeline())
    client = TestClient(app)

    response = client.post(
        "/v1/vocab/fill",
        files={"teaching_file": ("lesson.pdf", b"%PDF-1.4", "application/pdf")},
        data={"words_text": "apple"},
    )

    assert response.status_code == 200
    assert response.headers["x-words-written"] == "1"
    assert 'filename="lesson_filled.xlsx"' in response.headers["content-disposition"]


def test_fill_route_maps_vision_errors_to_502(monkeypatch) -> None:
    class _BrokenPipeline:
        async def process(self, teaching_path: Path, output_path: Path, *, audio_path: Path | None = None, words_text: str | None = None):
            raise VisionServiceError("upstream failed")

    monkeypatch.setattr(routes, "build_pipeline", lambda settings: _BrokenPipeline())
    client = TestClient(app)

    response = client.post(
        "/v1/vocab/fill",
        files={"teaching_file": ("lesson.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "upstream failed"}


def test_fill_route_maps_configuration_errors_to_500(monkeypatch) -> None:
    class _BrokenPipeline:
        async def process(self, teaching_path: Path, output_path: Path, *, audio_path: Path | None = None, words_text: str | None = None):
            raise ConfigurationError("缺少 VISION_API_KEY，请先配置。")

    monkeypatch.setattr(routes, "build_pipeline", lambda settings: _BrokenPipeline())
    client = TestClient(app)

    response = client.post(
        "/v1/vocab/fill",
        files={"teaching_file": ("lesson.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "缺少 VISION_API_KEY，请先配置。"}
