from app.models.domain import DocumentPage, SentenceOccurrence
from app.utils.text import (
    build_sentence_occurrences,
    clean_sentence_occurrences,
    dedupe_preserve_order,
    find_sentence_for_word,
    find_sentences_for_word,
    find_term_spans,
    merge_words,
    parse_words_text,
)


def test_merge_words_is_case_insensitive():
    assert merge_words(["Apple", "pear"], ["apple", "banana"]) == ["Apple", "pear", "banana"]


def test_find_sentences_for_word_matches_boundaries():
    sentences = [
        "This apple is red.",
        "Pineapple cakes are sweet.",
        "An APPLE a day keeps the doctor away.",
    ]
    assert find_sentences_for_word(sentences, "apple") == [
        "This apple is red.",
        "An APPLE a day keeps the doctor away.",
    ]


def test_find_sentence_for_word_returns_first_sentence_occurrence():
    sentences = [
        SentenceOccurrence(text="This apple is red.", order=0, page_number=2),
        SentenceOccurrence(text="An APPLE a day keeps the doctor away.", order=1, page_number=5),
    ]

    result = find_sentence_for_word(sentences, "apple")

    assert result == sentences[0]


def test_find_term_spans_matches_all_occurrences_without_false_positives():
    text = "Apple pie and apple juice are better than pineapple."

    spans = find_term_spans(text, "apple")

    assert [text[start:end] for start, end in spans] == ["Apple", "apple"]


def test_find_term_spans_matches_phrases_case_insensitively():
    text = "A Growth Mindset helps. Another growth mindset example appears here."

    spans = find_term_spans(text, "growth mindset")

    assert [text[start:end] for start, end in spans] == ["Growth Mindset", "growth mindset"]


def test_build_sentence_occurrences_preserves_page_numbers():
    pages = [
        DocumentPage(text="This apple is red. Banana is yellow.", page_number=1),
        DocumentPage(text="Pears are green.", page_number=2),
    ]

    results = build_sentence_occurrences(pages)

    assert [item.text for item in results] == [
        "This apple is red.",
        "Banana is yellow.",
        "Pears are green.",
    ]
    assert [item.page_number for item in results] == [1, 1, 2]
    assert [item.order for item in results] == [0, 1, 2]


def test_clean_sentence_occurrences_removes_question_numbers_and_options():
    sentences = [
        SentenceOccurrence(
            text="2 You should ride your bike on the left to make space for A people on motorbikes.",
            order=0,
            page_number=2,
        ),
        SentenceOccurrence(text="B people cycling more quickly.", order=1, page_number=2),
        SentenceOccurrence(text="C people coming the other way.", order=2, page_number=2),
    ]

    cleaned = clean_sentence_occurrences(sentences)

    assert [item.text for item in cleaned] == ["You should ride your bike on the left to make space for"]


def test_clean_sentence_occurrences_removes_leading_option_letters_before_question_number():
    sentences = [
        SentenceOccurrence(
            text="A B C 8 Who was given a prize for completing an activity?",
            order=0,
            page_number=5,
        ),
        SentenceOccurrence(
            text="A B C 10 Who plans to return to the museum in the future?",
            order=1,
            page_number=5,
        ),
        SentenceOccurrence(
            text="A B C 13 Who was allowed to hold some things in the museum?",
            order=2,
            page_number=5,
        ),
    ]

    cleaned = clean_sentence_occurrences(sentences)

    assert [item.text for item in cleaned] == [
        "Who was given a prize for completing an activity?",
        "Who plans to return to the museum in the future?",
        "Who was allowed to hold some things in the museum?",
    ]


def test_clean_sentence_occurrences_drops_pure_option_block():
    sentences = [
        SentenceOccurrence(
            text="19 A collect B ask C give 20 A travelled B took C arrived 21 A angry B worried C afraid.",
            order=0,
            page_number=7,
        )
    ]

    cleaned = clean_sentence_occurrences(sentences)

    assert cleaned == []


def test_clean_sentence_occurrences_keeps_legitimate_article_a():
    sentences = [SentenceOccurrence(text="A growth mindset helps students learn.", order=0, page_number=3)]

    cleaned = clean_sentence_occurrences(sentences)

    assert [item.text for item in cleaned] == ["A growth mindset helps students learn."]


def test_parse_words_text_accepts_mixed_delimiters():
    assert parse_words_text("apple, banana\npear，grape") == ["apple", "banana", "pear", "grape"]


def test_dedupe_preserve_order_trims_duplicates():
    assert dedupe_preserve_order([" Example one ", "example   one", "Example two"]) == [
        "Example one",
        "Example two",
    ]
