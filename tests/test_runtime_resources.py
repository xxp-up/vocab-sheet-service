from __future__ import annotations

import io
import shutil
import uuid
from pathlib import Path

import pytest

from app.services import runtime_resources
from app.services.runtime_resources import ResourceBootstrapError, _download_file


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def _make_test_dir() -> Path:
    root = Path("D:/workspace/vocab-sheet-service/.runtime/test-runtime-resources") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_download_file_retries_and_succeeds(monkeypatch):
    attempts = {"count": 0}

    def fake_urlopen(request, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TimeoutError("timed out")
        return _FakeResponse(b"ok")

    monkeypatch.setattr(runtime_resources.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runtime_resources.time, "sleep", lambda seconds: None)

    root = _make_test_dir()
    try:
        target = root / "model.zip"
        _download_file("https://example.test/model.zip", target, 1)

        assert attempts["count"] == 2
        assert target.read_bytes() == b"ok"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_download_file_exposes_root_cause(monkeypatch):
    def fake_urlopen(request, timeout):
        raise TimeoutError("timed out")

    monkeypatch.setattr(runtime_resources.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(runtime_resources.time, "sleep", lambda seconds: None)

    root = _make_test_dir()
    try:
        target = root / "model.zip"
        with pytest.raises(ResourceBootstrapError) as excinfo:
            _download_file("https://example.test/model.zip", target, 1)

        message = str(excinfo.value)
        assert "model.zip" in message
        assert "TimeoutError" in message
        assert "timed out" in message
    finally:
        shutil.rmtree(root, ignore_errors=True)
