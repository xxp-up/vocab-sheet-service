from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Protocol

import httpx

from app.models.schemas import FeedbackDraftSection
from app.models.settings import Settings
from app.utils.text import collapse_whitespace, dedupe_preserve_order, split_sentences


SYSTEM_PROMPT = """
You turn classroom notes or transcripts into a parent-facing after-class feedback draft.
Return one JSON object and nothing else.
Use simplified Chinese, but keep important English words, phrases, topics, or grammar forms when needed.
Do not invent specific homework, praise, or grammar points that are not supported by the source.
Avoid repeating the same sentence across sections.
The JSON object must have exactly these keys:
- focus_items: array of 2 to 5 short strings about what was taught or reviewed today, each ideally within 30 Chinese characters
- pattern_items: array of 1 to 4 short strings about grammar rules, sentence patterns, or common mistakes, each ideally within 36 Chinese characters
- homework_items: array of 1 to 5 short strings with only explicit homework tasks, each ideally within 32 Chinese characters
- teacher_note: one concise Chinese paragraph suitable for parents, ideally within 60 to 100 Chinese characters
Never copy long raw transcript passages into any field.
"""

SECTION_REGEN_SYSTEM_PROMPT = """
You rewrite one section of a parent-facing after-class feedback draft.
Return one JSON object and nothing else.
The object must have exactly one key: "content".
Use simplified Chinese, keep important English words or grammar forms when needed, and avoid copying long raw transcript passages.
"""

USER_PROMPT_TEMPLATE = """
请根据以下课堂内容整理成课后反馈草稿，风格要求如下：
1. “本节课重点”适合逐条呈现，每条简洁清楚。
2. “规则 / 句型”只保留明确提到的语法、句型、知识点或易错点。
3. “作业”只保留明确布置的课后任务，不要重复课堂重点。
4. “教师补充”写成适合发给家长的一段提醒、表扬或学习建议。
5. 全部内容用中文表达，必要时保留英文单词或句型。

来源处理：
- 如果原始课堂内容同时包含【课堂音频转写】和【老师补充笔记 / 逐字稿】，必须结合两部分提炼总结。
- 课堂音频转写用于还原真实课堂内容；老师补充笔记用于校正、补充重点、作业和学生表现。
- 音频里出现但补充笔记没有写到的有效课堂内容，也要纳入总结；不要只按补充笔记生成。
- 若两部分信息冲突，以老师补充笔记中的准确作业、学生姓名和明确纠错为准。

上课日期：{lesson_date}
节次：第{lesson_index}节
班级 / 课程：{class_name}

原始课堂内容：
{transcript_text}
"""

SECTION_REGEN_PROMPT_TEMPLATE = """
请只重写“{section_title}”这个模块，基于原始课堂内容重新整理，不要输出其他模块。

要求：
1. 用中文表达，必要时保留关键英文单词、句型或话题名。
2. 内容必须来自原始课堂内容，不要编造。
3. 避免与其他模块重复。
4. 如果原始内容不足以支撑该模块，请给出简洁、保守的概括，不要粘贴大段原文。
5. 只返回一个 JSON 对象，格式为 {{"content":"..."}}。
6. 优先输出简洁总结，而不是口语化原文转述。
7. 如果原始内容同时包含【课堂音频转写】和【老师补充笔记 / 逐字稿】，必须同时参考两部分；不要只按补充笔记重写。

该模块的格式要求：
{section_rules}

当前其他模块内容：
{other_sections}

当前模块内容：
{current_section_content}

原始课堂内容：
{transcript_text}
"""

STOP_WORDS = {
    "a",
    "about",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "did",
    "do",
    "for",
    "had",
    "has",
    "have",
    "he",
    "i",
    "in",
    "is",
    "it",
    "not",
    "of",
    "okay",
    "on",
    "she",
    "sure",
    "that",
    "the",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "what",
    "yeah",
    "you",
}

SECTION_TITLES = {
    "header": "抬头",
    "focus": "本节课重点",
    "patterns": "规则 / 句型",
    "homework": "作业",
    "teacher_note": "教师补充",
}

