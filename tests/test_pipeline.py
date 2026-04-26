from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.models.domain import DocumentParseResult, ExtractedWord, SentenceOccurrence, VocabMeaning
from app.services.pipeline import PipelineContentError, PipelineService


class _DocumentService:
    def __init__(self, result: DocumentParseResult) -> None:
        self._result = result

    async def parse(self, path: Path) -> DocumentParseResult:
        return self._result


class _AudioService:
    def __init__(self, words: list[str] | None = None) -> None:
        self._words = words or []

    async def extract_words(self, audio_path: Path | None, hints: list[str] | None = None) -> list[str]:
        return self._words


class _LexiconService:
    def __init__(self, meanings: dict[str, VocabMeaning] | None = None) -> None:
        self._meanings = meanings or {}

    async def enrich_words(self, words: list[str], full_text: str) -> dict[str, VocabMeaning]:
        return self._meanings


class _ExerciseRestoreService:
    def __init__(self, result: DocumentParseResult | None = None) -> None:
        self._result = result

    async def restore_document(self, document: DocumentParseResult) -> DocumentParseResult:
        return self._result or document


class _WorkbookService:
    def fill_template(self, rows, output_path: Path) -> None:
        raise AssertionError("Workbook should not be written when there is no content.")


class _CaptureWorkbookService:
    def __init__(self) -> None:
        self.rows = None
        self.output_path = None

    def fill_template(self, rows, output_path: Path) -> None:
        self.rows = rows
        self.output_path = output_path


def test_process_raises_when_no_candidate_words() -> None:
    pipeline = PipelineService(
        lexicon_service=_LexiconService(),
        document_service=_DocumentService(
            DocumentParseResult(
                source_type="pdf",
                full_text="This is a lesson.",
                words=[],
                sentences=[SentenceOccurrence(text="This is a lesson.", order=0, page_number=1)],
            )
        ),
        audio_service=_AudioService(),
        exercise_restore_service=_ExerciseRestoreService(),
        workbook_service=_WorkbookService(),
    )

    with pytest.raises(PipelineContentError) as excinfo:
        asyncio.run(
            pipeline.process(
                teaching_path=Path("lesson.pdf"),
                output_path=Path("result.xlsx"),
            )
        )

    assert "message" in excinfo.value.detail
    assert "identified_words" not in excinfo.value.detail


def test_process_raises_when_all_words_are_skipped() -> None:
    pipeline = PipelineService(
        lexicon_service=_LexiconService(
            meanings={"apple": VocabMeaning(word="apple", ipa="/apple/", pos_abbr="n.", zh_meaning="苹果")}
        ),
        document_service=_DocumentService(
            DocumentParseResult(
                source_type="pdf",
                full_text="This is a lesson.",
                words=[ExtractedWord(word="apple", source="pdf:qwen_vl", page_hint=1)],
                sentences=[SentenceOccurrence(text="This is a lesson.", order=0, page_number=1)],
            )
        ),
        audio_service=_AudioService(),
        exercise_restore_service=_ExerciseRestoreService(),
        workbook_service=_WorkbookService(),
    )

    with pytest.raises(PipelineContentError) as excinfo:
        asyncio.run(
            pipeline.process(
                teaching_path=Path("lesson.pdf"),
                output_path=Path("result.xlsx"),
            )
        )

    assert excinfo.value.detail["identified_words"] == ["apple"]
    assert excinfo.value.detail["skipped_words"] == {"apple": "未在教材正文中定位到例句"}


def test_process_keeps_phrase_row_when_lexicon_has_no_phrase_meaning() -> None:
    workbook = _CaptureWorkbookService()
    pipeline = PipelineService(
        lexicon_service=_LexiconService(),
        document_service=_DocumentService(
            DocumentParseResult(
                source_type="pdf",
                full_text="A growth mindset helps students learn.",
                words=[ExtractedWord(word="growth mindset", source="pdf:qwen_vl", page_hint=3)],
                sentences=[
                    SentenceOccurrence(
                        text="A growth mindset helps students learn.",
                        order=0,
                        page_number=3,
                    )
                ],
            )
        ),
        audio_service=_AudioService(),
        exercise_restore_service=_ExerciseRestoreService(),
        workbook_service=workbook,
    )

    result = asyncio.run(
        pipeline.process(
            teaching_path=Path("lesson.pdf"),
            output_path=Path("result.xlsx"),
        )
    )

    assert result.rows_written == 1
    assert workbook.rows is not None
    assert len(workbook.rows) == 1
    row = workbook.rows[0]
    assert row.word == "growth mindset"
    assert row.ipa == ""
    assert row.pos_abbr == ""
    assert row.zh_meaning == ""
    assert row.example == "A growth mindset helps students learn."
    assert row.example_page == 3


