from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from app.models.schemas import FeedbackDraftSection
from app.utils.text import collapse_whitespace, split_sentences


class FeedbackGenerationError(ValueError):
    """Raised when feedback content cannot be generated from the source material."""


@dataclass(slots=True)
class FeedbackDraft:
    draft_sections: list[FeedbackDraftSection]
    composed_text: str
    transcript_text: str


class FeedbackService:
    def generate_draft(
        self,
        *,
        transcript_text: str,
        lesson_date: date,
        lesson_index: int,
        class_name: str | None = None,
    ) -> FeedbackDraft:
        cleaned_text = transcript_text.strip()
        if not cleaned_text:
            raise FeedbackGenerationError("缺少可用于生成课后反馈的课堂内容。")

        normalized_lines = _normalize_lines(cleaned_text)
        sentences = split_sentences(cleaned_text)
        sections = [
            FeedbackDraftSection(
                key="header",
                title="抬头",
                content=_build_header(lesson_date, lesson_index, class_name),
            ),
            FeedbackDraftSection(
                key="focus",
                title="本节课重点",
                content=_build_focus_section(sentences),
            ),
            FeedbackDraftSection(
                key="patterns",
                title="规则 / 句型",
                content=_build_patterns_section(sentences),
            ),
            FeedbackDraftSection(
                key="homework",
                title="作业",
                content=_build_homework_section(normalized_lines, sentences),
            ),
            FeedbackDraftSection(
                key="teacher_note",
                title="教师补充",
                content=_build_teacher_note(sentences),
            ),
        ]
        composed_text = "\n\n".join(f"{section.title}\n{section.content}".strip() for section in sections)
        return FeedbackDraft(
            draft_sections=sections,
            composed_text=composed_text,
            transcript_text=cleaned_text,
        )


def _build_header(lesson_date: date, lesson_index: int, class_name: str | None) -> str:
    lesson_title = f"{lesson_date.year}年{lesson_date.strftime('%B')} {_format_day(lesson_date.day)}，第{lesson_index}节"
    if class_name and class_name.strip():
        return f"{lesson_title}\n班级 / 课程：{class_name.strip()}"
    return lesson_title


def _build_focus_section(sentences: list[str]) -> str:
    highlights = _pick_sentences(
        sentences,
        keywords=("review", "practice", "learn", "复习", "学习", "重点", "表格", "比较级", "最高级", "句型", "grammar"),
        fallback_count=4,
    )
    if not highlights:
        return "1. 本节课围绕教材重点内容进行了课堂讲解与例句练习。"
    return _to_numbered_lines(highlights)


def _build_patterns_section(sentences: list[str]) -> str:
    patterns = _pick_sentences(
        sentences,
        keywords=("as ", " than ", " most ", "比较级", "最高级", "句型", "规则", "grammar", "pattern"),
        fallback_count=3,
    )
    if not patterns:
        patterns = [
            "1. 按课堂讲解整理本节涉及的核心句型与变化规则。",
            "2. 结合教材例句复述每个句型的使用场景。",
        ]
        return "\n".join(patterns)
    return _to_numbered_lines(patterns)


def _build_homework_section(lines: list[str], sentences: list[str]) -> str:
    homework_lines = _extract_homework_lines(lines)
    if homework_lines:
        return _to_numbered_lines(homework_lines)

    candidates = _pick_sentences(
        sentences,
        keywords=("homework", "assignment", "作业", "完成", "翻译", "默写", "背诵", "练习"),
        fallback_count=3,
    )
    if not candidates:
        candidates = [
            "完成课堂对应练习，巩固本节重点句型。",
            "复习并整理本节课涉及的规则与例句。",
        ]
    return _to_numbered_lines(candidates)


def _build_teacher_note(sentences: list[str]) -> str:
    notes = _pick_sentences(
        sentences,
        keywords=("attention", "remember", "注意", "建议", "提醒", "易错", "纠错", "pronunciation"),
        fallback_count=2,
    )
    if not notes:
        return "建议课后继续结合教材例句进行口头复述，并在下节课前完成重点词句复习。"
    return "\n".join(f"- {item}" for item in notes)


def _pick_sentences(sentences: list[str], *, keywords: tuple[str, ...], fallback_count: int) -> list[str]:
    selected: list[str] = []
    for sentence in sentences:
        normalized = sentence.strip()
        if not normalized:
            continue
        lowered = f" {normalized.lower()} "
        if any(keyword.lower() in lowered for keyword in keywords):
            selected.append(collapse_whitespace(normalized))
    if not selected:
        selected = [collapse_whitespace(item) for item in sentences[:fallback_count] if collapse_whitespace(item)]

    deduped: list[str] = []
    seen: set[str] = set()
    for item in selected:
        key = item.lower()
        if key in seen:
            continue
        deduped.append(item)
        seen.add(key)
        if len(deduped) >= fallback_count:
            break
    return deduped


def _normalize_lines(text: str) -> list[str]:
    return [collapse_whitespace(line) for line in re.split(r"[\r\n]+", text) if collapse_whitespace(line)]


def _extract_homework_lines(lines: list[str]) -> list[str]:
    results: list[str] = []
    capture_following = False

    for line in lines:
        lowered = line.lower()
        if capture_following:
            if re.match(r"^(?:\d+[.)]|[-*])\s*", line):
                results.append(re.sub(r"^(?:\d+[.)]|[-*])\s*", "", line).strip())
                continue
            capture_following = False

        if lowered in {"作业", "作业:", "作业：", "homework", "homework:"}:
            capture_following = True
            continue

        inline_match = re.search(r"(?:作业|homework|assignment)[:：]?\s*(.+)$", line, flags=re.IGNORECASE)
        if inline_match:
            cleaned = inline_match.group(1).strip()
            if cleaned:
                results.append(cleaned)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in results:
        key = item.lower()
        if key in seen:
            continue
        deduped.append(item)
        seen.add(key)
    return deduped[:5]


def _to_numbered_lines(items: list[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _format_day(day: int) -> str:
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"
