from __future__ import annotations

import asyncio
import json

import httpx

from app.models.domain import DocumentPage, DocumentParseResult, SentenceOccurrence
from app.models.settings import Settings
from app.services.exercise_restore import ExerciseRestoreService


def _make_settings() -> Settings:
    return Settings(vision_api_key="test-key")


def test_restore_document_replaces_part4_blank_sentence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content.decode("utf-8"))
        assert payload["model"] == "Qwen/Qwen3-VL-32B-Instruct"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "questions": [
                                        {
                                            "part": 4,
                                            "number": 19,
                                            "sentence_with_blank": "My parents went to Reception to (19) ... our room key.",
                                            "restored_sentence": "My parents went to Reception to collect our room key.",
                                            "answer": "collect",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    service = ExerciseRestoreService(_make_settings(), transport=httpx.MockTransport(handler))
    document = DocumentParseResult(
        source_type="pdf",
        full_text="Part 4 My parents went to Reception to (19) ... our room key. 19 A collect B ask C give",
        pages=[
            DocumentPage(
                text="Part 4 My parents went to Reception to (19) ... our room key. 19 A collect B ask C give",
                page_number=7,
            )
        ],
        sentences=[
            SentenceOccurrence(
                text="My parents went to Reception to (19) ... our room key.",
                order=0,
                page_number=7,
            )
        ],
    )

    result = asyncio.run(service.restore_document(document))

    assert result.sentences[0].text == "My parents went to Reception to collect our room key."
    assert result.sentences[0].page_number == 7


def test_restore_document_replaces_part5_blank_sentence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "questions": [
                                        {
                                            "part": 5,
                                            "number": 26,
                                            "sentence_with_blank": "Once (26)....... month, we meet after school.",
                                            "restored_sentence": "Once a month, we meet after school.",
                                            "answer": "a",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    service = ExerciseRestoreService(_make_settings(), transport=httpx.MockTransport(handler))
    document = DocumentParseResult(
        source_type="pdf",
        full_text="Part 5 Once (26)....... month, we meet after school.",
        pages=[DocumentPage(text="Part 5 Once (26)....... month, we meet after school.", page_number=4)],
        sentences=[SentenceOccurrence(text="Once (26)....... month, we meet after school.", order=0, page_number=4)],
    )

    result = asyncio.run(service.restore_document(document))

    assert result.sentences[0].text == "Once a month, we meet after school."
    assert result.sentences[0].page_number == 4


def test_restore_document_replaces_part5_multiple_blanks_in_same_sentence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "questions": [
                                        {
                                            "part": 5,
                                            "number": 27,
                                            "sentence_with_blank": "We watch a movie, then one (27) ............ us writes an article about the film for the school website.",
                                            "restored_sentence": "We watch a movie, then one of us writes an article about the film for the school website.",
                                            "answer": "of",
                                        },
                                        {
                                            "part": 5,
                                            "number": 28,
                                            "sentence_with_blank": "She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists.",
                                            "restored_sentence": "She liked it and sent me an email, saying it was good enough to enter a competition for young journalists.",
                                            "answer": "and",
                                        },
                                        {
                                            "part": 5,
                                            "number": 29,
                                            "sentence_with_blank": "She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists.",
                                            "restored_sentence": "She liked it and sent me an email, saying it was good enough to enter a competition for young journalists.",
                                            "answer": "to",
                                        },
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    service = ExerciseRestoreService(_make_settings(), transport=httpx.MockTransport(handler))
    document = DocumentParseResult(
        source_type="pdf",
        full_text=(
            "Part 5 We watch a movie, then one (27) ............ us writes an article about the film for the school website. "
            "She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists."
        ),
        pages=[
            DocumentPage(
                text=(
                    "Part 5 We watch a movie, then one (27) ............ us writes an article about the film for the school website. "
                    "She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists."
                ),
                page_number=8,
            )
        ],
        sentences=[
            SentenceOccurrence(
                text="We watch a movie, then one (27) ............ us writes an article about the film for the school website.",
                order=0,
                page_number=8,
            ),
            SentenceOccurrence(
                text="She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists.",
                order=1,
                page_number=8,
            ),
        ],
    )

    result = asyncio.run(service.restore_document(document))

    assert result.sentences[0].text == "We watch a movie, then one of us writes an article about the film for the school website."
    assert result.sentences[1].text == "She liked it and sent me an email, saying it was good enough to enter a competition for young journalists."


def test_restore_document_replaces_ocr_noisy_exercise_sentences_with_restored_sentence() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "questions": [
                                        {
                                            "part": 4,
                                            "number": 19,
                                            "sentence_with_blank": "When we got to our hotel, my parents went to Reception to (19) ... our room key.",
                                            "restored_sentence": "When we got to our hotel, my parents went to Reception to collect our room key.",
                                            "answer": "collect",
                                        },
                                        {
                                            "part": 4,
                                            "number": 20,
                                            "sentence_with_blank": "The hotel rooms were around a beautiful lake, so a member of staff (20) ... us by boat to our room.",
                                            "restored_sentence": "The hotel rooms were around a beautiful lake, so a member of staff took us by boat to our room.",
                                            "answer": "took",
                                        },
                                        {
                                            "part": 4,
                                            "number": 24,
                                            "sentence_with_blank": "My brother was (24) ... of it, but it didn't come anywhere near us.",
                                            "restored_sentence": "My brother was afraid of it, but it didn't come anywhere near us.",
                                            "answer": "afraid",
                                        },
                                        {
                                            "part": 5,
                                            "number": 27,
                                            "sentence_with_blank": "We watch a movie, then one (27) ............ us writes an article about the film for the school website.",
                                            "restored_sentence": "We watch a movie, then one of us writes an article about the film for the school website.",
                                            "answer": "of",
                                        },
                                        {
                                            "part": 5,
                                            "number": 28,
                                            "sentence_with_blank": "She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists.",
                                            "restored_sentence": "She liked it and sent me an email, saying it was good enough to enter a competition for young journalists.",
                                            "answer": "and",
                                        },
                                        {
                                            "part": 5,
                                            "number": 29,
                                            "sentence_with_blank": "She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists.",
                                            "restored_sentence": "She liked it and sent me an email, saying it was good enough to enter a competition for young journalists.",
                                            "answer": "to",
                                        },
                                    ]
                                }
                            )
                        }
                    }
                ]
            },
        )

    service = ExerciseRestoreService(_make_settings(), transport=httpx.MockTransport(handler))
    document = DocumentParseResult(
        source_type="pdf",
        full_text=(
            "Part 4 When we got to our hotel, my parents went to Reception to (19) ... our room key. "
            "The hotel rooms were around a beautiful lake, so a member of staff (20) ... us by boat to our room. "
            "My brother was (24) ... of it, but it didn't come anywhere near us. "
            "Part 5 We watch a movie, then one (27) ............ us writes an article about the film for the school website. "
            "She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists."
        ),
        pages=[
            DocumentPage(
                text=(
                    "Part 4 When we got to our hotel, my parents went to Reception to (19) ... our room key. "
                    "The hotel rooms were around a beautiful lake, so a member of staff (20) ... us by boat to our room. "
                    "My brother was (24) ... of it, but it didn't come anywhere near us. "
                    "Part 5 We watch a movie, then one (27) ............ us writes an article about the film for the school website. "
                    "She liked it (28) ............ sent me an email, saying it was good enough (29) ............ enter a competition for young journalists."
                ),
                page_number=8,
            )
        ],
        sentences=[
            SentenceOccurrence(
                text="When we got to our hotel, my parents went to Reception to A collect ............ our room key.",
                order=0,
                page_number=7,
            ),
            SentenceOccurrence(
                text="The hotel rooms were around a beautiful lake, so a member of staff B took ............ us by boat to our room.",
                order=1,
                page_number=7,
            ),
            SentenceOccurrence(
                text="My brother was C afraid ............ of it, but it didn't come anywhere near us.",
                order=2,
                page_number=7,
            ),
            SentenceOccurrence(
                text="We watch a movie, then one of ............ us writes an article about the film for the school website.",
                order=3,
                page_number=8,
            ),
            SentenceOccurrence(
                text="She liked it and ............ sent me an email, saying it was good enough to ............ enter a competition for young journalists.",
                order=4,
                page_number=8,
            ),
        ],
    )

    result = asyncio.run(service.restore_document(document))

    assert [item.text for item in result.sentences] == [
        "When we got to our hotel, my parents went to Reception to collect our room key.",
        "The hotel rooms were around a beautiful lake, so a member of staff took us by boat to our room.",
        "My brother was afraid of it, but it didn't come anywhere near us.",
        "We watch a movie, then one of us writes an article about the film for the school website.",
        "She liked it and sent me an email, saying it was good enough to enter a competition for young journalists.",
    ]


