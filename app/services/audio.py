from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from pathlib import Path

from app.models.settings import Settings
from app.services.runtime_resources import ResourceBootstrapError, ensure_speech_runtime
from app.utils.text import extract_candidate_words, merge_words


class AudioServiceError(RuntimeError):
    """Raised when local speech recognition fails."""


class UnsupportedAudioFormatError(AudioServiceError):
    """Raised when the input audio file cannot be decoded locally."""


class AudioService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract_words(self, audio_path: Path | None, hints: list[str] | None = None) -> list[str]:
        if audio_path is None:
            return []
        return await asyncio.to_thread(self._extract_words_sync, audio_path, hints or [])

    def _extract_words_sync(self, audio_path: Path, hints: list[str]) -> list[str]:
        try:
            _, model_path = ensure_speech_runtime(
                self.settings.runtime_root_path,
                self.settings.request_timeout_seconds,
            )
            import av
            import vosk
        except ResourceBootstrapError as exc:
            raise AudioServiceError(str(exc)) from exc
        except Exception as exc:
            raise AudioServiceError("本地语音识别运行环境加载失败。") from exc

        try:
            vosk.SetLogLevel(-1)
            grammar = _build_vosk_grammar(hints)
            model = _load_vosk_model(str(model_path))
            recognizer = (
                vosk.KaldiRecognizer(model, 16000.0, grammar)
                if grammar
                else vosk.KaldiRecognizer(model, 16000.0)
            )
            recognizer.SetWords(True)
            text_parts: list[str] = []

            container = av.open(str(audio_path))
            try:
                stream = next((item for item in container.streams if item.type == "audio"), None)
                if stream is None:
                    raise UnsupportedAudioFormatError("音频文件中没有可识别的音轨。")
                resampler = av.audio.resampler.AudioResampler(format="s16", layout="mono", rate=16000)
                for frame in container.decode(stream):
                    for chunk in _resample_frame(resampler, frame):
                        if recognizer.AcceptWaveform(chunk):
                            text = json.loads(recognizer.Result()).get("text", "")
                            if text:
                                text_parts.append(text)
                final_text = json.loads(recognizer.FinalResult()).get("text", "")
                if final_text:
                    text_parts.append(final_text)
            finally:
                container.close()
        except UnsupportedAudioFormatError:
            raise
        except av.error.FFmpegError as exc:
            raise UnsupportedAudioFormatError("本地免费语音识别暂时无法解码该音频格式。") from exc
        except Exception as exc:
            raise AudioServiceError("本地免费语音识别失败。") from exc

        return merge_words(extract_candidate_words(" ".join(text_parts)))


def _resample_frame(resampler, frame) -> list[bytes]:
    result = resampler.resample(frame)
    if result is None:
        return []
    frames = result if isinstance(result, list) else [result]
    return [bytes(item.planes[0]) for item in frames if item is not None and item.planes]


def _build_vosk_grammar(hints: list[str]) -> str | None:
    candidates = merge_words(hints)
    if not candidates:
        return None
    limited = [word.lower() for word in candidates[:256]]
    if "[unk]" not in limited:
        limited.append("[unk]")
    return json.dumps(limited, ensure_ascii=False)


@lru_cache(maxsize=2)
def _load_vosk_model(model_path: str):
    import vosk

    return vosk.Model(model_path=model_path)
