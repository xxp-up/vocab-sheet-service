from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import shutil
import uuid

from fastapi import HTTPException, UploadFile

from app.models.schemas import FeedbackDraftSection, FeedbackJobStatusResponse, JobCreatedResponse, VocabJobStatusResponse
from app.models.settings import Settings
from app.services.audio import AudioService, AudioServiceError, UnsupportedAudioFormatError
from app.services.feedback import FeedbackGenerationError, FeedbackService
from app.services.pipeline import PipelineContentError, PipelineService
from app.services.vision import VisionServiceError


VOCAB_JOB_STAGES = {
    "queued": (0, "等待开始"),
    "upload_validation": (5, "上传校验"),
    "document_parsing": (25, "教材解析"),
    "merge_candidates": (45, "音频/补词合并"),
    "lexicon_enrichment": (65, "词典补全"),
    "sentence_matching": (85, "例句定位"),
    "workbook_writing": (95, "模板写入"),
    "download_ready": (100, "准备下载"),
}

FEEDBACK_JOB_STAGES = {
    "queued": (0, "等待开始"),
    "source_preparing": (15, "整理源材料"),
    "audio_transcribing": (45, "音频转写"),
    "draft_generating": (75, "生成反馈草稿"),
    "draft_ready": (100, "草稿可编辑"),
}

ACTIVE_JOB_STATUSES = {"queued", "processing"}


@dataclass(slots=True)
class VocabJobRecord:
    job_id: str
    workdir: Path
    teaching_path: Path
    audio_path: Path | None
    words_text: str | None
    output_path: Path
    output_filename: str
    status: str = "queued"
    progress_percent: int = 0
    stage_code: str = "queued"
    stage_label: str = "等待开始"
    rows_written: int = 0
    skipped_words: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_created_response(self) -> JobCreatedResponse:
        return JobCreatedResponse(
            job_id=self.job_id,
            status=self.status,
            progress_percent=self.progress_percent,
            stage_code=self.stage_code,
            stage_label=self.stage_label,
        )

    def to_status_response(self) -> VocabJobStatusResponse:
        download_url = None
        if self.status == "completed" and self.output_path.exists():
            download_url = f"/v1/vocab/jobs/{self.job_id}/download"
        return VocabJobStatusResponse(
            job_id=self.job_id,
            status=self.status,
            progress_percent=self.progress_percent,
            stage_code=self.stage_code,
            stage_label=self.stage_label,
            rows_written=self.rows_written,
            skipped_words=dict(self.skipped_words),
            error_message=self.error_message,
            download_url=download_url,
            output_filename=self.output_filename,
        )


@dataclass(slots=True)
class FeedbackJobRecord:
    job_id: str
    workdir: Path
    lesson_date: date
    lesson_index: int
    class_name: str | None
    audio_path: Path | None
    transcript_text: str
    status: str = "queued"
    progress_percent: int = 0
    stage_code: str = "queued"
    stage_label: str = "等待开始"
    draft_sections: list[FeedbackDraftSection] = field(default_factory=list)
    composed_text: str = ""
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_created_response(self) -> JobCreatedResponse:
        return JobCreatedResponse(
            job_id=self.job_id,
            status=self.status,
            progress_percent=self.progress_percent,
            stage_code=self.stage_code,
            stage_label=self.stage_label,
        )

    def to_status_response(self) -> FeedbackJobStatusResponse:
        return FeedbackJobStatusResponse(
            job_id=self.job_id,
            status=self.status,
            progress_percent=self.progress_percent,
            stage_code=self.stage_code,
            stage_label=self.stage_label,
            draft_sections=list(self.draft_sections),
            composed_text=self.composed_text,
            transcript_text=self.transcript_text,
            error_message=self.error_message,
        )


