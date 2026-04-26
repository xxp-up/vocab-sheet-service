from __future__ import annotations

from datetime import date
import json
import logging
from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

from app.models.schemas import (
    AudioTranscriptionResponse,
    FeedbackJobStatusResponse,
    FillSummary,
    HealthResponse,
    JobCreatedResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    SettingsValidateResponse,
    VocabJobStatusResponse,
)
from app.models.settings import ConfigurationError, Settings, get_settings
from app.services.audio import AudioService, AudioServiceError, UnsupportedAudioFormatError
from app.services.document.service import DocumentService, UnsupportedDocumentError
from app.services.exercise_restore import ExerciseRestoreService
from app.services.feedback import FeedbackService
from app.services.jobs import JobStore
from app.services.lexicon import LexiconService, LexiconServiceError
from app.services.pipeline import PipelineContentError, PipelineService
from app.services.settings_manager import SettingsManager, SettingsValidationError
from app.services.vision import VisionServiceError
from app.services.workbook import WorkbookService, WorkbookTemplateError


router = APIRouter()
logger = logging.getLogger("vocab_sheet_service.api")

INDEX_HTML_PATH = Path(__file__).resolve().parents[1] / "web" / "index.html"
JOB_STORE = JobStore()
SETTINGS_MANAGER = SettingsManager()


def build_pipeline(settings: Settings) -> PipelineService:
    return PipelineService(
        lexicon_service=LexiconService(settings),
        document_service=DocumentService(settings),
        audio_service=AudioService(settings),
        exercise_restore_service=ExerciseRestoreService(settings),
        workbook_service=WorkbookService(),
    )


def get_job_store() -> JobStore:
    return JOB_STORE


def get_settings_manager() -> SettingsManager:
    return SETTINGS_MANAGER


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse()


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML_PATH.read_text(encoding="utf-8"))