def test_process_uses_cleaned_sentence_from_restore_service() -> None:
    workbook = _CaptureWorkbookService()
    pipeline = PipelineService(
        lexicon_service=_LexiconService(
            meanings={"space": VocabMeaning(word="space", ipa="/space/", pos_abbr="n.", zh_meaning="空间")}
        ),
        document_service=_DocumentService(
            DocumentParseResult(
                source_type="pdf",
                full_text="source text",
                words=[ExtractedWord(word="space", source="pdf:qwen_vl", page_hint=2)],
                sentences=[],
            )
        ),
        audio_service=_AudioService(),
        exercise_restore_service=_ExerciseRestoreService(
            DocumentParseResult(
                source_type="pdf",
                full_text="source text",
                words=[ExtractedWord(word="space", source="pdf:qwen_vl", page_hint=2)],
                sentences=[
                    SentenceOccurrence(
                        text="You should ride your bike on the left to make space for",
                        order=0,
                        page_number=2,
                    )
                ],
            )
        ),
        workbook_service=workbook,
    )

    result = asyncio.run(
        pipeline.process(
            teaching_path=Path("lesson.pdf"),
            output_path=Path("result.xlsx"),
        )
    )

    assert result.rows_written == 1
    assert workbook.rows[0].example == "You should ride your bike on the left to make space for"


def test_process_skips_word_when_only_option_block_contains_it() -> None:
    pipeline = PipelineService(
        lexicon_service=_LexiconService(
            meanings={"yet": VocabMeaning(word="yet", ipa="/jet/", pos_abbr="adv.", zh_meaning="还")}
        ),
        document_service=_DocumentService(
            DocumentParseResult(
                source_type="pdf",
                full_text="source text",
                words=[ExtractedWord(word="yet", source="pdf:qwen_vl", page_hint=7)],
                sentences=[],
            )
        ),
        audio_service=_AudioService(),
        exercise_restore_service=_ExerciseRestoreService(
            DocumentParseResult(
                source_type="pdf",
                full_text="source text",
                words=[ExtractedWord(word="yet", source="pdf:qwen_vl", page_hint=7)],
                sentences=[],
            )
        ),
        workbook_service=_WorkbookService(),
    )

    with pytest.raises(PipelineContentError) as excinfo:
        asyncio.run(
            pipeline.process(
                teaching_path=Path("lesson.pdf"),
                output_path=Path("result.xlsx"),
            )
        )

    assert excinfo.value.detail["identified_words"] == ["yet"]
    assert excinfo.value.detail["skipped_words"] == {"yet": "未在教材正文中定位到例句"}


def test_process_emits_progress_stages_in_order() -> None:
    workbook = _CaptureWorkbookService()
    pipeline = PipelineService(
        lexicon_service=_LexiconService(
            meanings={"apple": VocabMeaning(word="apple", ipa="/apple/", pos_abbr="n.", zh_meaning="苹果")}
        ),
        document_service=_DocumentService(
            DocumentParseResult(
                source_type="pdf",
                full_text="Apple is red.",
                words=[ExtractedWord(word="apple", source="pdf:qwen_vl", page_hint=1)],
                sentences=[SentenceOccurrence(text="Apple is red.", order=0, page_number=1)],
            )
        ),
        audio_service=_AudioService(),
        exercise_restore_service=_ExerciseRestoreService(),
        workbook_service=workbook,
    )
    stages: list[tuple[str, int, str]] = []

    async def _progress(stage_code: str, percent: int, label: str) -> None:
        stages.append((stage_code, percent, label))

    result = asyncio.run(
        pipeline.process(
            teaching_path=Path("lesson.pdf"),
            output_path=Path("result.xlsx"),
            progress_callback=_progress,
        )
    )

    assert result.rows_written == 1
    assert stages == [
        ("document_parsing", 25, "教材解析"),
        ("merge_candidates", 45, "音频/补词合并"),
        ("lexicon_enrichment", 65, "词典补全"),
        ("sentence_matching", 85, "例句定位"),
        ("workbook_writing", 95, "模板写入"),
        ("download_ready", 100, "准备下载"),
    ]
