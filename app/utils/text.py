from __future__ import annotations

import re
from collections import OrderedDict

from app.models.domain import DocumentPage, SentenceOccurrence


WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z'/-]*")
LETTER_PATTERN = re.compile(r"[A-Za-z]")
WHITESPACE_PATTERN = re.compile(r"\s+")
OPTION_CONTINUATION_PATTERN = re.compile(r"^[B-C]\s+[a-z].*[.!?]?$")
OPTION_BLOCK_PATTERN = re.compile(
    r"^(?:\d{1,2}\s+)?A\s+[a-z].*?\sB\s+[a-z].*?(?:\sC\s+[a-z].*)?$",
    re.IGNORECASE,
)


def normalize_word(word: str) -> str:
    cleaned = re.sub(r"(^[^A-Za-z]+|[^A-Za-z]+$)", "", collapse_whitespace(word))
    return cleaned.lower()


def extract_candidate_words(text: str) -> list[str]:
    seen: OrderedDict[str, str] = OrderedDict()
    for match in WORD_PATTERN.finditer(text):
        candidate = match.group(0)
        normalized = normalize_word(candidate)
        if normalized:
            seen.setdefault(normalized, candidate)
    return list(seen.values())


def split_sentences(text: str) -> list[str]:
    return [item.text for item in split_sentence_occurrences(text)]


def collapse_whitespace(text: str) -> str:
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def clean_marked_term(text: str) -> str:
    return re.sub(r"(^[^A-Za-z]+|[^A-Za-z]+$)", "", collapse_whitespace(text)).strip()


def has_english_content(text: str) -> bool:
    return bool(LETTER_PATTERN.search(text))


def split_sentence_occurrences(
    text: str,
    *,
    page_number: int | None = None,
    order_start: int = 0,
) -> list[SentenceOccurrence]:
    collapsed = collapse_whitespace(text)
    if not collapsed:
        return []

    parts = re.split(r"(?<=[.!?])\s+", collapsed)
    results: list[SentenceOccurrence] = []
    next_order = order_start
    for part in parts:
        sentence = part.strip()
        if not sentence:
            continue
        results.append(SentenceOccurrence(text=sentence, order=next_order, page_number=page_number))
        next_order += 1
    return results


def build_sentence_occurrences(pages: list[DocumentPage]) -> list[SentenceOccurrence]:
    results: list[SentenceOccurrence] = []
    next_order = 0
    for page in pages:
        current = split_sentence_occurrences(page.text, page_number=page.page_number, order_start=next_order)
        results.extend(current)
        next_order += len(current)
    return results


def clean_sentence_occurrences(sentences: list[SentenceOccurrence]) -> list[SentenceOccurrence]:
    cleaned: list[SentenceOccurrence] = []
    skip_option_continuations = False

    for index, sentence in enumerate(sentences):
        text = collapse_whitespace(sentence.text)
        if not text:
            continue

        text = _strip_leading_question_number(text)

        if _looks_like_option_block(text):
            continue

        if skip_option_continuations and _looks_like_option_continuation(text):
            continue

        skip_option_continuations = False

        option_start = _find_embedded_option_start(text, sentences[index + 1 : index + 3])
        if option_start is not None:
            text = text[:option_start].rstrip()
            skip_option_continuations = True

        text = _tidy_sentence_text(text)
        if not text:
            continue

        cleaned.append(
            SentenceOccurrence(
                text=text,
                order=sentence.order,
                page_number=sentence.page_number,
            )
        )

    return cleaned


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: OrderedDict[str, str] = OrderedDict()
    for value in values:
        normalized = collapse_whitespace(value).lower()
        if normalized:
            seen.setdefault(normalized, value.strip())
    return list(seen.values())


def merge_words(*groups: list[str]) -> list[str]:
    seen: OrderedDict[str, str] = OrderedDict()
    for group in groups:
        for word in group:
            normalized = normalize_word(word)
            if normalized:
                seen.setdefault(normalized, word.strip())
    return list(seen.values())


def find_sentences_for_word(sentences: list[str], word: str) -> list[str]:
    matched = [sentence for sentence in sentences if find_term_spans(sentence, word)]
    return dedupe_preserve_order(matched)


def find_sentence_for_word(sentences: list[SentenceOccurrence], word: str) -> SentenceOccurrence | None:
    for sentence in sentences:
        if find_term_spans(sentence.text, word):
            return sentence
    return None


def find_term_spans(text: str, term: str) -> list[tuple[int, int]]:
    pattern = build_term_pattern(term)
    if pattern is None:
        return []
    return [(match.start(), match.end()) for match in pattern.finditer(text)]


def build_term_pattern(term: str) -> re.Pattern[str] | None:
    normalized = normalize_word(term)
    if not normalized:
        return None

    pieces = [re.escape(part) for part in normalized.split()]
    if not pieces:
        return None

    body = r"\s+".join(pieces)
    return re.compile(rf"(?<![A-Za-z]){body}(?![A-Za-z])", re.IGNORECASE)


def is_multiword_term(term: str) -> bool:
    return len(normalize_word(term).split()) > 1


def parse_words_text(words_text: str | None) -> list[str]:
    if not words_text:
        return []
    chunks = re.split(r"[\s,;，；、]+", words_text)
    merged = [chunk for chunk in chunks if chunk.strip()]
    return merge_words(merged)


def _strip_leading_question_number(text: str) -> str:
    return re.sub(r"^\s*(?:(?:[A-C]\s*){1,3})?\d{1,2}[.)]?\s+(?=[A-Z(])", "", text)


def _find_embedded_option_start(text: str, upcoming: list[SentenceOccurrence]) -> int | None:
    inline_options = re.search(r"\sA\s+(?=[a-z]).*?\sB\s+(?=[a-z]).*?(?:\sC\s+(?=[a-z]).*)?$", text)
    if inline_options is not None:
        return inline_options.start()

    match = re.search(r"\sA\s+(?=[a-z])", text)
    if match is None:
        return None

    upcoming_texts = [collapse_whitespace(item.text) for item in upcoming if collapse_whitespace(item.text)]
    if any(_looks_like_option_continuation(item) for item in upcoming_texts):
        return match.start()
    return None


def _looks_like_option_continuation(text: str) -> bool:
    return bool(OPTION_CONTINUATION_PATTERN.fullmatch(text))


def _looks_like_option_block(text: str) -> bool:
    return bool(OPTION_BLOCK_PATTERN.fullmatch(text))


def _tidy_sentence_text(text: str) -> str:
    cleaned = collapse_whitespace(text)
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)
    cleaned = re.sub(r"\s+\d{1,2}$", "", cleaned)
    cleaned = cleaned.strip(" -")
    return cleaned
