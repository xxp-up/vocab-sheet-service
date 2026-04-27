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
from app.models.schemas import SettingsResponse, SettingsUpdateRequest, SettingsValidateResponse
from app.models.settings import ConfigurationError
from app.services.settings_manager import SettingsValidationError
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


def test_index_renders_workspace_sections() -> None:
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "教材题词与课后反馈工作台" in response.text
    assert "系统配置" in response.text
    assert "支持 PDF / DOCX" in response.text
    assert "template/test 6单词表模板.xlsx" in response.text


def test_fill_route_uses_fixed_template_and_teaching_filename(monkeypatch) -> None:
    class _Pipeline:
        async def process(
            self,
            teaching_path: Path,
            output_path: Path,
            *,
            audio_path: Path | None = None,
            words_text: str | None = None,
            progress_callback=None,
        ):
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
        async def process(
            self,
            teaching_path: Path,
            output_path: Path,
            *,
            audio_path: Path | None = None,
            words_text: str | None = None,
            progress_callback=None,
        ):
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
        async def process(
            self,
            teaching_path: Path,
            output_path: Path,
            *,
            audio_path: Path | None = None,
            words_text: str | None = None,
            progress_callback=None,
        ):
            raise ConfigurationError("missing VISION_API_KEY")

    monkeypatch.setattr(routes, "build_pipeline", lambda settings: _BrokenPipeline())
    client = TestClient(app)

    response = client.post(
        "/v1/vocab/fill",
        files={"teaching_file": ("lesson.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "missing VISION_API_KEY"}


def test_create_vocab_job_route_uses_job_store(monkeypatch) -> None:
    class _Pipeline:
        pass

    class _FakeJobStore:
        async def create_vocab_job(self, **kwargs):
            assert isinstance(kwargs["pipeline"], _Pipeline)
            assert kwargs["words_text"] == "apple"
            return {
                "job_id": "job-123",
                "status": "queued",
                "progress_percent": 0,
                "stage_code": "queued",
                "stage_label": "等待开始",
            }

    app.dependency_overrides[routes.get_job_store] = lambda: _FakeJobStore()
    monkeypatch.setattr(routes, "build_pipeline", lambda settings: _Pipeline())
    client = TestClient(app)

    response = client.post(
        "/v1/vocab/jobs",
        files={"teaching_file": ("lesson.pdf", b"%PDF-1.4", "application/pdf")},
        data={"words_text": "apple"},
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"


def test_get_vocab_job_route_uses_job_store() -> None:
    class _FakeJobStore:
        async def get_vocab_job(self, job_id: str):
            assert job_id == "job-123"
            return {
                "job_id": job_id,
                "status": "completed",
                "progress_percent": 100,
                "stage_code": "download_ready",
                "stage_label": "准备下载",
                "rows_written": 3,
                "skipped_words": {"idea": "未在教材正文中定位到例句"},
                "error_message": None,
                "download_url": f"/v1/vocab/jobs/{job_id}/download",
                "output_filename": "lesson_filled.xlsx",
            }

    app.dependency_overrides[routes.get_job_store] = lambda: _FakeJobStore()
    client = TestClient(app)

    response = client.get("/v1/vocab/jobs/job-123")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["rows_written"] == 3


def test_feedback_job_route_rejects_missing_source() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/feedback/jobs",
        data={"lesson_date": "2026-03-11", "lesson_index": "1", "class_name": "五年级"},
    )

    assert response.status_code == 400
    assert "课堂音频或逐字稿文本" in response.json()["detail"]


def test_regenerate_feedback_section_route_uses_job_store() -> None:
    class _FakeJobStore:
        async def regenerate_feedback_section(self, **kwargs):
            assert kwargs["job_id"] == "job-123"
            assert kwargs["section_key"] == "patterns"
            assert kwargs["draft_sections"][0].key == "focus"
            return {
                "key": "patterns",
                "title": "规则 / 句型",
                "content": "1. 重新整理后的规则总结。",
            }

    app.dependency_overrides[routes.get_job_store] = lambda: _FakeJobStore()
    client = TestClient(app)

    response = client.post(
        "/v1/feedback/jobs/job-123/sections/patterns/regenerate",
        json={
            "draft_sections": [
                {"key": "focus", "title": "本节课重点", "content": "⭐️旧内容"},
                {"key": "patterns", "title": "规则 / 句型", "content": "1. 旧规则"},
            ]
        },
    )

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["content"] == "1. 重新整理后的规则总结。"


def test_settings_routes_use_manager_dependency() -> None:
    class _FakeSettingsManager:
        def get_settings_response(self) -> SettingsResponse:
            return SettingsResponse(
                request_timeout_seconds=90,
                runtime_root=".runtime",
                vision_base_url="https://api.example.com/v1",
                vision_model="model-a",
                vision_timeout_seconds=80,
                vision_api_key_masked="******1234",
                vision_api_key_configured=True,
            )

        def update_settings(self, payload: SettingsUpdateRequest) -> SettingsResponse:
            assert payload.vision_model == "model-b"
            return self.get_settings_response().model_copy(update={"vision_model": "model-b"})

        async def validate_settings(self, payload: SettingsUpdateRequest) -> SettingsValidateResponse:
            assert payload.runtime_root == ".runtime"
            return SettingsValidateResponse(ok=True, detail="ok")

    app.dependency_overrides[routes.get_settings_manager] = lambda: _FakeSettingsManager()
    client = TestClient(app)

    read_response = client.get("/v1/settings")
    update_response = client.put(
        "/v1/settings",
        json={
            "request_timeout_seconds": 90,
            "runtime_root": ".runtime",
            "vision_api_key": None,
            "vision_base_url": "https://api.example.com/v1",
            "vision_model": "model-b",
            "vision_timeout_seconds": 80,
        },
    )
    validate_response = client.post(
        "/v1/settings/validate",
        json={
            "request_timeout_seconds": 90,
            "runtime_root": ".runtime",
            "vision_api_key": None,
            "vision_base_url": "https://api.example.com/v1",
            "vision_model": "model-b",
            "vision_timeout_seconds": 80,
        },
    )

    app.dependency_overrides.clear()
    assert read_response.status_code == 200
    assert read_response.json()["vision_api_key_masked"] == "******1234"
    assert update_response.status_code == 200
    assert update_response.json()["vision_model"] == "model-b"
    assert validate_response.status_code == 200
    assert validate_response.json()["ok"] is True


def test_validate_settings_maps_validation_error() -> None:
    class _BrokenSettingsManager:
        async def validate_settings(self, payload: SettingsUpdateRequest) -> SettingsValidateResponse:
            raise SettingsValidationError("bad config")

    app.dependency_overrides[routes.get_settings_manager] = lambda: _BrokenSettingsManager()
    client = TestClient(app)

    response = client.post(
        "/v1/settings/validate",
        json={
            "request_timeout_seconds": 90,
            "runtime_root": ".runtime",
            "vision_api_key": None,
            "vision_base_url": "https://api.example.com/v1",
            "vision_model": "model-b",
            "vision_timeout_seconds": 80,
        },
    )

    app.dependency_overrides.clear()
    assert response.status_code == 400
    assert response.json()["detail"] == "bad config"
