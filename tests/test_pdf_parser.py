from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import fitz

from app.services.document.pdf import parse_pdf
from app.services.vision import VisionPageResult


class _FakeVisionClient:
    def __init__(self, results: list[VisionPageResult]) -> None:
        self.results = results
        self.calls: list[tuple[int, bytes]] = []

    async def extract_page(self, image_bytes: bytes, page_number: int) -> VisionPageResult:
        self.calls.append((page_number, image_bytes))
        return self.results[page_number - 1]


def _make_test_root() -> Path:
    root = Path(".runtime/test-pdf-parser") / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def _create_pdf(path: Path, pages: list[str]) -> None:
    document = fitz.open()
    for text in pages:
        page = document.new_page()
        page.insert_text((72, 72), text, fontsize=18)
    document.save(path)
    document.close()


def test_parse_pdf_uses_vision_client_for_each_page() -> None:
    root = _make_test_root()
    pdf_path = root / "lesson.pdf"
    _create_pdf(pdf_path, ["Page one", "Page two"])
    client = _FakeVisionClient(
        [
            VisionPageResult(page_text="This apple is red.", marked_words=["apple"]),
            VisionPageResult(page_text="Banana is yellow.", marked_words=["banana"]),
        ]
    )

    result = asyncio.run(parse_pdf(pdf_path, client))

    try:
        assert len(client.calls) == 2
        assert [page_number for page_number, _ in client.calls] == [1, 2]
        assert all(image_bytes for _, image_bytes in client.calls)
        assert result.full_text == "This apple is red.\nBanana is yellow."
        assert [item.text for item in result.sentences] == ["This apple is red.", "Banana is yellow."]
        assert [item.page_number for item in result.sentences] == [1, 2]
        assert [item.word.lower() for item in result.words] == ["apple", "banana"]
        assert {item.source for item in result.words} == {"pdf:qwen_vl"}
        assert [item.page_hint for item in result.words] == [1, 2]
        assert [page.page_number for page in result.pages] == [1, 2]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_parse_pdf_preserves_phrase_items() -> None:
    root = _make_test_root()
    pdf_path = root / "lesson.pdf"
    _create_pdf(pdf_path, ["Page one"])
    client = _FakeVisionClient(
        [
            VisionPageResult(
                page_text="Apple appears here.",
                marked_words=["Apple", "apple", "growth mindset"],
            )
        ]
    )

    result = asyncio.run(parse_pdf(pdf_path, client))

    try:
        assert [item.word for item in result.words] == ["Apple", "growth mindset"]
        assert [item.page_hint for item in result.words] == [1, 1]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_parse_pdf_allows_empty_marked_words() -> None:
    root = _make_test_root()
    pdf_path = root / "lesson.pdf"
    _create_pdf(pdf_path, ["Page one"])
    client = _FakeVisionClient([VisionPageResult(page_text="Only body text.", marked_words=[])])

    result = asyncio.run(parse_pdf(pdf_path, client))

    try:
        assert result.full_text == "Only body text."
        assert [item.text for item in result.sentences] == ["Only body text."]
        assert result.words == []
    finally:
        shutil.rmtree(root, ignore_errors=True)
