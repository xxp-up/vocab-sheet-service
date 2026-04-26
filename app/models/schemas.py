from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class FillSummary(BaseModel):
    rows_written: int = Field(ge=0)
    skipped_words: int = Field(ge=0)
    skipped_reasons: dict[str, str] = Field(default_factory=dict)


JobStatus = Literal["queued", "processing", "completed", "failed"]


class JobCreatedResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress_percent: int = Field(ge=0, le=100)
    stage_code: str
    stage_label: str


class VocabJobStatusResponse(JobCreatedResponse):
    rows_written: int = Field(default=0, ge=0)
    skipped_words: dict[str, str] = Field(default_factory=dict)
    error_message: str | None = None
    download_url: str | None = None
    output_filename: str | None = None


class FeedbackDraftSection(BaseModel):
    key: str
    title: str
    content: str


class FeedbackJobStatusResponse(JobCreatedResponse):
    draft_sections: list[FeedbackDraftSection] = Field(default_factory=list)
    composed_text: str = ""
    transcript_text: str = ""
    error_message: str | None = None


class SettingsResponse(BaseModel):
    request_timeout_seconds: float = Field(gt=0)
    runtime_root: str = Field(min_length=1)
    vision_base_url: str = Field(min_length=1)
    vision_model: str = Field(min_length=1)
    vision_timeout_seconds: float | None = Field(default=None, gt=0)
    vision_api_key_masked: str = ""
    vision_api_key_configured: bool = False


class SettingsUpdateRequest(BaseModel):
    request_timeout_seconds: float = Field(gt=0)
    runtime_root: str = Field(min_length=1)
    vision_base_url: str = Field(min_length=1)
    vision_model: str = Field(min_length=1)
    vision_timeout_seconds: float | None = Field(default=None, gt=0)
    vision_api_key: str | None = None


class SettingsValidateResponse(BaseModel):
    ok: bool
    detail: str


class AudioTranscriptionResponse(BaseModel):
    transcript_text: str
    candidate_words: list[str] = Field(default_factory=list)