class JobStore:
    def __init__(self, retention_hours: int = 2) -> None:
        self.retention = timedelta(hours=retention_hours)
        self.vocab_jobs: dict[str, VocabJobRecord] = {}
        self.feedback_jobs: dict[str, FeedbackJobRecord] = {}
        self._lock = asyncio.Lock()

    async def has_running_jobs(self) -> bool:
        await self._cleanup_expired_jobs()
        async with self._lock:
            return any(record.status in ACTIVE_JOB_STATUSES for record in self.vocab_jobs.values()) or any(
                record.status in ACTIVE_JOB_STATUSES for record in self.feedback_jobs.values()
            )

    async def create_vocab_job(
        self,
        *,
        settings: Settings,
        pipeline: PipelineService,
        teaching_file: UploadFile,
        audio_file: UploadFile | None,
        words_text: str | None,
    ) -> JobCreatedResponse:
        await self._cleanup_expired_jobs()
        job_id = uuid.uuid4().hex
        workdir = settings.runtime_root_path / "jobs" / f"vocab-{job_id}"
        workdir.mkdir(parents=True, exist_ok=True)
        teaching_path = await _save_upload(teaching_file, workdir)
        audio_path = await _save_optional_upload(audio_file, workdir)
        output_filename = f"{teaching_path.stem}_filled.xlsx"
        record = VocabJobRecord(
            job_id=job_id,
            workdir=workdir,
            teaching_path=teaching_path,
            audio_path=audio_path,
            words_text=words_text,
            output_path=workdir / output_filename,
            output_filename=output_filename,
        )
        async with self._lock:
            self.vocab_jobs[job_id] = record

        asyncio.create_task(self._run_vocab_job(record, pipeline))
        return record.to_created_response()

    async def create_feedback_job(
        self,
        *,
        settings: Settings,
        feedback_service: FeedbackService,
        audio_service: AudioService,
        lesson_date: date,
        lesson_index: int,
        class_name: str | None,
        audio_file: UploadFile | None,
        transcript_text: str | None,
    ) -> JobCreatedResponse:
        await self._cleanup_expired_jobs()
        transcript = (transcript_text or "").strip()
        if not transcript and (audio_file is None or not (audio_file.filename or "").strip()):
            raise HTTPException(status_code=400, detail="请提供课堂音频或逐字稿文本。")

        job_id = uuid.uuid4().hex
        workdir = settings.runtime_root_path / "jobs" / f"feedback-{job_id}"
        workdir.mkdir(parents=True, exist_ok=True)
        audio_path = await _save_optional_upload(audio_file, workdir)
        record = FeedbackJobRecord(
            job_id=job_id,
            workdir=workdir,
            lesson_date=lesson_date,
            lesson_index=lesson_index,
            class_name=class_name,
            audio_path=audio_path,
            transcript_text=transcript,
        )
        async with self._lock:
            self.feedback_jobs[job_id] = record

        asyncio.create_task(self._run_feedback_job(record, feedback_service, audio_service))
        return record.to_created_response()

    async def get_vocab_job(self, job_id: str) -> VocabJobStatusResponse:
        await self._cleanup_expired_jobs()
        async with self._lock:
            record = self.vocab_jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="未找到对应的教材题词任务。")
        return record.to_status_response()

    async def get_feedback_job(self, job_id: str) -> FeedbackJobStatusResponse:
        await self._cleanup_expired_jobs()
        async with self._lock:
            record = self.feedback_jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="未找到对应的课后反馈任务。")
        return record.to_status_response()

    async def regenerate_feedback_section(
        self,
        *,
        job_id: str,
        section_key: str,
        feedback_service: FeedbackService,
        draft_sections: list[FeedbackDraftSection] | None = None,
    ) -> FeedbackDraftSection:
        await self._cleanup_expired_jobs()
        async with self._lock:
            record = self.feedback_jobs.get(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="未找到对应的课后反馈任务。")
        if record.status != "completed":
            raise HTTPException(status_code=409, detail="当前任务尚未生成可编辑的反馈草稿。")

        section = await feedback_service.regenerate_section(
            section_key=section_key,
            transcript_text=record.transcript_text,
            lesson_date=record.lesson_date,
            lesson_index=record.lesson_index,
            class_name=record.class_name,
            draft_sections=draft_sections or list(record.draft_sections),
        )

        async with self._lock:
            current = self.feedback_jobs.get(job_id)
            if current is None:
                raise HTTPException(status_code=404, detail="未找到对应的课后反馈任务。")
            current.draft_sections = _replace_feedback_section(current.draft_sections, section)
            current.composed_text = "\n\n".join(
                f"{item.title}\n{item.content}".strip() for item in current.draft_sections
            )
            current.updated_at = datetime.now(timezone.utc)
        return section

    async def get_vocab_download(self, job_id: str) -> tuple[Path, str]:
        status = await self.get_vocab_job(job_id)
        if status.status != "completed" or not status.download_url:
            raise HTTPException(status_code=409, detail="当前任务尚未生成可下载文件。")
        async with self._lock:
            record = self.vocab_jobs[job_id]
        return record.output_path, record.output_filename

    async def _run_vocab_job(self, record: VocabJobRecord, pipeline: PipelineService) -> None:
        await self._set_vocab_stage(record.job_id, status="processing", stage_code="upload_validation")
        try:
            result = await pipeline.process(
                teaching_path=record.teaching_path,
                output_path=record.output_path,
                audio_path=record.audio_path,
                words_text=record.words_text,
                progress_callback=lambda code, percent, label: self._update_vocab_progress(
                    record.job_id,
                    stage_code=code,
                    progress_percent=percent,
                    stage_label=label,
                ),
            )
        except PipelineContentError as exc:
            message = exc.detail.get("message", "处理失败")
            skipped_words = exc.detail.get("skipped_words", {}) if isinstance(exc.detail, dict) else {}
            await self._fail_vocab_job(record.job_id, str(message), skipped_words if isinstance(skipped_words, dict) else {})
            return
        except UnsupportedAudioFormatError as exc:
            await self._fail_vocab_job(record.job_id, str(exc))
            return
        except (AudioServiceError, VisionServiceError, Exception) as exc:
            await self._fail_vocab_job(record.job_id, str(exc))
            return

        async with self._lock:
            current = self.vocab_jobs.get(record.job_id)
            if current is None:
                return
            current.status = "completed"
            current.progress_percent = 100
            current.stage_code = "download_ready"
            current.stage_label = "准备下载"
            current.rows_written = result.rows_written
            current.skipped_words = dict(result.skipped_words)
            current.updated_at = datetime.now(timezone.utc)

    async def _run_feedback_job(
        self,
        record: FeedbackJobRecord,
        feedback_service: FeedbackService,
        audio_service: AudioService,
    ) -> None:
        await self._set_feedback_stage(record.job_id, status="processing", stage_code="source_preparing")
        try:
            manual_transcript_text = record.transcript_text.strip()
            audio_transcript_text = ""
            if record.audio_path is not None:
                await self._set_feedback_stage(record.job_id, status="processing", stage_code="audio_transcribing")
                transcription = await audio_service.transcribe_feedback_audio(record.audio_path)
                audio_transcript_text = transcription.transcript_text.strip()

            transcript_text = _compose_feedback_source_text(
                audio_transcript_text=audio_transcript_text,
                manual_transcript_text=manual_transcript_text,
            )
            source_kind = _resolve_feedback_source_kind(
                audio_transcript_text=audio_transcript_text,
                manual_transcript_text=manual_transcript_text,
            )

            if not transcript_text.strip():
                raise FeedbackGenerationError("音频中未识别到可生成反馈的课堂内容。")

            await self._set_feedback_stage(record.job_id, status="processing", stage_code="draft_generating")
            draft = await feedback_service.generate_draft(
                transcript_text=transcript_text,
                lesson_date=record.lesson_date,
                lesson_index=record.lesson_index,
                class_name=record.class_name,
                source_kind=source_kind,
            )
        except (FeedbackGenerationError, AudioServiceError, UnsupportedAudioFormatError) as exc:
            await self._fail_feedback_job(record.job_id, str(exc))
            return
        except Exception as exc:
            await self._fail_feedback_job(record.job_id, str(exc))
            return

        async with self._lock:
            current = self.feedback_jobs.get(record.job_id)
            if current is None:
                return
            current.status = "completed"
            current.progress_percent = 100
            current.stage_code = "draft_ready"
            current.stage_label = "草稿可编辑"
            current.draft_sections = list(draft.draft_sections)
            current.composed_text = draft.composed_text
            current.transcript_text = draft.transcript_text
            current.updated_at = datetime.now(timezone.utc)

    async def _set_vocab_stage(self, job_id: str, *, status: str, stage_code: str) -> None:
        progress_percent, stage_label = VOCAB_JOB_STAGES[stage_code]
        await self._update_vocab_progress(
            job_id,
            status=status,
            stage_code=stage_code,
            progress_percent=progress_percent,
            stage_label=stage_label,
        )

    async def _set_feedback_stage(self, job_id: str, *, status: str, stage_code: str) -> None:
        progress_percent, stage_label = FEEDBACK_JOB_STAGES[stage_code]
        await self._update_feedback_progress(
            job_id,
            status=status,
            stage_code=stage_code,
            progress_percent=progress_percent,
            stage_label=stage_label,
        )

    async def _update_vocab_progress(
        self,
        job_id: str,
        *,
        stage_code: str,
        progress_percent: int,
        stage_label: str,
        status: str | None = None,
    ) -> None:
        async with self._lock:
            record = self.vocab_jobs.get(job_id)
            if record is None:
                return
            if status is not None:
                record.status = status
            record.stage_code = stage_code
            record.stage_label = stage_label
            record.progress_percent = progress_percent
            record.updated_at = datetime.now(timezone.utc)

    async def _update_feedback_progress(
        self,
        job_id: str,
        *,
        stage_code: str,
        progress_percent: int,
        stage_label: str,
        status: str | None = None,
    ) -> None:
        async with self._lock:
            record = self.feedback_jobs.get(job_id)
            if record is None:
                return
            if status is not None:
                record.status = status
            record.stage_code = stage_code
            record.stage_label = stage_label
            record.progress_percent = progress_percent
            record.updated_at = datetime.now(timezone.utc)

    async def _fail_vocab_job(self, job_id: str, message: str, skipped_words: dict[str, str] | None = None) -> None:
        async with self._lock:
            record = self.vocab_jobs.get(job_id)
            if record is None:
                return
            record.status = "failed"
            record.stage_code = "failed"
            record.stage_label = "处理失败"
            record.error_message = message
            record.skipped_words = skipped_words or record.skipped_words
            record.updated_at = datetime.now(timezone.utc)

    async def _fail_feedback_job(self, job_id: str, message: str) -> None:
        async with self._lock:
            record = self.feedback_jobs.get(job_id)
            if record is None:
                return
            record.status = "failed"
            record.stage_code = "failed"
            record.stage_label = "处理失败"
            record.error_message = message
            record.updated_at = datetime.now(timezone.utc)

    async def _cleanup_expired_jobs(self) -> None:
        cutoff = datetime.now(timezone.utc) - self.retention
        stale_dirs: list[Path] = []
        async with self._lock:
            for mapping in (self.vocab_jobs, self.feedback_jobs):
                stale_ids = [job_id for job_id, record in mapping.items() if record.updated_at < cutoff]
                for job_id in stale_ids:
                    stale_dirs.append(mapping[job_id].workdir)
                    del mapping[job_id]

        for path in stale_dirs:
            shutil.rmtree(path, ignore_errors=True)


