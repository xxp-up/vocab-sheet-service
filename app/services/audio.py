from __future__ import annotations

import asyncio
import json
import mimetypes
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx

from app.models.settings import Settings
from app.services.runtime_resources import ResourceBootstrapError, ensure_speech_runtime
from app.utils.text import collapse_whitespace, extract_candidate_words, merge_words


DEFAULT_FEEDBACK_TRANSCRIPTION_MODEL = "FunAudioLLM/SenseVoiceSmall"


class AudioServiceError(RuntimeError):
    """Raised when speech recognition fails."""


class UnsupportedAudioFormatError(AudioServiceError):
    """Raised when the input audio file cannot be decoded."""


@dataclass(slots=True)
class AudioTranscriptionResult:
    transcript_text: str
    candidate_words: list[str]


class AudioService:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    async def extract_words(self, audio_path: Path | None, hints: list[str] | None = None) -> list[str]:
        if audio_path is None:
            return []
        result = await asyncio.to_thread(self._transcribe_sync, audio_path, hints or [], "english")
        return result.candidate_words

    async def transcribe_audio(self, audio_path: Path | None, hints: list[str] | None = None) -> AudioTranscriptionResult:
        if audio_path is None:
            return AudioTranscriptionResult(transcript_text="", candidate_words=[])
        return await asyncio.to_thread(self._transcribe_sync, audio_path, hints or [], "english")

    async def transcribe_feedback_audio(self, audio_path: Path | None) -> AudioTranscriptionResult:
        if audio_path is None:
            return AudioTranscriptionResult(transcript_text="", candidate_words=[])

        if self.settings.vision_api_key.strip():
            try:
                return await self._transcribe_feedback_audio_remote(audio_path)
            except AudioServiceError:
                pass

        return await asyncio.to_thread(self._transcribe_sync, audio_path, [], "chinese")

    def _transcribe_sync(
        self,
        audio_path: Path,
        hints: list[str],
        speech_model: str,
    ) -> AudioTranscriptionResult:
        try:
            _, model_path = ensure_speech_runtime(
                self.settings.runtime_root_path,
                self.settings.request_timeout_seconds,
                speech_model=speech_model,
            )
            import av
            import vosk
        except ResourceBootstrapError as exc:
            raise AudioServiceError(str(exc)) from exc
        except Exception as exc:
            raise AudioServiceError("本地语音识别运行环境加载失败。") from exc

        try:
            vosk.SetLogLevel(-1)
            grammar = _build_vosk_grammar(hints) if speech_model == "english" else None
            model = _load_vosk_model(str(model_path))
            recognizer = (
                vosk.KaldiRecognizer(model, 16000.0, grammar)
                if grammar
                else vosk.KaldiRecognizer(model, 16000.0)
            )
            recognizer.SetWords(True)
            text_parts: list[str] = []

            with audio_path.open("rb") as audio_handle:
                container = av.open(audio_handle)
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

        transcript_text = _normalize_transcript_text(" ".join(part.strip() for part in text_parts if part.strip()))
        return AudioTranscriptionResult(
            transcript_text=transcript_text,
            candidate_words=merge_words(extract_candidate_words(transcript_text)),
        )

    async def _transcribe_feedback_audio_remote(self, audio_path: Path) -> AudioTranscriptionResult:
        headers = {"Authorization": f"Bearer {self.settings.require_vision_api_key()}"}
        media_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"

        try:
            async with httpx.AsyncClient(
                base_url=self.settings.vision_base_url.rstrip("/"),
                timeout=self.settings.effective_vision_timeout_seconds,
                transport=self.transport,
            ) as client:
                with audio_path.open("rb") as audio_handle:
                    response = await client.post(
                        "/audio/transcriptions",
                        headers=headers,
                        data={"model": DEFAULT_FEEDBACK_TRANSCRIPTION_MODEL},
                        files={"file": (audio_path.name, audio_handle, media_type)},
                    )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise AudioServiceError("课后反馈音频转写超时，请稍后重试。") from exc
        except httpx.HTTPStatusError as exc:
            raise AudioServiceError(
                f"课后反馈音频转写失败，服务返回 HTTP {exc.response.status_code}。"
            ) from exc
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise AudioServiceError("课后反馈音频转写服务返回了无法解析的结果。") from exc

        transcript_text = _normalize_transcript_text(str(data.get("text", "")))
        if not transcript_text:
            raise AudioServiceError("课后反馈音频未识别到可用内容。")

        return AudioTranscriptionResult(
            transcript_text=transcript_text,
            candidate_words=merge_words(extract_candidate_words(transcript_text)),
        )


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


@lru_cache(maxsize=4)
def _load_vosk_model(model_path: str):
    import vosk

    return vosk.Model(model_path=model_path)


def _normalize_transcript_text(text: str) -> str:
    normalized = collapse_whitespace(text)
    normalized = re.sub(r"<\|[^>]+\|>", "", normalized)
    normalized = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", normalized)
    return collapse_whitespace(normalized)