SECTION_REGEN_RULES = {
    "focus": "输出 2 到 4 行，每行一个重点，适合用“⭐️”分条展示；不要写成长段。",
    "patterns": "输出 1 到 4 条规则，使用“1. 2. 3.”编号并逐行换行；每条尽量控制在 36 个中文字符以内。",
    "homework": "输出 1 到 5 条作业，使用“1. 2. 3.”编号并逐行换行；不要夹杂课堂总结。",
    "teacher_note": "输出 1 段或 2 到 3 行简短提醒，总长度尽量控制在 90 个中文字符以内；如有多个提醒点，请换行。",
}

DEFAULT_PATTERN_ITEMS = [
    "结合课堂讲解整理本节涉及的核心句型与语法规则。",
    "请对照课堂例句再次复述相关句型的使用场景。",
]
DEFAULT_HOMEWORK_ITEMS = [
    "完成课堂对应练习，巩固本节课重点。",
    "根据课堂笔记复习本节涉及的词汇与句型。",
]
DEFAULT_TEACHER_NOTE = "请课后结合课堂内容及时复习，并在下节课前完成巩固练习。"


class FeedbackGenerationError(ValueError):
    """Raised when feedback content cannot be generated from the source material."""


@dataclass(slots=True)
class FeedbackDraft:
    draft_sections: list[FeedbackDraftSection]
    composed_text: str
    transcript_text: str


@dataclass(slots=True)
class GeneratedFeedbackContent:
    focus_items: list[str]
    pattern_items: list[str]
    homework_items: list[str]
    teacher_note: str


class FeedbackPlanner(Protocol):
    async def build_feedback_content(
        self,
        *,
        transcript_text: str,
        lesson_date: date,
        lesson_index: int,
        class_name: str | None,
    ) -> GeneratedFeedbackContent: ...

    async def build_feedback_section(
        self,
        *,
        section_key: str,
        section_title: str,
        transcript_text: str,
        current_section_content: str,
        other_sections: list[FeedbackDraftSection],
    ) -> str: ...


