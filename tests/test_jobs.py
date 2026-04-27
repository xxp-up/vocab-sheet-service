from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

from app.services.jobs import _compose_feedback_source_text, _resolve_feedback_source_kind
from app.services.jobs import FeedbackJobRecord, JobStore, VocabJobRecord


def test_compose_feedback_source_text_merges_audio_and_manual_notes() -> None:
    merged = _compose_feedback_source_text(
        audio_transcript_text="今天复习一般疑问句。",
        manual_transcript_text="补充：布置了翻译题作业。",
    )

    assert "合并要求" in merged
    assert "课堂音频转写" in merged
    assert "老师补充笔记 / 逐字稿" in merged
    assert "今天复习一般疑问句。" in merged
    assert "补充：布置了翻译题作业。" in merged


def test_resolve_feedback_source_kind_supports_mixed_inputs() -> None:
    assert _resolve_feedback_source_kind(audio_transcript_text="音频", manual_transcript_text="笔记") == "mixed"
    assert _resolve_feedback_source_kind(audio_transcript_text="音频", manual_transcript_text="") == "audio"
    assert _resolve_feedback_source_kind(audio_transcript_text="", manual_transcript_text="笔记") == "manual"


def test_job_store_detects_running_jobs_across_vocab_and_feedback() -> None:
    store = JobStore()
    store.vocab_jobs["vocab-1"] = VocabJobRecord(
        job_id="vocab-1",
        workdir=Path(".runtime/test-jobs/vocab-1"),
        teaching_path=Path("lesson.pdf"),
        audio_path=None,
        words_text=None,
        output_path=Path("lesson_filled.xlsx"),
        output_filename="lesson_filled.xlsx",
        status="processing",
    )
    store.feedback_jobs["feedback-1"] = FeedbackJobRecord(
        job_id="feedback-1",
        workdir=Path(".runtime/test-jobs/feedback-1"),
        lesson_date=date(2026, 4, 27),
        lesson_index=1,
        class_name=None,
        audio_path=None,
        transcript_text="课堂内容",
        status="completed",
    )

    assert asyncio.run(store.has_running_jobs()) is True


def test_job_store_ignores_completed_and_failed_jobs_when_checking_running_state() -> None:
    store = JobStore()
    store.vocab_jobs["vocab-1"] = VocabJobRecord(
        job_id="vocab-1",
        workdir=Path(".runtime/test-jobs/vocab-1"),
        teaching_path=Path("lesson.pdf"),
        audio_path=None,
        words_text=None,
        output_path=Path("lesson_filled.xlsx"),
        output_filename="lesson_filled.xlsx",
        status="completed",
    )
    store.feedback_jobs["feedback-1"] = FeedbackJobRecord(
        job_id="feedback-1",
        workdir=Path(".runtime/test-jobs/feedback-1"),
        lesson_date=date(2026, 4, 27),
        lesson_index=1,
        class_name=None,
        audio_path=None,
        transcript_text="课堂内容",
        status="failed",
    )

    assert asyncio.run(store.has_running_jobs()) is False
