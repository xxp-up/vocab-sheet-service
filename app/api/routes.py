from __future__ import annotations

import json
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

from app.models.schemas import FillSummary, HealthResponse
from app.models.settings import ConfigurationError, Settings, get_settings
from app.services.audio import AudioService, AudioServiceError, UnsupportedAudioFormatError
from app.services.document.service import DocumentService, UnsupportedDocumentError
from app.services.exercise_restore import ExerciseRestoreService
from app.services.lexicon import LexiconService, LexiconServiceError
from app.services.pipeline import PipelineContentError, PipelineService
from app.services.vision import VisionServiceError
from app.services.workbook import WorkbookService, WorkbookTemplateError


router = APIRouter()
logger = logging.getLogger("vocab_sheet_service.api")


def build_pipeline(settings: Settings) -> PipelineService:
    return PipelineService(
        lexicon_service=LexiconService(settings),
        document_service=DocumentService(settings),
        audio_service=AudioService(settings),
        exercise_restore_service=ExerciseRestoreService(settings),
        workbook_service=WorkbookService(),
    )


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse()


@router.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = """
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <meta charset="utf-8" />
        <title>Vocab Sheet Service</title>
        <style>
          body { font-family: "Microsoft YaHei", sans-serif; max-width: 760px; margin: 40px auto; padding: 0 16px; }
          form { display: grid; gap: 12px; padding: 20px; border: 1px solid #ddd; border-radius: 12px; }
          .hint { color: #666; font-size: 14px; margin: 0; }
          button { width: 180px; padding: 10px 14px; background: #1f6feb; color: white; border: 0; border-radius: 8px; }
          input[type=file], textarea { width: 100%; }
        </style>
      </head>
      <body>
        <h1>教材抽词回填服务</h1>
        <p class="hint">系统固定使用模板：test 6单词表模板.xlsx</p>
        <form action="/v1/vocab/fill" method="post" enctype="multipart/form-data">
          <label>教材文件（PDF 或 DOCX）<input name="teaching_file" type="file" required /></label>
          <label>音频文件（可选）<input name="audio_file" type="file" /></label>
          <label>手动补充单词（可选）<textarea name="words_text" rows="5"></textarea></label>
          <button type="submit">生成单词表</button>
        </form>
      </body>
    </html>
    """
    return HTMLResponse(html)


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