def _resolve_feedback_source_kind(*, audio_transcript_text: str, manual_transcript_text: str) -> str:
    if audio_transcript_text and manual_transcript_text:
        return "mixed"
    if audio_transcript_text:
        return "audio"
    return "manual"


def _compose_feedback_source_text(*, audio_transcript_text: str, manual_transcript_text: str) -> str:
    audio_text = audio_transcript_text.strip()
    manual_text = manual_transcript_text.strip()
    if audio_text and manual_text:
        return (
            "【合并要求】\n"
            "请同时参考课堂音频转写和老师补充笔记：音频用于还原真实课堂内容，补充笔记用于校正和补充重点、作业、学生表现。\n\n"
            "【课堂音频转写】\n"
            f"{audio_text}\n\n"
            "【老师补充笔记 / 逐字稿】\n"
            f"{manual_text}"
        ).strip()
    return audio_text or manual_text


def _replace_feedback_section(
    existing_sections: list[FeedbackDraftSection],
    next_section: FeedbackDraftSection,
) -> list[FeedbackDraftSection]:
    replaced = False
    updated_sections: list[FeedbackDraftSection] = []
    for section in existing_sections:
        if section.key == next_section.key:
            updated_sections.append(next_section)
            replaced = True
        else:
            updated_sections.append(section)
    if not replaced:
        updated_sections.append(next_section)
    return updated_sections


async def _save_upload(upload: UploadFile | None, workdir: Path) -> Path:
    if upload is None:
        raise ValueError("缺少上传文件")

    filename = Path(upload.filename or "upload.bin").name
    target = workdir / filename
    with target.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            handle.write(chunk)
    await upload.close()
    return target


async def _save_optional_upload(upload: UploadFile | None, workdir: Path) -> Path | None:
    if upload is None:
        return None
    if not (upload.filename or "").strip():
        await upload.close()
        return None
    return await _save_upload(upload, workdir)
