from __future__ import annotations

from pathlib import Path

from app.models.domain import DocumentParseResult
from app.models.settings import Settings
from app.services.document.docx import parse_docx
from app.services.document.pdf import PageVisionClient, parse_pdf
from app.services.vision import SiliconFlowVisionClient


class UnsupportedDocumentError(ValueError):
    """Raised when the teaching document type is not supported."""


class DocumentService:
    def __init__(self, settings: Settings, vision_client: PageVisionClient | None = None) -> None:
        self.settings = settings
        self.vision_client = vision_client or SiliconFlowVisionClient(settings)

    async def parse(self, path: Path) -> DocumentParseResult:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return await parse_pdf(path, self.vision_client)
        if suffix == ".docx":
            return parse_docx(path)
        if suffix == ".doc":
            raise UnsupportedDocumentError("暂不支持 .doc 文件，请先另存为 .docx 后再上传。")
        raise UnsupportedDocumentError(f"暂不支持的教材文件类型: {path.suffix}")
