from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


class Settings(BaseSettings):
    request_timeout_seconds: float = Field(default=90, alias="REQUEST_TIMEOUT_SECONDS")
    runtime_root: str = Field(default=".runtime", alias="RUNTIME_ROOT")
    vision_api_key: str = Field(default="", alias="VISION_API_KEY")
    vision_base_url: str = Field(default="https://api.siliconflow.cn/v1", alias="VISION_BASE_URL")
    vision_model: str = Field(default="Qwen/Qwen3-VL-32B-Instruct", alias="VISION_MODEL")
    vision_timeout_seconds: float | None = Field(default=None, alias="VISION_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    @property
    def runtime_root_path(self) -> Path:
        return Path(self.runtime_root).expanduser().resolve()

    @property
    def effective_vision_timeout_seconds(self) -> float:
        return self.vision_timeout_seconds or self.request_timeout_seconds

    def require_vision_api_key(self) -> str:
        value = self.vision_api_key.strip()
        if not value:
            raise ConfigurationError("缺少 VISION_API_KEY，请先在 .env 或系统环境变量中配置后再启动服务。")
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
