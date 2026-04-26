from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path


BOOTSTRAP_LOCK = threading.Lock()
USER_AGENT = "vocab-sheet-service/0.1"
DOWNLOAD_RETRY_ATTEMPTS = 3
DOWNLOAD_RETRY_DELAY_SECONDS = 1.0

VOSK_MODEL_NAME = "vosk-model-small-en-us-0.15"
VOSK_MODEL_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"


class ResourceBootstrapError(RuntimeError):
    """Raised when local free resources cannot be prepared."""


@dataclass(frozen=True, slots=True)
class WheelSpec:
    package: str
    version: str
    filename_suffix: str
    marker_path: str


LEXICON_WHEELS = (
    WheelSpec("cmudict", "1.1.3", "py3-none-any.whl", "cmudict/data/cmudict.dict"),
    WheelSpec("cedict", "0.1.0", "py3-none-any.whl", "cedict/db/words.db"),
)

SPEECH_WHEELS = (
    WheelSpec("av", "16.0.1", "cp312-cp312-win_amd64.whl", "av/__init__.py"),
    WheelSpec("cffi", "2.0.0", "cp312-cp312-win_amd64.whl", "_cffi_backend.cp312-win_amd64.pyd"),
    WheelSpec("vosk", "0.3.45", "py3-none-win_amd64.whl", "vosk/__init__.py"),
    WheelSpec("requests", "2.33.1", "py3-none-any.whl", "requests/__init__.py"),
    WheelSpec("urllib3", "2.6.3", "py3-none-any.whl", "urllib3/__init__.py"),
    WheelSpec("certifi", "2026.2.25", "py3-none-any.whl", "certifi/__init__.py"),
    WheelSpec("idna", "3.12", "py3-none-any.whl", "idna/__init__.py"),
    WheelSpec("charset-normalizer", "3.4.7", "cp312-cp312-win_amd64.whl", "charset_normalizer/__init__.py"),
    WheelSpec("tqdm", "4.67.3", "py3-none-any.whl", "tqdm/__init__.py"),
)


def ensure_lexicon_resources(runtime_root: Path, timeout_seconds: float) -> tuple[Path, Path]:
    resource_root = runtime_root / "bootstrap" / "lexicon"
    _ensure_wheels(resource_root, LEXICON_WHEELS, timeout_seconds)

    cmudict_path = resource_root / "cmudict" / "data" / "cmudict.dict"
    cedict_db_path = resource_root / "cedict" / "db" / "words.db"
    if not cmudict_path.exists() or not cedict_db_path.exists():
        raise ResourceBootstrapError("Free lexicon resources could not be prepared.")
    return cmudict_path, cedict_db_path


def ensure_speech_runtime(runtime_root: Path, timeout_seconds: float) -> tuple[Path, Path]:
    bootstrap_root = runtime_root / "bootstrap"
    vendor_root = bootstrap_root / "vendor"
    _ensure_wheels(vendor_root, SPEECH_WHEELS, timeout_seconds)
    _ensure_srt_stub(vendor_root)
    _ensure_sys_path(vendor_root)

    model_root = bootstrap_root / "models"
    model_path = model_root / VOSK_MODEL_NAME
    archive_path = model_root / f"{VOSK_MODEL_NAME}.zip"

    with BOOTSTRAP_LOCK:
        if not model_path.exists():
            model_root.mkdir(parents=True, exist_ok=True)
            _download_file(VOSK_MODEL_URL, archive_path, timeout_seconds)
            try:
                shutil.rmtree(model_path, ignore_errors=True)
                with zipfile.ZipFile(archive_path) as archive:
                    archive.extractall(model_root)
            except zipfile.BadZipFile as exc:
                archive_path.unlink(missing_ok=True)
                shutil.rmtree(model_path, ignore_errors=True)
                raise ResourceBootstrapError("The Vosk model archive is corrupt and could not be extracted.") from exc
            except Exception as exc:
                shutil.rmtree(model_path, ignore_errors=True)
                raise ResourceBootstrapError(
                    f"Failed to extract the Vosk model: {_describe_exception(exc)}"
                ) from exc

    if not model_path.exists():
        raise ResourceBootstrapError("The Vosk model could not be prepared.")
    return vendor_root, model_path


def _ensure_wheels(extract_root: Path, specs: tuple[WheelSpec, ...], timeout_seconds: float) -> None:
    wheel_cache = extract_root.parent / "wheel-cache"
    with BOOTSTRAP_LOCK:
        extract_root.mkdir(parents=True, exist_ok=True)
        wheel_cache.mkdir(parents=True, exist_ok=True)

        for spec in specs:
            marker = extract_root / spec.marker_path
            if marker.exists():
                continue

            wheel_path = _download_wheel(spec, wheel_cache, timeout_seconds)
            try:
                with zipfile.ZipFile(wheel_path) as archive:
                    archive.extractall(extract_root)
            except zipfile.BadZipFile as exc:
                raise ResourceBootstrapError(
                    f"The {spec.package} wheel is corrupt and could not be extracted."
                ) from exc


def _download_wheel(spec: WheelSpec, wheel_cache: Path, timeout_seconds: float) -> Path:
    json_url = f"https://pypi.org/pypi/{spec.package}/{spec.version}/json"
    request = urllib.request.Request(json_url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
    except Exception as exc:
        raise ResourceBootstrapError(
            f"Could not fetch release metadata for {spec.package}: {_describe_exception(exc)}"
        ) from exc

    file_info = next(
        (item for item in payload.get("urls", []) if item.get("filename", "").endswith(spec.filename_suffix)),
        None,
    )
    if file_info is None:
        raise ResourceBootstrapError(f"Could not find a compatible wheel for {spec.package}.")

    target = wheel_cache / file_info["filename"]
    if target.exists():
        return target

    _download_file(str(file_info["url"]), target, timeout_seconds)
    return target


def _download_file(url: str, target: Path, timeout_seconds: float) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    temp_path = target.with_suffix(target.suffix + ".tmp")

    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                with temp_path.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            temp_path.replace(target)
            return
        except Exception as exc:
            last_error = exc
            temp_path.unlink(missing_ok=True)
            if attempt < DOWNLOAD_RETRY_ATTEMPTS:
                time.sleep(DOWNLOAD_RETRY_DELAY_SECONDS * attempt)

    message = _describe_exception(last_error) if last_error is not None else "unknown error"
    raise ResourceBootstrapError(f"Resource download failed: {target.name} ({message})") from last_error


def _ensure_srt_stub(vendor_root: Path) -> None:
    srt_path = vendor_root / "srt.py"
    if srt_path.exists():
        return

    srt_path.write_text(
        "class Subtitle:\n"
        "    def __init__(self, *args, **kwargs):\n"
        "        self.args = args\n"
        "        self.kwargs = kwargs\n\n"
        "def compose(subtitles):\n"
        "    return \"\"\n",
        encoding="utf-8",
    )


def _ensure_sys_path(path: Path) -> None:
    path_str = str(path.resolve())
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _describe_exception(exc: Exception | None) -> str:
    if exc is None:
        return "unknown error"

    text = str(exc).strip()
    if not text:
        text = repr(exc)
    return f"{exc.__class__.__name__}: {text}"
