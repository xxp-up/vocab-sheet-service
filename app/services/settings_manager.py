from __future__ import annotations

from pathlib import Path

import httpx

from app.models.schemas import SettingsResponse, SettingsUpdateRequest, SettingsValidateResponse
from app.models.settings import (
    SETTINGS_ENV_KEYS,
    Settings,
    get_env_file_path,
    get_settings,
    mask_secret,
    serialize_env_value,
)


class SettingsValidationError(ValueError):
    """Raised when proposed settings cannot be validated."""


class SettingsManager:
    def __init__(self, env_path: Path | None = None) -> None:
        self.env_path = env_path or get_env_file_path()

    def get_settings_response(self) -> SettingsResponse:
        settings = self._load_current_settings()
        return self._to_response(settings)

    def update_settings(self, payload: SettingsUpdateRequest) -> SettingsResponse:
        current = self._load_current_settings()
        next_settings = self._build_settings(payload, current)
        values = self._serialize_settings(next_settings)
        self._write_env_values(values)
        get_settings.cache_clear()
        return self._to_response(next_settings)

    async def validate_settings(self, payload: SettingsUpdateRequest) -> SettingsValidateResponse:
        current = self._load_current_settings()
        candidate = self._build_settings(payload, current)
        await validate_vision_settings(candidate)
        return SettingsValidateResponse(ok=True, detail="视觉服务连接校验通过。")

    def _load_current_settings(self) -> Settings:
        return Settings(_env_file=str(self.env_path))

    def _build_settings(self, payload: SettingsUpdateRequest, current: Settings) -> Settings:
        api_key = payload.vision_api_key
        if api_key is None or not api_key.strip():
            api_key = current.vision_api_key

        return Settings(
            request_timeout_seconds=payload.request_timeout_seconds,
            runtime_root=payload.runtime_root,
            vision_api_key=api_key,
            vision_base_url=payload.vision_base_url,
            vision_model=payload.vision_model,
            vision_timeout_seconds=payload.vision_timeout_seconds,
        )

    def _to_response(self, settings: Settings) -> SettingsResponse:
        return SettingsResponse(
            request_timeout_seconds=settings.request_timeout_seconds,
            runtime_root=settings.runtime_root,
            vision_base_url=settings.vision_base_url,
            vision_model=settings.vision_model,
            vision_timeout_seconds=settings.vision_timeout_seconds,
            vision_api_key_masked=mask_secret(settings.vision_api_key),
            vision_api_key_configured=bool(settings.vision_api_key.strip()),
        )

    def _serialize_settings(self, settings: Settings) -> dict[str, str]:
        return {
            "REQUEST_TIMEOUT_SECONDS": serialize_env_value(settings.request_timeout_seconds),
            "RUNTIME_ROOT": serialize_env_value(settings.runtime_root),
            "VISION_API_KEY": serialize_env_value(settings.vision_api_key.strip()),
            "VISION_BASE_URL": serialize_env_value(settings.vision_base_url),
            "VISION_MODEL": serialize_env_value(settings.vision_model),
            "VISION_TIMEOUT_SECONDS": serialize_env_value(settings.vision_timeout_seconds),
        }

    def _write_env_values(self, values: dict[str, str]) -> None:
        existing_lines = []
        if self.env_path.exists():
            existing_lines = self.env_path.read_text(encoding="utf-8").splitlines()

        updated_lines: list[str] = []
        seen_keys: set[str] = set()
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                updated_lines.append(line)
                continue

            key, _, _ = line.partition("=")
            key = key.strip()
            if key in values:
                updated_lines.append(f"{key}={values[key]}")
                seen_keys.add(key)
                continue
            updated_lines.append(line)

        for key in SETTINGS_ENV_KEYS:
            if key not in seen_keys:
                updated_lines.append(f"{key}={values[key]}")

        self.env_path.write_text("\n".join(updated_lines).rstrip() + "\n", encoding="utf-8")


async def validate_vision_settings(settings: Settings) -> None:
    api_key = settings.require_vision_api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    url = settings.vision_base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(base_url=url, timeout=settings.effective_vision_timeout_seconds) as client:
            response = await client.get("/models", headers=headers)
    except httpx.TimeoutException as exc:
        raise SettingsValidationError("连接视觉服务超时，请检查地址和超时配置。") from exc
    except httpx.HTTPError as exc:
        raise SettingsValidationError("无法连接视觉服务，请检查地址或网络。") from exc

    if response.status_code in {401, 403}:
        raise SettingsValidationError("视觉服务认证失败，请检查 API Key。")
    if response.status_code >= 400:
        raise SettingsValidationError(
            f"视觉服务返回 HTTP {response.status_code}，请检查接口地址、模型权限或网关状态。"
        )
