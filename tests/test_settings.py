from __future__ import annotations

import asyncio
from pathlib import Path
import shutil
import uuid

import pytest

from app.models.schemas import SettingsUpdateRequest
from app.models.settings import ConfigurationError, Settings, mask_secret
from app.services import settings_manager
from app.services.settings_manager import SettingsManager, SettingsValidationError


def _make_env_dir() -> Path:
    root = Path("D:/workspace/vocab-sheet-service/.runtime/test-settings") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_require_vision_api_key_returns_trimmed_value() -> None:
    settings = Settings(vision_api_key="  test-key  ")

    assert settings.require_vision_api_key() == "test-key"


def test_require_vision_api_key_rejects_blank_value() -> None:
    settings = Settings(vision_api_key="   ")

    with pytest.raises(ConfigurationError) as excinfo:
        settings.require_vision_api_key()

    assert "VISION_API_KEY" in str(excinfo.value)


def test_mask_secret_keeps_last_four_characters() -> None:
    assert mask_secret("abcdef123456") == "********3456"
    assert mask_secret("key") == "***"


def test_settings_manager_updates_env_file_and_masks_secret() -> None:
    root = _make_env_dir()
    try:
        env_path = root / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "REQUEST_TIMEOUT_SECONDS=90",
                    "RUNTIME_ROOT=.runtime",
                    "VISION_API_KEY=old-secret",
                    "VISION_BASE_URL=https://api.example.com/v1",
                    "VISION_MODEL=model-a",
                    "VISION_TIMEOUT_SECONDS=80",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        manager = SettingsManager(env_path=env_path)

        response = manager.update_settings(
            SettingsUpdateRequest(
                request_timeout_seconds=120,
                runtime_root=".runtime-updated",
                vision_api_key="new-secret-1234",
                vision_base_url="https://api.changed.example/v1",
                vision_model="model-b",
                vision_timeout_seconds=95,
            )
        )

        content = env_path.read_text(encoding="utf-8")
        assert "REQUEST_TIMEOUT_SECONDS=120" in content
        assert "RUNTIME_ROOT=.runtime-updated" in content
        assert "VISION_API_KEY=new-secret-1234" in content
        assert response.vision_api_key_masked.endswith("1234")
        assert response.vision_api_key_configured is True
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_settings_manager_validate_uses_current_secret_when_input_is_blank(monkeypatch) -> None:
    root = _make_env_dir()
    try:
        env_path = root / ".env"
        env_path.write_text(
            "\n".join(
                [
                    "REQUEST_TIMEOUT_SECONDS=90",
                    "RUNTIME_ROOT=.runtime",
                    "VISION_API_KEY=current-secret",
                    "VISION_BASE_URL=https://api.example.com/v1",
                    "VISION_MODEL=model-a",
                    "VISION_TIMEOUT_SECONDS=80",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        manager = SettingsManager(env_path=env_path)
        captured: dict[str, str] = {}

        async def _fake_validate(settings: Settings) -> None:
            captured["api_key"] = settings.vision_api_key

        monkeypatch.setattr(settings_manager, "validate_vision_settings", _fake_validate)

        response = asyncio.run(
            manager.validate_settings(
                SettingsUpdateRequest(
                    request_timeout_seconds=90,
                    runtime_root=".runtime",
                    vision_api_key="",
                    vision_base_url="https://api.example.com/v1",
                    vision_model="model-a",
                    vision_timeout_seconds=80,
                )
            )
        )

        assert response.ok is True
        assert captured["api_key"] == "current-secret"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_validate_vision_settings_raises_on_http_failure(monkeypatch) -> None:
    class _Response:
        status_code = 403

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return _Response()

    monkeypatch.setattr(settings_manager.httpx, "AsyncClient", _Client)

    with pytest.raises(SettingsValidationError):
        asyncio.run(
            settings_manager.validate_vision_settings(
                Settings(
                    request_timeout_seconds=90,
                    runtime_root=".runtime",
                    vision_api_key="test-secret",
                    vision_base_url="https://api.example.com/v1",
                    vision_model="model-a",
                    vision_timeout_seconds=80,
                )
            )
        )