@router.post("/v1/vocab/fill", responses={200: {"content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}}})
async def fill_vocab_sheet(
    teaching_file: UploadFile = File(...),
    audio_file: UploadFile | None = File(default=None),
    words_text: str | None = Form(default=None),
    settings: Settings = Depends(get_settings),
):
    teaching_name = Path(teaching_file.filename or "upload.bin").name
    workdir: Path | None = None

    try:
        pipeline = build_pipeline(settings)
        runtime_root = settings.runtime_root_path
        runtime_root.mkdir(parents=True, exist_ok=True)
        workdir = runtime_root / f"vocab-sheet-{uuid.uuid4().hex}"
        workdir.mkdir(parents=True, exist_ok=True)

        teaching_path = await _save_upload(teaching_file, workdir)
        audio_path = await _save_optional_upload(audio_file, workdir)
        output_name = f"{teaching_path.stem}_filled.xlsx"
        output_path = workdir / output_name
        logger.info(
            "Started vocab fill request: teaching_file=%s audio_file=%s manual_words_provided=%s workdir=%s",
            teaching_path.name,
            audio_path.name if audio_path is not None else "-",
            bool((words_text or "").strip()),
            workdir.name,
        )

        result = await pipeline.process(
            teaching_path=teaching_path,
            output_path=output_path,
            audio_path=audio_path,
            words_text=words_text,
        )
        logger.info(
            "Completed vocab fill request: teaching_file=%s rows_written=%s skipped=%s output=%s",
            teaching_path.name,
            result.rows_written,
            len(result.skipped_words),
            output_name,
        )

        headers = {
            "X-Words-Written": str(result.rows_written),
            "X-Words-Skipped": str(len(result.skipped_words)),
            "X-Skipped-Reasons": json.dumps(result.skipped_words, ensure_ascii=True),
        }
        return FileResponse(
            path=result.output_path,
            filename=output_name,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=headers,
            background=BackgroundTask(_cleanup_dir, workdir),
        )
    except ConfigurationError as exc:
        _cleanup_dir(workdir)
        logger.error("Configuration error while processing %s: %s", teaching_name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except UnsupportedDocumentError as exc:
        _cleanup_dir(workdir)
        logger.warning("Unsupported teaching file for %s: %s", teaching_name, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PipelineContentError as exc:
        _cleanup_dir(workdir)
        logger.warning("Pipeline content error for %s: %s", teaching_name, exc.detail)
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except UnsupportedAudioFormatError as exc:
        _cleanup_dir(workdir)
        logger.warning("Unsupported audio file for %s: %s", teaching_name, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VisionServiceError as exc:
        _cleanup_dir(workdir)
        logger.warning("Vision upstream error for %s: %s", teaching_name, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except WorkbookTemplateError as exc:
        _cleanup_dir(workdir)
        logger.error("Workbook template error for %s: %s", teaching_name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except (AudioServiceError, LexiconServiceError) as exc:
        _cleanup_dir(workdir)
        logger.error("Local processing error for %s: %s", teaching_name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except HTTPException:
        _cleanup_dir(workdir)
        raise
    except Exception as exc:
        _cleanup_dir(workdir)
        logger.exception("Unexpected failure while processing %s", teaching_name)
        raise HTTPException(status_code=500, detail=f"处理失败: {exc}") from exc


@router.post("/v1/vocab/jobs", response_model=JobCreatedResponse)
async def create_vocab_job(
    teaching_file: UploadFile = File(...),
    audio_file: UploadFile | None = File(default=None),
    words_text: str | None = Form(default=None),
    settings: Settings = Depends(get_settings),
    job_store: JobStore = Depends(get_job_store),
) -> JobCreatedResponse:
    pipeline = build_pipeline(settings)
    return await job_store.create_vocab_job(
        settings=settings,
        pipeline=pipeline,
        teaching_file=teaching_file,
        audio_file=audio_file,
        words_text=words_text,
    )


@router.get("/v1/vocab/jobs/{job_id}", response_model=VocabJobStatusResponse)
async def get_vocab_job(job_id: str, job_store: JobStore = Depends(get_job_store)) -> VocabJobStatusResponse:
    return await job_store.get_vocab_job(job_id)


@router.get("/v1/vocab/jobs/{job_id}/download")
async def download_vocab_job(job_id: str, job_store: JobStore = Depends(get_job_store)):
    path, filename = await job_store.get_vocab_download(job_id)
    return FileResponse(
        path=path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/v1/feedback/jobs", response_model=JobCreatedResponse)
async def create_feedback_job(
    lesson_date: date = Form(...),
    lesson_index: int = Form(..., ge=1),
    class_name: str | None = Form(default=None),
    transcript_text: str | None = Form(default=None),
    audio_file: UploadFile | None = File(default=None),
    settings: Settings = Depends(get_settings),
    job_store: JobStore = Depends(get_job_store),
) -> JobCreatedResponse:
    return await job_store.create_feedback_job(
        settings=settings,
        feedback_service=FeedbackService(),
        audio_service=AudioService(settings),
        lesson_date=lesson_date,
        lesson_index=lesson_index,
        class_name=class_name,
        audio_file=audio_file,
        transcript_text=transcript_text,
    )


@router.get("/v1/feedback/jobs/{job_id}", response_model=FeedbackJobStatusResponse)
async def get_feedback_job(job_id: str, job_store: JobStore = Depends(get_job_store)) -> FeedbackJobStatusResponse:
    return await job_store.get_feedback_job(job_id)


@router.get("/v1/settings", response_model=SettingsResponse)
async def read_settings(manager: SettingsManager = Depends(get_settings_manager)) -> SettingsResponse:
    return manager.get_settings_response()


@router.put("/v1/settings", response_model=SettingsResponse)
async def update_settings(
    payload: SettingsUpdateRequest,
    manager: SettingsManager = Depends(get_settings_manager),
) -> SettingsResponse:
    return manager.update_settings(payload)


@router.post("/v1/settings/validate", response_model=SettingsValidateResponse)
async def validate_settings(
    payload: SettingsUpdateRequest,
    manager: SettingsManager = Depends(get_settings_manager),
) -> SettingsValidateResponse:
    try:
        return await manager.validate_settings(payload)
    except SettingsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/v1/audio/transcribe", response_model=AudioTranscriptionResponse)
async def transcribe_audio(
    audio_file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
) -> AudioTranscriptionResponse:
    workdir = settings.runtime_root_path / f"audio-transcribe-{uuid.uuid4().hex}"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        audio_path = await _save_upload(audio_file, workdir)
        result = await AudioService(settings).transcribe_audio(audio_path)
        return AudioTranscriptionResponse(
            transcript_text=result.transcript_text,
            candidate_words=result.candidate_words,
        )
    except UnsupportedAudioFormatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AudioServiceError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        _cleanup_dir(workdir)


@router.get("/v1/vocab/summary-example", response_model=FillSummary)
async def summary_example() -> FillSummary:
    return FillSummary(
        rows_written=2,
        skipped_words=1,
        skipped_reasons={"idea": "未在教材正文中定位到例句"},
    )


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
    if not _has_selected_file(upload):
        await upload.close()
        return None
    return await _save_upload(upload, workdir)


def _has_selected_file(upload: UploadFile) -> bool:
    return bool((upload.filename or "").strip())


def _cleanup_dir(workdir: Path | None) -> None:
    if workdir is None:
        return
    shutil.rmtree(workdir, ignore_errors=True)
