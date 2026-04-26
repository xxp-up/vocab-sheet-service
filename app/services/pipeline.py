from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Awaitable, Callable

from app.models.domain import PipelineResult, VocabRow
from app.services.audio import AudioService
from app.services.document.service import DocumentService
from app.services.exercise_restore import ExerciseRestoreService
from app.services.lexicon import LexiconService
from app.services.workbook import WorkbookService
from app.utils.text import find_sentence_for_word, is_multiword_term, merge_words, normalize_word, parse_words_text


logger = logging.getLogger("vocab_sheet_service.pipeline")

ProgressCallback = Callable[[str, int, str], Awaitable[None] | None]


class PipelineContentError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        identified_words: list[str] | None = None,
        skipped_words: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        detail: dict[str, object] = {"message": message}
        if identified_words:
            detail["identified_words"] = identified_words
        if skipped_words:
            detail["skipped_words"] = skipped_words
        self.detail = detail


class PipelineService:
    def __init__(
        self,
        lexicon_service: LexiconService,
        document_service: DocumentService,
        audio_service: AudioService,
        exercise_restore_service: ExerciseRestoreService,
        workbook_service: WorkbookService,
    ) -> None:
        self.lexicon_service = lexicon_service
        self.document_service = document_service
        self.audio_service = audio_service
        self.exercise_restore_service = exercise_restore_service
        self.workbook_service = workbook_service

    async def process(
        self,
        teaching_path: Path,
        output_path: Path,
        *,
        audio_path: Path | None = None,
        words_text: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> PipelineResult:
        await _emit_progress(progress_callback, "document_parsing", 25, "教材解析")
        parsed_document = await self.document_service.parse(teaching_path)
        parsed_document = await self.exercise_restore_service.restore_document(parsed_document)
        logger.info(
            "Document parsed: file=%s source_type=%s pages=%s extracted_words=%s sentences=%s",
            teaching_path.name,
            parsed_document.source_type,
            len(parsed_document.pages),
            len(parsed_document.words),
            len(parsed_document.sentences),
        )

        document_words = [item.word for item in parsed_document.words]
        manual_words = parse_words_text(words_text)
        await _emit_progress(progress_callback, "merge_candidates", 45, "音频/补词合并")
        audio_hints = merge_words(document_words, manual_words)
        audio_words = await self.audio_service.extract_words(audio_path, hints=audio_hints)
        merged_words = merge_words(document_words, manual_words, audio_words)
        manual_keys = {normalize_word(word) for word in manual_words}
        audio_keys = {normalize_word(word) for word in audio_words}
        logger.info(
            "Word candidates merged: file=%s document=%s manual=%s audio=%s total=%s",
            teaching_path.name,
            len(document_words),
            len(manual_words),
            len(audio_words),
            len(merged_words),
        )

        if not merged_words:
            logger.warning("No candidate words identified for %s", teaching_path.name)
            raise PipelineContentError(
                "未识别到可回填的单词。当前只会从教材中的红字、下划线、批注，或手动补充单词中取词。"
            )

        await _emit_progress(progress_callback, "lexicon_enrichment", 65, "词典补全")
        meanings = await self.lexicon_service.enrich_words(merged_words, parsed_document.full_text)

        await _emit_progress(progress_callback, "sentence_matching", 85, "例句定位")
        rows: list[VocabRow] = []
        skipped: dict[str, str] = {}
        for word in merged_words:
            sentence = find_sentence_for_word(parsed_document.sentences, word)
            if sentence is None:
                skipped[word] = "未在教材正文中定位到例句"
                continue

            meaning = meanings.get(normalize_word(word))
            if meaning is None and not is_multiword_term(word):
                skipped[word] = "本地免费词典未找到该单词释义"
                continue

            normalized_word = normalize_word(word)
            source_names = [item.source for item in parsed_document.words if normalize_word(item.word) == normalized_word]
            if normalized_word in audio_keys and "audio" not in source_names:
                source_names.append("audio")
            if normalized_word in manual_keys and "manual" not in source_names:
                source_names.append("manual")

            rows.append(
                VocabRow(
                    word=meaning.word if meaning is not None and meaning.word else word,
                    ipa=meaning.ipa if meaning is not None else "",
                    pos_abbr=meaning.pos_abbr if meaning is not None else "",
                    zh_meaning=meaning.zh_meaning if meaning is not None else "",
                    example=sentence.text,
                    example_page=sentence.page_number,
                    sources=source_names,
                )
            )

        if not rows:
            logger.warning("All candidate words were skipped for %s", teaching_path.name)
            raise PipelineContentError(
                "已识别到候选单词，但都未能写入模板。",
                identified_words=merged_words,
                skipped_words=skipped,
            )

        logger.info(
            "Workbook rows prepared: file=%s rows_written=%s skipped=%s",
            teaching_path.name,
            len(rows),
            len(skipped),
        )
        await _emit_progress(progress_callback, "workbook_writing", 95, "模板写入")
        self.workbook_service.fill_template(rows, output_path)
        await _emit_progress(progress_callback, "download_ready", 100, "准备下载")
        logger.info("Workbook written: file=%s output=%s", teaching_path.name, output_path.name)
        return PipelineResult(output_path=str(output_path), rows_written=len(rows), skipped_words=skipped)


async def _emit_progress(progress_callback: ProgressCallback | None, stage_code: str, progress_percent: int, stage_label: str) -> None:
    if progress_callback is None:
        return
    result = progress_callback(stage_code, progress_percent, stage_label)
    if inspect.isawaitable(result):
        await result
