from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

import httpx

from app.models.domain import DocumentPage, DocumentParseResult, SentenceOccurrence
from app.models.settings import Settings
from app.utils.text import clean_sentence_occurrences, collapse_whitespace


PART4_RANGE = range(19, 25)
PART5_RANGE = range(25, 31)
MATCH_WORD_PATTERN = re.compile(r"[a-z]+(?:'[a-z]+)?")
MIN_SENTENCE_MATCH_SCORE = 0.85

SYSTEM_PROMPT = (
    "You solve Cambridge-style English textbook exercises. "
    "Return JSON only. Focus only on Part 4 questions 19-24 and Part 5 questions 25-30. "
    'Return an object with exactly one key: "questions". '
    '"questions" must be an array of objects with exactly these keys: '
    '"part" (integer), "number" (integer), "sentence_with_blank" (string), '
    '"restored_sentence" (string), and "answer" (string). '
    '"sentence_with_blank" must closely match the original sentence containing the blank marker. '
    '"restored_sentence" must be the fully completed sentence with the correct answer filled in. '
    'For Part 4, "answer" should be the completed word or phrase chosen from the options. '
    'For Part 5, "answer" should be the word filled into the blank. '
    "Skip any question you cannot solve confidently."
)

USER_PROMPT_TEMPLATE = (
    "Analyze the extracted textbook text below.\n"
    "Restore only these exercises:\n"
    "- Part 4 questions 19-24: use the answer options to complete each sentence.\n"
    "- Part 5 questions 25-30: understand the whole text and fill each blank with the correct word.\n"
    "Return JSON only.\n\n"
    "{context}"
)


@dataclass(slots=True)
class RestoredExerciseQuestion:
    part: int
    number: int
    sentence_with_blank: str
    restored_sentence: str
    answer: str = ""


class ExerciseRestoreServiceError(RuntimeError):
    """Raised when the exercise restore helper cannot return a usable result."""


