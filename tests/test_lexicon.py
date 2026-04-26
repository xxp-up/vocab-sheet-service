from app.services.audio import _build_vosk_grammar
from app.services.lexicon import _arpabet_to_ipa, _lemma_candidates, _parse_translation


def test_arpabet_to_ipa_converts_stress_marks():
    assert _arpabet_to_ipa("AE1 P AH0 L") == "/ˈæpəl/"


def test_parse_translation_extracts_pos_and_meaning():
    pos_abbr, zh_meaning = _parse_translation("n.苹果,似苹果的果实")
    assert pos_abbr == "n."
    assert zh_meaning == "苹果"


def test_parse_translation_splits_stuck_pos_prefixes():
    pos_abbr, zh_meaning = _parse_translation("adj.较好的adv.更好的,更多的")
    assert pos_abbr == "adj."
    assert zh_meaning == "较好的"


def test_lemma_candidates_include_common_inflections():
    assert "study" in _lemma_candidates("studies")
    assert "run" in _lemma_candidates("running")
    assert "plan" in _lemma_candidates("planned")


def test_build_vosk_grammar_dedupes_and_adds_unk():
    grammar = _build_vosk_grammar(["Apple", "apple", "banana"])
    assert grammar == '["apple", "banana", "[unk]"]'
