from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.models.schemas import FeedbackDraftSection
from app.services.feedback import FeedbackGenerationError, FeedbackService, GeneratedFeedbackContent


def test_feedback_service_generates_expected_sections() -> None:
    service = FeedbackService()

    draft = asyncio.run(
        service.generate_draft(
            transcript_text=(
                "Today we review comparative adjectives. "
                "A be as ... as B is one key pattern. "
                "Homework: finish the worksheet and memorize the irregular forms."
            ),
            lesson_date=date(2026, 3, 11),
            lesson_index=1,
            class_name="\u4e94\u5e74\u7ea7\u82f1\u8bed\u63d0\u9ad8\u73ed",
        )
    )

    assert [section.key for section in draft.draft_sections] == [
        "header",
        "focus",
        "patterns",
        "homework",
        "teacher_note",
    ]
    assert "2026\u5e74March 11th\uff0c\u7b2c1\u8282" in draft.draft_sections[0].content
    assert "\u4e94\u5e74\u7ea7\u82f1\u8bed\u63d0\u9ad8\u73ed" in draft.draft_sections[0].content
    assert "Homework" not in draft.draft_sections[3].content
    assert "finish the worksheet" in draft.draft_sections[3].content.lower()
    assert "\u62ac\u5934" in draft.composed_text


def test_feedback_service_parses_structured_teacher_notes() -> None:
    service = FeedbackService()

    draft = asyncio.run(
        service.generate_draft(
            transcript_text=(
                "April 22th\uff0c\u7b2c7\u8282\n\n"
                "\u2b50\ufe0f\u9ed8\u5199\u4eba\u79f0\u8868\u683c\u548c\u8bdd\u9898food and drinks\u548cfamily and home\u5355\u8bcd\u8868\n"
                "\u2b50\ufe0f\u8bb2\u89e3\u5173\u4e8e\u65f6\u6001\u6d4b\u8bd5\u9898\u7684\u7ec3\u4e60\u7eb8\n"
                "\u2b50\ufe0f\u590d\u4e60\u4e00\u822c\u7591\u95ee\u53e5\u548c\u5426\u5b9a\u53e5\u7684\u6539\u5199\u6280\u5de7\n\n"
                "[\u52a0\u6cb9]\u8bb2\u89e3\u6d4b\u8bd5\u9898\u7684\u8fc7\u7a0b\u4e2d\uff0c\u4e09\u4e2a\u5b69\u5b50\u90fd\u9700\u8981\u6ce8\u610f\u4ee5\u4e0b\u77e5\u8bc6\u70b9\uff1a"
                "1\u3001will not=won't\uff1b"
                "2\u3001\u9648\u8ff0\u53e5\u6539\u4e3a\u5426\u5b9a\u53e5\u548c\u4e00\u822c\u7591\u95ee\u53e5\u90fd\u662f\u5148\u627ebe\u548c\u60c5\u6001\u52a8\u8bcd\uff0c\u6ca1\u6709\u518d\u627e\u52a9\u52a8\u8bcddo/does/did\uff1b"
                "3\u3001\u52a8\u8bcd\u8fc7\u53bb\u5f0f\u548c\u73b0\u5728\u5206\u8bcd\u7684\u53d8\u5316\u89c4\u5219\uff0c\u518d\u6b21\u8868\u626cCece\u672c\u6b21\u4eba\u79f0\u8868\u683c\u9ed8\u5199\u6b63\u786e\uff0c"
                "\u518d\u9ed8\u5199\u6b63\u786e\u4e00\u6b21\u5c31\u6ee1\u8fde\u7eed3\u6b21\u9ed8\u5199\u6b63\u786e\u5566\uff0c\u7ee7\u7eed\u52a0\u6cb9~\n\n"
                "\u8bf7\u719f\u8bb0\n"
                "\U0001f4dd\u8bfe\u540e\u4efb\u52a1\uff1a\n"
                "1.\u5b8c\u6210\u7ec3\u4e60\u7b2c\u56db\u9898\u7ffb\u8bd1\u9898\n"
                "2.\u719f\u8bb0\u52a8\u8bcd\u8fc7\u53bb\u5f0f\u8fc7\u53bb\u5206\u8bcd\u8868\u683c\uff08\u4e0b\u8282\u8bfe\u5802\u9ed8\uff09\n"
                "3.\u719f\u8bb0\u5e76\u6253\u5361\u6717\u8bfb\u5355\u8bcd\u8868food and drinks\u5230sports and health\u4e09\u4e2a\u8bdd\u9898\u7684\u5355\u8bcd\n"
            ),
            lesson_date=date(2026, 4, 22),
            lesson_index=7,
        )
    )

    focus = draft.draft_sections[1].content
    patterns = draft.draft_sections[2].content
    homework = draft.draft_sections[3].content
    teacher_note = draft.draft_sections[4].content

    assert "\u9ed8\u5199\u4eba\u79f0\u8868\u683c" in focus
    assert "\u8bb2\u89e3\u5173\u4e8e\u65f6\u6001\u6d4b\u8bd5\u9898\u7684\u7ec3\u4e60\u7eb8" in focus
    assert "\u590d\u4e60\u4e00\u822c\u7591\u95ee\u53e5\u548c\u5426\u5b9a\u53e5\u7684\u6539\u5199\u6280\u5de7" in focus
    assert "will not=won't" in patterns
    assert "\u9648\u8ff0\u53e5\u6539\u4e3a\u5426\u5b9a\u53e5" in patterns
    assert "\u5b8c\u6210\u7ec3\u4e60\u7b2c\u56db\u9898\u7ffb\u8bd1\u9898" in homework
    assert "Cece" in teacher_note
    assert "\u8bf7\u719f\u8bb0" in teacher_note


