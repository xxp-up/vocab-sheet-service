from __future__ import annotations

import pytest

from app.models.settings import ConfigurationError, Settings


def test_require_vision_api_key_returns_trimmed_value() -> None:
    settings = Settings(vision_api_key="  test-key  ")

    assert settings.require_vision_api_key() == "test-key"


def test_require_vision_api_key_rejects_blank_value() -> None:
    settings = Settings(vision_api_key="   ")

    with pytest.raises(ConfigurationError) as excinfo:
        settings.require_vision_api_key()

    assert "VISION_API_KEY" in str(excinfo.value)
