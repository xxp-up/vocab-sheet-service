from __future__ import annotations

from pathlib import Path
from typing import Protocol

import fitz

from app.models.domain import DocumentPage, DocumentParseResult, ExtractedWord
from app.services.vision import VisionPageResult
from app.utils.text import build_sentence_occurrences, clean_marked_term, has_english_content


PDF_RENDER_DPI = 180


class PageVisionClient(Protocol):
    async def extract_page(self, image_bytes: bytes, page_number: int) -> VisionPageResult:
        """Extract page text and emphasized words from a rendered PDF page."""


async def parse_pdf(path: Path, vision_client: PageVisionClient) -> DocumentParseResult:
    document = fitz.open(path)
    try:
        full_text_parts: list[str] = []
        pages: list[DocumentPage] = []
        extracted_words: list[ExtractedWord] = []

        for index, page in enumerate(document):
            page_number = index + 1
            page_result = await vision_client.extract_page(_render_page_png(page), page_number)
            if page_result.page_text:
                page_text = page_result.page_text.strip()
                full_text_parts.append(page_text)
                pages.append(DocumentPage(text=page_text, page_number=page_number))

            for raw_word in page_result.marked_words:
                token = clean_marked_term(raw_word)
                if token and has_english_content(token):
                    extracted_words.append(
                        ExtractedWord(word=token, source="pdf:qwen_vl", page_hint=page_number)
                    )

        full_text = "\n".join(full_text_parts)
        return DocumentParseResult(
            source_type="pdf",
            full_text=full_text,
            pages=pages,
            words=_dedupe_extracted(extracted_words),
            sentences=build_sentence_occurrences(pages),
        )
    finally:
        document.close()


def _render_page_png(page: fitz.Page) -> bytes:
    pixmap = page.get_pixmap(dpi=PDF_RENDER_DPI, alpha=False, annots=True)
    return pixmap.tobytes("png")


def _dedupe_extracted(words: list[ExtractedWord]) -> list[ExtractedWord]:
    seen: dict[str, ExtractedWord] = {}
    for item in words:
        key = item.word.strip().lower()
        if key and key not in seen:
            seen[key] = item
    return list(seen.values())