def test_feedback_service_mixed_source_uses_full_planner_before_structured_notes() -> None:
    class _Planner:
        def __init__(self) -> None:
            self.content_calls = 0
            self.seen_transcript = ""

        async def build_feedback_content(self, **kwargs):
            self.content_calls += 1
            self.seen_transcript = kwargs["transcript_text"]
            return GeneratedFeedbackContent(
                focus_items=["讲解新版KET教材和U1课堂流程", "复习一般疑问句改写"],
                pattern_items=["will not=won't"],
                homework_items=["完成翻译题"],
                teacher_note="已结合课堂音频和补充笔记整理，请课后按作业要求复习。",
            )

        async def build_feedback_section(self, **kwargs) -> str:
            return kwargs["current_section_content"]

    planner = _Planner()
    service = FeedbackService(planner=planner)
    mixed_transcript = (
        "【课堂音频转写】\n"
        "今天主要介绍新版KET教材，讲到第一单元的课堂流程和分层课时安排。\n\n"
        "【老师补充笔记 / 逐字稿】\n"
        "⭐️复习一般疑问句和否定句的改写技巧\n"
        "📝课后任务：\n"
        "1.完成翻译题"
    )

    draft = asyncio.run(
        service.generate_draft(
            transcript_text=mixed_transcript,
            lesson_date=date(2026, 4, 27),
            lesson_index=1,
            source_kind="mixed",
        )
    )

    focus = next(section for section in draft.draft_sections if section.key == "focus")
    homework = next(section for section in draft.draft_sections if section.key == "homework")

    assert planner.content_calls == 1
    assert "课堂音频转写" in planner.seen_transcript
    assert "老师补充笔记 / 逐字稿" in planner.seen_transcript
    assert "KET教材" in focus.content
    assert "完成翻译题" in homework.content


def test_feedback_service_rejects_low_confidence_audio_transcript() -> None:
    service = FeedbackService()
    gibberish = (
        "not last that doing this it's all about you all good that found that auto how can you please "
        "that should be possible oh okay motel of i'm sure sure so good want to go good yeah kate you know "
        "the shows you know and i shot either jewish day what about you or it's yeah he looked it up "
    ) * 12

    with pytest.raises(FeedbackGenerationError) as exc_info:
        asyncio.run(
            service.generate_draft(
                transcript_text=gibberish,
                lesson_date=date(2026, 4, 27),
                lesson_index=1,
                source_kind="audio",
            )
        )

    assert "\u8f6c\u5199\u7ed3\u679c\u7591\u4f3c\u5f02\u5e38" in str(exc_info.value)