class ExerciseRestoreService:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = settings.require_vision_api_key()
        self.base_url = settings.vision_base_url.rstrip("/")
        self.model = settings.vision_model
        self.timeout = settings.effective_vision_timeout_seconds
        self.transport = transport

    async def restore_document(self, document: DocumentParseResult) -> DocumentParseResult:
        restored_sentences = [replace(sentence) for sentence in document.sentences]
        candidate_pages = [page for page in document.pages if _page_mentions_target_exercises(page.text)]

        if candidate_pages:
            try:
                questions = await self._solve_questions(candidate_pages)
            except ExerciseRestoreServiceError:
                questions = []

            if questions:
                restored_sentences = _apply_restorations(restored_sentences, questions)

        cleaned_sentences = clean_sentence_occurrences(restored_sentences)
        return replace(document, sentences=cleaned_sentences)

    async def _solve_questions(self, pages: list[DocumentPage]) -> list[RestoredExerciseQuestion]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": USER_PROMPT_TEMPLATE.format(context=_format_page_context(pages)),
                },
            ],
            "temperature": 0,
            "max_tokens": 2048,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
            ) as client:
                response = await client.post("/chat/completions", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise ExerciseRestoreServiceError("Exercise restore solver timed out.") from exc
        except httpx.HTTPStatusError as exc:
            raise ExerciseRestoreServiceError(
                f"Exercise restore solver failed with HTTP {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise ExerciseRestoreServiceError("Exercise restore solver response could not be decoded.") from exc

        content = _extract_message_content(data)
        return _parse_questions(content)


def _format_page_context(pages: list[DocumentPage]) -> str:
    blocks: list[str] = []
    for page in pages:
        label = f"Page {page.page_number}" if page.page_number is not None else "Page unknown"
        blocks.append(f"[{label}]\n{page.text}")
    return "\n\n".join(blocks)


def _page_mentions_target_exercises(text: str) -> bool:
    collapsed = collapse_whitespace(text)
    if not collapsed:
        return False

    if re.search(r"\bpart\s*4\b", collapsed, re.IGNORECASE):
        return True
    if re.search(r"\bpart\s*5\b", collapsed, re.IGNORECASE):
        return True
    return any(re.search(rf"\({number}\)", collapsed) for number in list(PART4_RANGE) + list(PART5_RANGE))


def _apply_restorations(
    sentences: list[SentenceOccurrence],
    questions: list[RestoredExerciseQuestion],
) -> list[SentenceOccurrence]:
    restored = [replace(sentence) for sentence in sentences]
    for question in sorted(questions, key=lambda item: (item.part, item.number)):
        index = _find_sentence_index(restored, question)
        if index is None:
            continue
        merged_text = _merge_restored_sentence(restored[index].text, question)
        restored[index] = replace(restored[index], text=merged_text)
    return restored


def _find_sentence_index(
    sentences: list[SentenceOccurrence],
    question: RestoredExerciseQuestion,
) -> int | None:
    marker_pattern = re.compile(rf"\({question.number}\)")
    for index, sentence in enumerate(sentences):
        if marker_pattern.search(sentence.text):
            return index

    blank_text = _normalized_sentence(question.sentence_with_blank)
    if not blank_text:
        blank_text = _normalized_sentence(question.restored_sentence)

    best_index: int | None = None
    best_score = 0.0
    for index, sentence in enumerate(sentences):
        candidate = _normalized_sentence(sentence.text)
        if candidate and (candidate in blank_text or blank_text in candidate):
            return index

        score = max(
            _sentence_match_score(sentence.text, reference)
            for reference in (question.sentence_with_blank, question.restored_sentence)
            if reference
        )
        if score > best_score:
            best_index = index
            best_score = score

    if best_index is not None and best_score >= MIN_SENTENCE_MATCH_SCORE:
        return best_index
    return None


def _normalized_sentence(text: str) -> str:
    return collapse_whitespace(text).lower()


def _merge_restored_sentence(current_text: str, question: RestoredExerciseQuestion) -> str:
    updated = current_text
    if question.answer:
        updated = _replace_blank_with_answer(updated, question.number, question.answer)
    normalized_updated = collapse_whitespace(updated)

    if _has_blank_marker(normalized_updated, question.number):
        return collapse_whitespace(question.restored_sentence)

    if question.restored_sentence:
        restored_normalized = collapse_whitespace(question.restored_sentence)
        if _text_still_matches_question(normalized_updated, question):
            return restored_normalized

    return normalized_updated


def _replace_blank_with_answer(text: str, number: int, answer: str) -> str:
    pattern = re.compile(rf"\({number}\)\s*\.{{2,}}")
    replaced = pattern.sub(f" {answer} ", text, count=1)
    if replaced != text:
        return collapse_whitespace(replaced)

    fallback = re.compile(rf"\({number}\)")
    replaced = fallback.sub(f" {answer} ", text, count=1)
    return collapse_whitespace(replaced)


def _has_blank_marker(text: str, number: int) -> bool:
    return bool(re.search(rf"\({number}\)\s*(?:\.{{2,}})?", text))


def _text_still_matches_question(text: str, question: RestoredExerciseQuestion) -> bool:
    references = [question.sentence_with_blank, question.restored_sentence]
    return max((_sentence_match_score(text, reference) for reference in references if reference), default=0.0) >= MIN_SENTENCE_MATCH_SCORE


def _sentence_match_score(candidate: str, reference: str) -> float:
    candidate_text = _comparison_text(candidate)
    reference_text = _comparison_text(reference)
    if not candidate_text or not reference_text:
        return 0.0

    if candidate_text == reference_text:
        return 1.0

    if candidate_text in reference_text or reference_text in candidate_text:
        return min(len(candidate_text), len(reference_text)) / max(len(candidate_text), len(reference_text))

    sequence_score = SequenceMatcher(None, candidate_text, reference_text).ratio()
    candidate_tokens = set(candidate_text.split())
    reference_tokens = set(reference_text.split())
    overlap_score = len(candidate_tokens & reference_tokens) / max(len(candidate_tokens), len(reference_tokens))
    return max(sequence_score, overlap_score)


def _comparison_text(text: str) -> str:
    collapsed = collapse_whitespace(text)
    if not collapsed:
        return ""

    collapsed = re.sub(r"\(\s*\d{1,2}\s*\)", " ", collapsed)
    collapsed = re.sub(r"\.{2,}", " ", collapsed)
    collapsed = re.sub(r"\bpart\s*[45]\b", " ", collapsed, flags=re.IGNORECASE)
    return " ".join(MATCH_WORD_PATTERN.findall(collapsed.lower()))


def _extract_message_content(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ExerciseRestoreServiceError("Exercise restore solver response is not a JSON object.")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ExerciseRestoreServiceError("Exercise restore solver response is missing choices.")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise ExerciseRestoreServiceError("Exercise restore solver response has an invalid first choice.")

    message = choice.get("message")
    if not isinstance(message, dict):
        raise ExerciseRestoreServiceError("Exercise restore solver response is missing message.")

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, dict)]
        merged = "".join(texts).strip()
        if merged:
            return merged

    raise ExerciseRestoreServiceError("Exercise restore solver response is missing text content.")


def _parse_questions(content: str) -> list[RestoredExerciseQuestion]:
    candidate = _extract_json_object(content)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ExerciseRestoreServiceError("Exercise restore solver returned invalid JSON.") from exc

    if not isinstance(data, dict):
        raise ExerciseRestoreServiceError("Exercise restore solver result is not a JSON object.")

    questions = data.get("questions")
    if not isinstance(questions, list):
        raise ExerciseRestoreServiceError("Exercise restore solver result is missing questions.")

    results: list[RestoredExerciseQuestion] = []
    for item in questions:
        if not isinstance(item, dict):
            continue

        part = item.get("part")
        number = item.get("number")
        sentence_with_blank = item.get("sentence_with_blank")
        restored_sentence = item.get("restored_sentence")
        answer = item.get("answer", "")

        if not isinstance(part, int) or part not in {4, 5}:
            continue
        if not isinstance(number, int) or not _number_belongs_to_part(part, number):
            continue
        if not isinstance(sentence_with_blank, str) or not collapse_whitespace(sentence_with_blank):
            continue
        if not isinstance(restored_sentence, str) or not collapse_whitespace(restored_sentence):
            continue
        if not isinstance(answer, str):
            answer = ""

        results.append(
            RestoredExerciseQuestion(
                part=part,
                number=number,
                sentence_with_blank=collapse_whitespace(sentence_with_blank),
                restored_sentence=collapse_whitespace(restored_sentence),
                answer=collapse_whitespace(answer),
            )
        )
    return results


def _number_belongs_to_part(part: int, number: int) -> bool:
    if part == 4:
        return number in PART4_RANGE
    if part == 5:
        return number in PART5_RANGE
    return False


def _extract_json_object(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            stripped = "\n".join(lines[1:-1]).strip()

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start : end + 1]
    return stripped