def test_restore_document_cleans_question_numbers_and_option_sentences() -> None:
    service = ExerciseRestoreService(_make_settings(), transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    document = DocumentParseResult(
        source_type="pdf",
        full_text="2 You should ride your bike on the left to make space for A people on motorbikes. B people cycling more quickly. C people coming the other way.",
        pages=[
            DocumentPage(
                text="2 You should ride your bike on the left to make space for A people on motorbikes. B people cycling more quickly. C people coming the other way.",
                page_number=2,
            )
        ],
        sentences=[
            SentenceOccurrence(
                text="2 You should ride your bike on the left to make space for A people on motorbikes.",
                order=0,
                page_number=2,
            ),
            SentenceOccurrence(text="B people cycling more quickly.", order=1, page_number=2),
            SentenceOccurrence(text="C people coming the other way.", order=2, page_number=2),
        ],
    )

    result = asyncio.run(service.restore_document(document))

    assert [item.text for item in result.sentences] == [
        "You should ride your bike on the left to make space for"
    ]


def test_restore_document_falls_back_to_cleaned_original_sentences_on_invalid_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]})

    service = ExerciseRestoreService(_make_settings(), transport=httpx.MockTransport(handler))
    original = DocumentParseResult(
        source_type="pdf",
        full_text="Part 4 Example (19) ... 19 A collect B ask C give",
        pages=[DocumentPage(text="Part 4 Example (19) ... 19 A collect B ask C give", page_number=3)],
        sentences=[SentenceOccurrence(text="Example (19) ... 19 A collect B ask C give", order=0, page_number=3)],
    )

    result = asyncio.run(service.restore_document(original))

    assert result.sentences[0].text == "Example (19)..."