def test_feedback_service_regenerates_specific_section() -> None:
    class _Planner:
        async def build_feedback_content(self, **kwargs):  # pragma: no cover - not used in this test
            raise AssertionError("build_feedback_content should not be called")

        async def build_feedback_section(self, **kwargs) -> str:
            assert kwargs["section_key"] == "patterns"
            assert kwargs["section_title"] == "规则 / 句型"
            assert kwargs["other_sections"][0].key == "focus"
            return "1. 重新整理了一般疑问句和否定句的改写方法。"

    service = FeedbackService(planner=_Planner())

    section = asyncio.run(
        service.regenerate_section(
            section_key="patterns",
            transcript_text="复习一般疑问句和否定句的改写方法。",
            lesson_date=date(2026, 4, 22),
            lesson_index=7,
            draft_sections=[
                FeedbackDraftSection(key="focus", title="本节课重点", content="⭐️复习一般疑问句。"),
                FeedbackDraftSection(key="patterns", title="规则 / 句型", content="1. 旧内容"),
            ],
        )
    )

    assert section.key == "patterns"
    assert "一般疑问句" in section.content
    assert "\n" in section.content or section.content.startswith("1. ")


def test_feedback_service_fallback_keeps_long_raw_transcript_out_of_sections() -> None:
    service = FeedbackService()
    long_transcript = (
        "这是一个非常长的课堂说明文本，主要在连续讲解教材安排、课堂流程、老师培训内容和一些背景说明，"
        "没有明确的作业条目，也没有清晰拆分成适合直接贴进反馈模板的短句。"
    ) * 12

    draft = asyncio.run(
        service.generate_draft(
            transcript_text=long_transcript,
            lesson_date=date(2026, 4, 27),
            lesson_index=1,
        )
    )

    patterns = next(section for section in draft.draft_sections if section.key == "patterns")
    teacher_note = next(section for section in draft.draft_sections if section.key == "teacher_note")

    assert len(patterns.content) < 120
    assert len(teacher_note.content) < 80


def test_feedback_service_refines_verbose_sections_with_planner() -> None:
    class _Planner:
        async def build_feedback_content(self, **kwargs):
            return GeneratedFeedbackContent(
                focus_items=["复习一般疑问句和否定句改写。"],
                pattern_items=[
                    "这一部分主要是在非常详细地解释一般疑问句、否定句以及be动词、情态动词和助动词的判断顺序，所以内容比较长。"
                ],
                homework_items=["完成课堂练习。"],
                teacher_note="这一段老师补充写得过长，而且更像课堂原文转写，并不适合直接发给家长，所以应该被再次压缩整理。",
            )

        async def build_feedback_section(self, **kwargs) -> str:
            if kwargs["section_key"] == "patterns":
                return "1. 否定句和一般疑问句先找be动词。\n2. 没有be再找do / does / did。"
            if kwargs["section_key"] == "teacher_note":
                return "请课后重点复习否定句和一般疑问句改写；下节课继续检查掌握情况。"
            return kwargs["current_section_content"]

    service = FeedbackService(planner=_Planner())

    draft = asyncio.run(
        service.generate_draft(
            transcript_text="复习一般疑问句和否定句改写，讲解be动词与助动词判断顺序。",
            lesson_date=date(2026, 4, 22),
            lesson_index=7,
        )
    )

    patterns = next(section for section in draft.draft_sections if section.key == "patterns")
    teacher_note = next(section for section in draft.draft_sections if section.key == "teacher_note")

    assert "1. 否定句和一般疑问句先找be动词。" in patterns.content
    assert "\n2. 没有be再找do / does / did。" in patterns.content
    assert "\n" in teacher_note.content
    assert len(teacher_note.content) < 100