class RemoteFeedbackPlanner:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = settings.require_vision_api_key()
        self.base_url = settings.vision_base_url.rstrip("/")
        self.model = settings.vision_model
        self.timeout = settings.effective_vision_timeout_seconds
        self.transport = transport

    async def build_feedback_content(
        self,
        *,
        transcript_text: str,
        lesson_date: date,
        lesson_index: int,
        class_name: str | None,
    ) -> GeneratedFeedbackContent:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.strip()},
                {
                    "role": "user",
                    "content": USER_PROMPT_TEMPLATE.format(
                        lesson_date=lesson_date.isoformat(),
                        lesson_index=lesson_index,
                        class_name=class_name.strip() if class_name and class_name.strip() else "未填写",
                        transcript_text=transcript_text,
                    ).strip(),
                },
            ],
            "temperature": 0.2,
            "max_tokens": 1400,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post("/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise FeedbackGenerationError("课后反馈生成超时，请稍后重试。") from exc
        except httpx.HTTPStatusError as exc:
            raise FeedbackGenerationError(
                f"课后反馈生成失败，服务返回 HTTP {exc.response.status_code}。"
            ) from exc
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise FeedbackGenerationError("课后反馈生成服务返回了无法解析的结果。") from exc

        content = _extract_message_content(data)
        return _parse_generated_feedback(content)

    async def build_feedback_section(
        self,
        *,
        section_key: str,
        section_title: str,
        transcript_text: str,
        current_section_content: str,
        other_sections: list[FeedbackDraftSection],
    ) -> str:
        other_sections_text = "\n\n".join(
            f"{section.title}\n{section.content}".strip()
            for section in other_sections
            if section.key != section_key and section.content.strip()
        ).strip() or "无"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SECTION_REGEN_SYSTEM_PROMPT.strip()},
                {
                    "role": "user",
                    "content": SECTION_REGEN_PROMPT_TEMPLATE.format(
                        section_title=section_title,
                        section_rules=SECTION_REGEN_RULES.get(section_key, "请输出简洁、清晰、适合直接粘贴到反馈模板的内容。"),
                        other_sections=other_sections_text,
                        current_section_content=current_section_content.strip() or "无",
                        transcript_text=transcript_text,
                    ).strip(),
                },
            ],
            "temperature": 0.35,
            "max_tokens": 700,
            "stream": False,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post("/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise FeedbackGenerationError("课后反馈模块重生成超时，请稍后重试。") from exc
        except httpx.HTTPStatusError as exc:
            raise FeedbackGenerationError(
                f"课后反馈模块重生成失败，服务返回 HTTP {exc.response.status_code}。"
            ) from exc
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise FeedbackGenerationError("课后反馈模块重生成服务返回了无法解析的结果。") from exc

        content = _extract_message_content(data)
        candidate = _extract_json_object(content)
        try:
            section_payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise FeedbackGenerationError("课后反馈模块重生成返回了无效的 JSON。") from exc

        regenerated = collapse_whitespace(str(section_payload.get("content", "")))
        if not regenerated:
            raise FeedbackGenerationError("课后反馈模块重生成未返回有效内容。")
        return regenerated


class FeedbackService:
    def __init__(
        self,
        settings: Settings | None = None,
        planner: FeedbackPlanner | None = None,
    ) -> None:
        self.planner = planner
        if self.planner is None and settings is not None and settings.vision_api_key.strip():
            self.planner = RemoteFeedbackPlanner(settings)

    async def generate_draft(
        self,
        *,
        transcript_text: str,
        lesson_date: date,
        lesson_index: int,
        class_name: str | None = None,
        source_kind: str = "manual",
    ) -> FeedbackDraft:
        cleaned_text = transcript_text.strip()
        if not cleaned_text:
            raise FeedbackGenerationError("缺少可用于生成课后反馈的课堂内容。")

        if source_kind == "audio" and _looks_like_low_confidence_audio_transcript(cleaned_text):
            raise FeedbackGenerationError(
                "当前音频转写结果疑似异常，未能识别出可靠的课堂内容。请优先粘贴课堂逐字稿，或检查录音清晰度后重试。"
            )

        normalized_lines = _normalize_lines(cleaned_text)
        prefer_planner_for_mixed_source = source_kind == "mixed" and self.planner is not None
        generated = None if prefer_planner_for_mixed_source else _extract_structured_feedback(normalized_lines)
        if generated is None and self.planner is not None:
            try:
                generated = await self.planner.build_feedback_content(
                    transcript_text=cleaned_text,
                    lesson_date=lesson_date,
                    lesson_index=lesson_index,
                    class_name=class_name,
                )
            except FeedbackGenerationError:
                generated = None

        if generated is None:
            generated = _build_heuristic_feedback(cleaned_text, normalized_lines)

        generated = _sanitize_generated_feedback(generated)
        sections = _build_feedback_sections(
            generated=generated,
            lesson_date=lesson_date,
            lesson_index=lesson_index,
            class_name=class_name,
        )
        sections = await self._refine_sections_if_needed(
            transcript_text=cleaned_text,
            sections=sections,
        )
        composed_text = "\n\n".join(f"{section.title}\n{section.content}".strip() for section in sections)
        return FeedbackDraft(
            draft_sections=sections,
            composed_text=composed_text,
            transcript_text=cleaned_text,
        )

    async def regenerate_section(
        self,
        *,
        section_key: str,
        transcript_text: str,
        lesson_date: date,
        lesson_index: int,
        class_name: str | None = None,
        draft_sections: list[FeedbackDraftSection] | None = None,
    ) -> FeedbackDraftSection:
        if section_key not in SECTION_TITLES:
            raise FeedbackGenerationError("不支持重新生成该反馈模块。")

        if section_key == "header":
            return FeedbackDraftSection(
                key="header",
                title=SECTION_TITLES["header"],
                content=_build_header(lesson_date, lesson_index, class_name),
            )

        cleaned_text = transcript_text.strip()
        if not cleaned_text:
            raise FeedbackGenerationError("缺少可用于重新生成模块的课堂内容。")

        current_sections = list(draft_sections or [])
        current_content = next((section.content for section in current_sections if section.key == section_key), "")
        if self.planner is not None:
            try:
                content = await self.planner.build_feedback_section(
                    section_key=section_key,
                    section_title=SECTION_TITLES[section_key],
                    transcript_text=cleaned_text,
                    current_section_content=current_content,
                    other_sections=current_sections,
                )
                return FeedbackDraftSection(
                    key=section_key,
                    title=SECTION_TITLES[section_key],
                    content=_sanitize_section_content(section_key, content),
                )
            except FeedbackGenerationError:
                pass

        normalized_lines = _normalize_lines(cleaned_text)
        generated = _extract_structured_feedback(normalized_lines)
        if generated is None:
            generated = _build_heuristic_feedback(cleaned_text, normalized_lines)
        generated = _sanitize_generated_feedback(generated)
        for section in _build_feedback_sections(
            generated=generated,
            lesson_date=lesson_date,
            lesson_index=lesson_index,
            class_name=class_name,
        ):
            if section.key == section_key:
                return section
        raise FeedbackGenerationError("未能重新生成该反馈模块。")

    async def _refine_sections_if_needed(
        self,
        *,
        transcript_text: str,
        sections: list[FeedbackDraftSection],
    ) -> list[FeedbackDraftSection]:
        if self.planner is None:
            return sections

        refined_sections = list(sections)
        for section_key in ("patterns", "teacher_note", "homework"):
            section = next((item for item in refined_sections if item.key == section_key), None)
            should_refine = section_key in {"patterns", "teacher_note"} or _needs_section_refinement(section_key, section.content)
            if section is None or not should_refine:
                continue

            try:
                content = await self.planner.build_feedback_section(
                    section_key=section_key,
                    section_title=section.title,
                    transcript_text=transcript_text,
                    current_section_content=section.content,
                    other_sections=refined_sections,
                )
            except FeedbackGenerationError:
                continue

            replacement = FeedbackDraftSection(
                key=section.key,
                title=section.title,
                content=_sanitize_section_content(section.key, content),
            )
            refined_sections = _replace_section(refined_sections, replacement)
        return refined_sections


def _build_header(lesson_date: date, lesson_index: int, class_name: str | None) -> str:
    lesson_title = f"{lesson_date.year}年{lesson_date.strftime('%B')} {_format_day(lesson_date.day)}，第{lesson_index}节"
    if class_name and class_name.strip():
        return f"{lesson_title}\n班级 / 课程：{class_name.strip()}"
    return lesson_title


def _build_feedback_sections(
    *,
    generated: GeneratedFeedbackContent,
    lesson_date: date,
    lesson_index: int,
    class_name: str | None,
) -> list[FeedbackDraftSection]:
    return [
        FeedbackDraftSection(
            key="header",
            title=SECTION_TITLES["header"],
            content=_build_header(lesson_date, lesson_index, class_name),
        ),
        FeedbackDraftSection(
            key="focus",
            title=SECTION_TITLES["focus"],
            content=_format_focus_section(generated.focus_items),
        ),
        FeedbackDraftSection(
            key="patterns",
            title=SECTION_TITLES["patterns"],
            content=_format_numbered_section(
                generated.pattern_items,
                fallback_items=DEFAULT_PATTERN_ITEMS,
            ),
        ),
        FeedbackDraftSection(
            key="homework",
            title=SECTION_TITLES["homework"],
            content=_format_numbered_section(
                generated.homework_items,
                fallback_items=DEFAULT_HOMEWORK_ITEMS,
            ),
        ),
        FeedbackDraftSection(
            key="teacher_note",
            title=SECTION_TITLES["teacher_note"],
            content=generated.teacher_note or DEFAULT_TEACHER_NOTE,
        ),
    ]


def _build_heuristic_feedback(text: str, lines: list[str]) -> GeneratedFeedbackContent:
    units = dedupe_preserve_order(lines or split_sentences(text) or [collapse_whitespace(text)])
    used: set[str] = set()

    focus_items = _pick_units(
        units,
        keywords=("review", "practice", "learn", "复习", "讲解", "默写", "学习", "单词", "话题", "时态", "句型"),
        limit=4,
        used=used,
    )
    pattern_items = _pick_units(
        units,
        keywords=("grammar", "pattern", "rule", "疑问句", "否定句", "句型", "规则", "语法", "时态", "will", "won't"),
        limit=3,
        used=used,
    )
    homework_items = _extract_homework_lines(lines)
    if not homework_items:
        homework_items = _pick_units(
            units,
            keywords=("homework", "assignment", "作业", "课后任务", "完成", "翻译", "默写", "背诵", "练习"),
            limit=4,
            used=used,
        )

    teacher_note = _pick_teacher_note(units, used)
    return GeneratedFeedbackContent(
        focus_items=focus_items,
        pattern_items=pattern_items,
        homework_items=homework_items,
        teacher_note=teacher_note,
    )


def _pick_units(units: list[str], *, keywords: tuple[str, ...], limit: int, used: set[str]) -> list[str]:
    selected: list[str] = []
    fallback: list[str] = []
    lowered_keywords = tuple(keyword.lower() for keyword in keywords)

    for unit in units:
        cleaned = _clean_inline_item(unit)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in used:
            continue
        lowered = f" {cleaned.lower()} "
        is_keyword_hit = any(keyword in lowered for keyword in lowered_keywords)
        if is_keyword_hit:
            selected.append(cleaned)
        elif _is_summary_friendly_unit(cleaned):
            fallback.append(cleaned)
        if len(selected) >= limit:
            break

    if not selected:
        selected = fallback[:limit]

    for item in selected:
        used.add(item.lower())
    return selected


def _pick_teacher_note(units: list[str], used: set[str]) -> str:
    for unit in units:
        cleaned = _clean_teacher_note_line(unit)
        if not cleaned:
            continue
        if not _is_summary_friendly_unit(cleaned, max_length=180):
            continue
        key = cleaned.lower()
        if key in used:
            continue
        lowered = cleaned.lower()
        if any(keyword in lowered for keyword in ("注意", "提醒", "表扬", "加油", "记得", "remember", "attention")):
            used.add(key)
            return cleaned

    for unit in units:
        cleaned = _clean_teacher_note_line(unit)
        if not cleaned:
            continue
        if not _is_summary_friendly_unit(cleaned, max_length=120):
            continue
        key = cleaned.lower()
        if key in used:
            continue
        used.add(key)
        return cleaned

    return ""


def _sanitize_generated_feedback(content: GeneratedFeedbackContent) -> GeneratedFeedbackContent:
    focus_items = _clean_generated_items("focus", content.focus_items, limit=4)
    pattern_items = _clean_generated_items("patterns", content.pattern_items, limit=4, excluded=focus_items)
    homework_items = _clean_generated_items("homework", content.homework_items, limit=5, excluded=focus_items + pattern_items)
    teacher_note = _format_teacher_note_content(content.teacher_note)

    if teacher_note:
        duplicates = {item.lower() for item in focus_items + pattern_items + homework_items}
        if teacher_note.lower() in duplicates:
            teacher_note = ""

    return GeneratedFeedbackContent(
        focus_items=focus_items,
        pattern_items=pattern_items,
        homework_items=homework_items,
        teacher_note=teacher_note,
    )


def _clean_generated_items(
    section_key: str,
    items: list[str],
    *,
    limit: int,
    excluded: list[str] | None = None,
) -> list[str]:
    results: list[str] = []
    seen = {item.lower() for item in (excluded or [])}
    for item in items:
        extracted_items = _extract_section_items(section_key, item)
        if not extracted_items and item:
            extracted_items = [_clean_inline_item(item)]
        for extracted in extracted_items:
            cleaned = _shorten_section_item(section_key, extracted)
            if not cleaned:
                continue
            key = cleaned.lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(cleaned)
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return results


def _extract_structured_feedback(lines: list[str]) -> GeneratedFeedbackContent | None:
    if not lines:
        return None

    focus_items: list[str] = []
    pattern_items: list[str] = []
    homework_items: list[str] = []
    teacher_notes: list[str] = []
    saw_template_cue = False
    in_homework = False

    for line in lines:
        if _is_homework_header(line):
            in_homework = True
            saw_template_cue = True
            continue

        if in_homework:
            homework_item = _extract_list_item(line)
            if homework_item:
                homework_items.append(homework_item)
                continue
            in_homework = False

        if _looks_like_focus_line(line):
            focus_items.append(_clean_inline_item(line))
            saw_template_cue = True
            continue

        inline_patterns = _extract_inline_numbered_items(line)
        if inline_patterns:
            pattern_items.extend(inline_patterns)
            teacher_notes.append(_clean_teacher_note_line(line))
            saw_template_cue = True
            continue

        lowered = line.lower()
        if any(keyword in lowered for keyword in ("规则", "句型", "语法", "知识点", "时态", "一般疑问句", "否定句")):
            pattern_items.append(_clean_inline_item(line))
            saw_template_cue = True
            continue

        if any(keyword in lowered for keyword in ("加油", "表扬", "提醒", "请熟记", "注意")):
            teacher_notes.append(_clean_teacher_note_line(line))
            saw_template_cue = True
            continue

    if not saw_template_cue:
        return None

    return GeneratedFeedbackContent(
        focus_items=focus_items,
        pattern_items=pattern_items,
        homework_items=homework_items,
        teacher_note="\n".join(item for item in teacher_notes if item),
    )


def _format_focus_section(items: list[str]) -> str:
    if not items:
        return "⭐️围绕本节课重点内容完成了课堂讲解与巩固练习。"
    return "\n".join(f"⭐️{item}" for item in items)


def _format_numbered_section(items: list[str], *, fallback_items: list[str]) -> str:
    lines = items or fallback_items
    return "\n".join(f"{index}. {item}" for index, item in enumerate(lines, start=1))


def _sanitize_section_content(section_key: str, content: str) -> str:
    cleaned = content.strip()
    if section_key == "header":
        return _normalize_multiline_text(cleaned)
    if section_key == "focus":
        items = _clean_generated_items("focus", [cleaned], limit=4)
        return _format_focus_section(items)
    if section_key == "patterns":
        items = _clean_generated_items("patterns", [cleaned], limit=4)
        return _format_numbered_section(items, fallback_items=DEFAULT_PATTERN_ITEMS)
    if section_key == "homework":
        items = _clean_generated_items("homework", [cleaned], limit=5)
        return _format_numbered_section(items, fallback_items=DEFAULT_HOMEWORK_ITEMS)
    if section_key == "teacher_note":
        return _format_teacher_note_content(cleaned) or DEFAULT_TEACHER_NOTE
    return _normalize_multiline_text(cleaned)


def _extract_section_items(section_key: str, text: str) -> list[str]:
    normalized = _normalize_multiline_text(text)
    if not normalized:
        return []

    normalized = re.sub(r"(?<!\n)([⭐★•●])\s*", r"\n\1", normalized)
    normalized = re.sub(r"(?<!\n)(\d+\s*[、.)．])\s*", r"\n\1 ", normalized)
    parts: list[str] = []

    for raw_line in normalized.splitlines():
        line = collapse_whitespace(raw_line)
        if not line:
            continue

        inline_items = _extract_inline_numbered_items(line)
        if inline_items:
            parts.extend(inline_items)
            continue

        if section_key in {"patterns", "homework"} and re.search(r"[；;]", line):
            split_parts = [collapse_whitespace(piece) for piece in re.split(r"[；;]+", line) if collapse_whitespace(piece)]
            if len(split_parts) > 1:
                parts.extend(split_parts)
                continue

        item = _extract_list_item(line) or _clean_inline_item(line)
        if item:
            parts.append(item)

    return parts


def _shorten_section_item(section_key: str, text: str) -> str:
    cleaned = _clean_inline_item(text)
    if not cleaned:
        return ""

    max_length = {"focus": 80, "patterns": 70, "homework": 80}.get(section_key, 80)
    if len(cleaned) <= max_length:
        return cleaned

    clauses = [
        collapse_whitespace(piece).strip("，,；;：:。")
        for piece in re.split(r"[。！？!?；;，,]", cleaned)
        if collapse_whitespace(piece).strip("，,；;：:。")
    ]
    for clause in clauses:
        if 4 <= len(clause) <= max_length:
            return clause
    if clauses:
        return clauses[0][:max_length].rstrip("，,；;：:。")
    return cleaned[:max_length].rstrip("，,；;：:。")


def _format_teacher_note_content(text: str) -> str:
    normalized = _normalize_multiline_text(text)
    if not normalized:
        return ""

    inline_items = _extract_inline_numbered_items(normalized)
    if inline_items:
        numbered_match = re.search(r"\d+\s*[、.)．]", normalized)
        intro = collapse_whitespace(normalized[: numbered_match.start()] if numbered_match else normalized).strip("：:")
        lines: list[str] = []
        if intro:
            lines.append(_trim_teacher_note(intro, max_length=60))
        lines.extend(f"{index}. {_trim_teacher_note(item, max_length=80)}" for index, item in enumerate(inline_items, start=1))
        return "\n".join(lines[:4])

    sentences = [
        collapse_whitespace(piece).strip("，,；;：:。")
        for piece in re.split(r"[。！？!?；;]+", normalized)
        if collapse_whitespace(piece).strip("，,；;：:。")
    ]
    if len(sentences) > 1:
        concise = [_trim_teacher_note(sentence, max_length=48) for sentence in sentences[:3]]
        return "\n".join(item for item in concise if item)

    if len(normalized) > 120:
        return _trim_teacher_note(normalized, max_length=90)
    return normalized


def _trim_teacher_note(text: str, *, max_length: int) -> str:
    cleaned = _clean_teacher_note_line(text)
    if len(cleaned) <= max_length:
        return cleaned
    clauses = [
        collapse_whitespace(piece).strip("，,；;：:。")
        for piece in re.split(r"[，,；;。]", cleaned)
        if collapse_whitespace(piece).strip("，,；;：:。")
    ]
    for clause in clauses:
        if 6 <= len(clause) <= max_length:
            return clause
    return cleaned[:max_length].rstrip("，,；;：:。")


def _normalize_multiline_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _needs_section_refinement(section_key: str, content: str) -> bool:
    normalized = _normalize_multiline_text(content)
    if not normalized:
        return True
    collapsed = collapse_whitespace(normalized)
    if section_key == "patterns":
        return len(collapsed) > 110 or normalized.count("\n") == 0
    if section_key == "teacher_note":
        return (
            len(collapsed) > 72
            or bool(_extract_inline_numbered_items(normalized))
            or "；" in normalized
            or ";" in normalized
            or normalized.count("，") >= 3
        )
    if section_key == "homework":
        return len(collapsed) > 120 or (normalized.count("\n") == 0 and not collapsed.startswith("1. "))
    return False


def _replace_section(
    existing_sections: list[FeedbackDraftSection],
    next_section: FeedbackDraftSection,
) -> list[FeedbackDraftSection]:
    updated_sections: list[FeedbackDraftSection] = []
    replaced = False
    for section in existing_sections:
        if section.key == next_section.key:
            updated_sections.append(next_section)
            replaced = True
        else:
            updated_sections.append(section)
    if not replaced:
        updated_sections.append(next_section)
    return updated_sections


def _normalize_lines(text: str) -> list[str]:
    return [collapse_whitespace(line) for line in re.split(r"[\r\n]+", text) if collapse_whitespace(line)]


def _extract_homework_lines(lines: list[str]) -> list[str]:
    results: list[str] = []
    capture_following = False

    for line in lines:
        if _is_homework_header(line):
            capture_following = True
            continue

        if capture_following:
            item = _extract_list_item(line)
            if item:
                results.append(item)
                continue
            capture_following = False

        inline_match = re.search(r"(?:作业|课后任务|homework|assignment)[:：]?\s*(.+)$", line, flags=re.IGNORECASE)
        if inline_match:
            cleaned = _clean_inline_item(inline_match.group(1))
            if cleaned:
                results.append(cleaned)

    return dedupe_preserve_order(results)[:5]


def _looks_like_focus_line(line: str) -> bool:
    return bool(re.match(r"^[⭐★•●\ufe0f\-]+\s*", line))


def _is_homework_header(line: str) -> bool:
    lowered = re.sub(r"^[📝⭐★•●\ufe0f\-\s]+", "", line).lower().strip()
    return lowered in {
        "作业",
        "作业:",
        "作业：",
        "课后任务",
        "课后任务:",
        "课后任务：",
        "homework",
        "homework:",
        "assignment",
        "assignment:",
    }


def _extract_list_item(line: str) -> str:
    cleaned = re.sub(r"^[📝⭐★•●\ufe0f\-\s]+", "", line).strip()
    cleaned = re.sub(r"^\d+\s*[、.)．]\s*", "", cleaned)
    cleaned = collapse_whitespace(cleaned)
    if not cleaned or _is_homework_header(cleaned):
        return ""
    return cleaned


def _extract_inline_numbered_items(line: str) -> list[str]:
    matches = re.findall(r"\d+\s*[、.)．]\s*([^；;]+)", line)
    return [collapse_whitespace(item) for item in matches if collapse_whitespace(item)]


def _clean_inline_item(text: str) -> str:
    cleaned = re.sub(r"^[📝⭐★•●\ufe0f\-\s]+", "", collapse_whitespace(text))
    cleaned = re.sub(r"^(?:本节课重点|规则\s*/\s*句型|教师补充|作业|课后任务)[:：]?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\d+\s*[、.)．]\s*", "", cleaned)
    return collapse_whitespace(cleaned).strip("：:")


def _clean_teacher_note_line(text: str) -> str:
    cleaned = _clean_inline_item(text)
    return cleaned.strip()


def _is_summary_friendly_unit(text: str, *, max_length: int = 120) -> bool:
    cleaned = collapse_whitespace(text)
    if not cleaned:
        return False
    if len(cleaned) > max_length:
        return False
    return True


def _looks_like_low_confidence_audio_transcript(text: str) -> bool:
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    if chinese_chars > 0:
        return False

    words = re.findall(r"[A-Za-z']+", text.lower())
    if len(words) < 160:
        return False

    sentence_count = len([item for item in re.split(r"(?<=[.!?])\s+", text.strip()) if item.strip()])
    unique_ratio = len(set(words)) / max(len(words), 1)
    common_ratio = sum(1 for word in words if word in STOP_WORDS) / max(len(words), 1)
    return sentence_count <= 2 and unique_ratio < 0.45 and common_ratio > 0.28


def _extract_message_content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise FeedbackGenerationError("课后反馈生成服务返回的结果不是 JSON 对象。")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise FeedbackGenerationError("课后反馈生成服务返回结果缺少 choices。")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise FeedbackGenerationError("课后反馈生成服务返回结果格式不正确。")

    message = choice.get("message")
    if not isinstance(message, dict):
        raise FeedbackGenerationError("课后反馈生成服务返回结果缺少 message。")

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, dict)]
        merged = "".join(texts).strip()
        if merged:
            return merged

    raise FeedbackGenerationError("课后反馈生成服务返回结果缺少文本内容。")


def _parse_generated_feedback(content: str) -> GeneratedFeedbackContent:
    candidate = _extract_json_object(content)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise FeedbackGenerationError("课后反馈生成服务返回了无效的 JSON。") from exc

    if not isinstance(data, dict):
        raise FeedbackGenerationError("课后反馈生成服务返回结果不是 JSON 对象。")

    return GeneratedFeedbackContent(
        focus_items=_coerce_text_list(data.get("focus_items")),
        pattern_items=_coerce_text_list(data.get("pattern_items")),
        homework_items=_coerce_text_list(data.get("homework_items")),
        teacher_note=collapse_whitespace(str(data.get("teacher_note", ""))),
    )


def _coerce_text_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [collapse_whitespace(str(item)) for item in value if collapse_whitespace(str(item))]
    if isinstance(value, str) and collapse_whitespace(value):
        return [collapse_whitespace(value)]
    return []


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            stripped = "\n".join(lines[1:-1]).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return stripped


def _format_day(day: int) -> str:
    if 11 <= day % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix}"
