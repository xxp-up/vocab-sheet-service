from __future__ import annotations

from app.services.jobs import _compose_feedback_source_text, _resolve_feedback_source_kind


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
