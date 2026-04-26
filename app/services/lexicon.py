from __future__ import annotations

import asyncio
import re
import sqlite3
from functools import lru_cache

from app.models.domain import VocabMeaning
from app.models.settings import Settings
from app.services.runtime_resources import ResourceBootstrapError, ensure_lexicon_resources
from app.utils.text import normalize_word


POS_PATTERN = re.compile(
    r"^(n\.|adj\.|adv\.|vt\.|vi\.|v\.|prep\.|pron\.|conj\.|num\.|art\.|int\.|aux\.|abbr\.|phr\.|vbl\.)",
    re.IGNORECASE,
)
ARPABET_TO_IPA = {
    "AA": "ɑ",
    "AE": "æ",
    "AH": "ʌ",
    "AO": "ɔ",
    "AW": "aʊ",
    "AY": "aɪ",
    "B": "b",
    "CH": "tʃ",
    "D": "d",
    "DH": "ð",
    "EH": "e",
    "ER": "ɝ",
    "EY": "eɪ",
    "F": "f",
    "G": "ɡ",
    "HH": "h",
    "IH": "ɪ",
    "IY": "i",
    "JH": "dʒ",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "ŋ",
    "OW": "oʊ",
    "OY": "ɔɪ",
    "P": "p",
    "R": "r",
    "S": "s",
    "SH": "ʃ",
    "T": "t",
    "TH": "θ",
    "UH": "ʊ",
    "UW": "u",
    "V": "v",
    "W": "w",
    "Y": "j",
    "Z": "z",
    "ZH": "ʒ",
}
VOWEL_SYMBOLS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
IRREGULAR_LEMMAS = {
    "am": "be",
    "are": "be",
    "been": "be",
    "did": "do",
    "does": "do",
    "done": "do",
    "gone": "go",
    "had": "have",
    "has": "have",
    "made": "make",
    "saw": "see",
    "seen": "see",
    "taken": "take",
    "took": "take",
    "was": "be",
    "were": "be",
    "went": "go",
}


class LexiconServiceError(RuntimeError):
    """Raised when the local free lexicon cannot satisfy a request."""


class LexiconService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def enrich_words(self, words: list[str], document_text: str) -> dict[str, VocabMeaning]:
        del document_text
        if not words:
            return {}
        return await asyncio.to_thread(self._enrich_words_sync, words)

    def _enrich_words_sync(self, words: list[str]) -> dict[str, VocabMeaning]:
        try:
            cmudict_path, cedict_db_path = ensure_lexicon_resources(
                self.settings.runtime_root_path,
                self.settings.request_timeout_seconds,
            )
        except ResourceBootstrapError as exc:
            raise LexiconServiceError(str(exc)) from exc

        pronunciations = _load_pronunciations(str(cmudict_path))
        translations = _load_translations(str(cedict_db_path))

        results: dict[str, VocabMeaning] = {}
        for original in words:
            normalized = normalize_word(original)
            if not normalized:
                continue
            entry = _build_meaning(original, normalized, pronunciations, translations)
            if entry is not None:
                results[normalized] = entry
        return results


def _build_meaning(
    original: str,
    normalized: str,
    pronunciations: dict[str, str],
    translations: dict[str, str],
) -> VocabMeaning | None:
    for candidate in _lemma_candidates(normalized):
        translation = translations.get(candidate)
        if translation:
            pos_abbr, zh_meaning = _parse_translation(translation)
            ipa = _arpabet_to_ipa(pronunciations.get(normalized) or pronunciations.get(candidate) or "")
            return VocabMeaning(
                word=original.strip(),
                ipa=ipa,
                pos_abbr=pos_abbr,
                zh_meaning=zh_meaning,
            )
    return None


@lru_cache(maxsize=4)
def _load_pronunciations(path_str: str) -> dict[str, str]:
    path = re.sub(r"\\", "/", path_str)
    results: dict[str, str] = {}
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            word, _, pronunciation = line.partition(" ")
            normalized = normalize_word(re.sub(r"\(\d+\)$", "", word))
            if normalized and pronunciation and normalized not in results:
                results[normalized] = pronunciation.strip()
    return results


