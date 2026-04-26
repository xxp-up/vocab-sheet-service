from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import httpx

from app.models.settings import Settings


DEFAULT_VISION_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_VISION_MODEL = "Qwen/Qwen3-VL-32B-Instruct"

SYSTEM_PROMPT = (
    "You extract structured data from textbook PDF pages. "
    "Return a single JSON object and nothing else. "
    'The object must have exactly these keys: "page_text" (string), "marked_words" (array of strings). '
    '"page_text" must contain the English text visible on the page. '
    '"marked_words" must include only English terms that are explicitly emphasized on the page, '
    "such as red text, underline, boxes, annotations, or other obvious markings. "
    "If multiple emphasized English words appear together as one continuous phrase, keep them in a single item. "
    "Do not split a continuous emphasized phrase into separate words. "
    "Do not include ordinary words that are not emphasized."
)

USER_PROMPT = (
    "Analyze this PDF page image and return JSON only. "
    'Use the shape {"page_text":"...","marked_words":["..."]}.'
)


@dataclass(slots=True)
class VisionPageResult:
    page_text: str
    marked_words: list[str]


class VisionServiceError(RuntimeError):
    """Raised when the upstream vision service cannot return a usable result."""


class SiliconFlowVisionClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_key = settings.require_vision_api_key()
        self.base_url = settings.vision_base_url.rstrip("/")
        self.model = settings.vision_model
        self.timeout = settings.effective_vision_timeout_seconds
        self.transport = transport

    async def extract_page(self, image_bytes: bytes, page_number: int) -> VisionPageResult:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": _image_data_url(image_bytes),
                                "detail": "high",
                            },
                        },
                    ],
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
            raise VisionServiceError(f"Vision model timed out while processing page {page_number}.") from exc
        except httpx.HTTPStatusError as exc:
            raise VisionServiceError(
                f"Vision model request failed for page {page_number} with HTTP {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            raise VisionServiceError(f"Vision model response could not be decoded for page {page_number}.") from exc

        content = _extract_message_content(data, page_number)
        return _parse_page_result(content, page_number)


def _image_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _extract_message_content(payload: object, page_number: int) -> str:
    if not isinstance(payload, dict):
        raise VisionServiceError(f"Vision response for page {page_number} is not a JSON object.")

    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise VisionServiceError(f"Vision response for page {page_number} is missing choices.")

    choice = choices[0]
    if not isinstance(choice, dict):
        raise VisionServiceError(f"Vision response for page {page_number} has an invalid first choice.")

    message = choice.get("message")
    if not isinstance(message, dict):
        raise VisionServiceError(f"Vision response for page {page_number} is missing message.")

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [item.get("text", "") for item in content if isinstance(item, dict)]
        merged = "".join(texts).strip()
        if merged:
            return merged

    raise VisionServiceError(f"Vision response for page {page_number} is missing text content.")


def _parse_page_result(content: str, page_number: int) -> VisionPageResult:
    candidate = _extract_json_object(content)
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise VisionServiceError(f"Vision model returned invalid JSON for page {page_number}.") from exc

    if not isinstance(data, dict):
        raise VisionServiceError(f"Vision result for page {page_number} is not a JSON object.")

    page_text = data.get("page_text")
    marked_words = data.get("marked_words")
    if not isinstance(page_text, str):
        raise VisionServiceError(f"Vision result for page {page_number} is missing page_text.")
    if not isinstance(marked_words, list) or not all(isinstance(item, str) for item in marked_words):
        raise VisionServiceError(f"Vision result for page {page_number} is missing marked_words.")

    return VisionPageResult(page_text=page_text.strip(), marked_words=[item.strip() for item in marked_words if item.strip()])


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
