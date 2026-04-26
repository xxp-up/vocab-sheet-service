from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class FillSummary(BaseModel):
    rows_written: int = Field(ge=0)
    skipped_words: int = Field(ge=0)
    skipped_reasons: dict[str, str] = Field(default_factory=dict)