@lru_cache(maxsize=4)
def _load_translations(path_str: str) -> dict[str, str]:
    results: dict[str, str] = {}
    with sqlite3.connect(path_str) as connection:
        rows = connection.execute("SELECT english, chinese FROM words")
        for english, chinese in rows:
            normalized = normalize_word(str(english))
            if normalized and normalized not in results:
                results[normalized] = str(chinese or "").strip()
    return results


def _lemma_candidates(word: str) -> list[str]:
    candidates: list[str] = []

    def push(value: str) -> None:
        normalized = normalize_word(value)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    push(word)
    if word in IRREGULAR_LEMMAS:
        push(IRREGULAR_LEMMAS[word])
    if word.endswith("ies") and len(word) > 4:
        push(word[:-3] + "y")
    if word.endswith("ves") and len(word) > 4:
        push(word[:-3] + "f")
        push(word[:-3] + "fe")
    if word.endswith("ing") and len(word) > 5:
        base = word[:-3]
        push(base)
        push(base + "e")
        if len(base) >= 2 and base[-1] == base[-2]:
            push(base[:-1])
    if word.endswith("ed") and len(word) > 4:
        base = word[:-2]
        push(base)
        push(base + "e")
        if len(base) >= 2 and base[-1] == base[-2]:
            push(base[:-1])
    if word.endswith("es") and len(word) > 4:
        push(word[:-2])
    if word.endswith("s") and len(word) > 3:
        push(word[:-1])
    if word.endswith("er") and len(word) > 4:
        base = word[:-2]
        push(base)
        push(base + "e")
        if len(base) >= 2 and base[-1] == base[-2]:
            push(base[:-1])
    if word.endswith("est") and len(word) > 5:
        base = word[:-3]
        push(base)
        push(base + "e")
        if len(base) >= 2 and base[-1] == base[-2]:
            push(base[:-1])
    return candidates


def _parse_translation(translation: str) -> tuple[str, str]:
    cleaned = translation.replace("\n", ";").strip()
    cleaned = re.sub(
        r"(?<!^)(?=(n\.|adj\.|adv\.|vt\.|vi\.|v\.|prep\.|pron\.|conj\.|num\.|art\.|int\.|aux\.|abbr\.|phr\.|vbl\.))",
        ";",
        cleaned,
        flags=re.IGNORECASE,
    )
    segments = [segment.strip() for segment in re.split(r"[;,，；/]", cleaned) if segment.strip()]
    fallback = cleaned.strip()

    for segment in segments:
        pos_abbr = _extract_pos(segment)
        meaning = _clean_meaning(segment)
        if meaning:
            return pos_abbr, meaning
    return "", _clean_meaning(fallback)


def _extract_pos(segment: str) -> str:
    match = POS_PATTERN.match(segment.strip())
    if not match:
        return ""
    value = match.group(1).lower()
    if value in {"vt.", "vi.", "vbl."}:
        return "v."
    return value


def _clean_meaning(segment: str) -> str:
    text = segment.strip()
    text = re.sub(r"^\[[^\]]+\]", "", text).strip()
    text = POS_PATTERN.sub("", text, count=1).strip()
    text = text.lstrip("：:，,;； ").strip()
    return text


def _arpabet_to_ipa(pronunciation: str) -> str:
    if not pronunciation:
        return ""
    parts: list[str] = []
    pending_onset = ""
    for token in pronunciation.split():
        stress = ""
        base = token
        if token and token[-1].isdigit():
            base = token[:-1]
            if base in VOWEL_SYMBOLS:
                stress = "ˈ" if token[-1] == "1" else "ˌ" if token[-1] == "2" else ""
        ipa = _arpabet_symbol_to_ipa(base, token[-1] if token and token[-1].isdigit() else "")
        if not ipa:
            continue
        if base in VOWEL_SYMBOLS:
            parts.append(stress + pending_onset + ipa)
            pending_onset = ""
        else:
            pending_onset += ipa
    if pending_onset:
        parts.append(pending_onset)
    return "/" + "".join(parts) + "/" if parts else ""


def _arpabet_symbol_to_ipa(base: str, stress_digit: str) -> str:
    if base == "AH" and stress_digit == "0":
        return "ə"
    if base == "ER" and stress_digit == "0":
        return "ɚ"
    return ARPABET_TO_IPA.get(base, "")
