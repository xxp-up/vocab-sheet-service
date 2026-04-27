from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ExtractedWord:
    word: str
    source: str
    page_hint: int | None = None


@dataclass(slots=True)
class DocumentPage:
    text: str
    page_number: int | None = None


@dataclass(slots=True)
class SentenceOccurrence:
    text: str
    order: int
    page_number: int | None = None


@dataclass(slots=True)
class DocumentParseResult:
    source_type: str
    full_text: str
    pages: list[DocumentPage] = field(default_factory=list)
    words: list[ExtractedWord] = field(default_factory=list)
    sentences: list[SentenceOccurrence] = field(default_factory=list)


@dataclass(slots=True)
class VocabMeaning:
    word: str
    ipa: str
    pos_abbr: str
    zh_meaning: str


@dataclass(slots=True)
class VocabRow:
    word: str
    ipa: str
    pos_abbr: str
    zh_meaning: str
    example: str
    example_page: int | None = None
    sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VocabSkippedItem:
    word: str
    reason: str
    sources: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PipelineResult:
    output_path: str
    rows_written: int
    skipped_words: dict[str, str] = field(default_factory=dict)
    written_rows: list[VocabRow] = field(default_factory=list)
    skipped_items: list[VocabSkippedItem] = field(default_factory=list)
