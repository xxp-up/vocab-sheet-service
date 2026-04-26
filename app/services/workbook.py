from __future__ import annotations

from copy import copy
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont

from app.models.domain import VocabRow
from app.utils.text import find_term_spans


EXPECTED_HEADERS = ["序号", "单词", "音标", "词性", "中文意思", "例句", "例句在教材中出现的页数"]
DEFAULT_TEMPLATE_NAME = "test 6单词表模板.xlsx"
DEFAULT_TEMPLATE_PATH = Path(__file__).resolve().parents[2] / "template" / DEFAULT_TEMPLATE_NAME
HIGHLIGHT_FONT = InlineFont(color="FFFF0000")


class WorkbookTemplateError(RuntimeError):
    """Raised when the fixed workbook template is unavailable or invalid."""


class WorkbookService:
    def __init__(self, template_path: Path | None = None) -> None:
        self.template_path = template_path or DEFAULT_TEMPLATE_PATH

    def fill_template(self, rows: list[VocabRow], output_path: Path) -> None:
        if not self.template_path.exists():
            raise WorkbookTemplateError(f"固定模板不存在: {self.template_path}")

        workbook = load_workbook(self.template_path)
        try:
            if "Sheet1" not in workbook.sheetnames:
                raise WorkbookTemplateError("固定模板缺少 Sheet1 工作表。")

            sheet = workbook["Sheet1"]
            self._validate_headers(sheet)
            self._clear_existing_rows(sheet)

            for index, row in enumerate(rows, start=3):
                sheet.cell(row=index, column=1, value=index - 2)
                sheet.cell(row=index, column=2, value=row.word)
                sheet.cell(row=index, column=3, value=row.ipa)
                sheet.cell(row=index, column=4, value=row.pos_abbr)
                sheet.cell(row=index, column=5, value=row.zh_meaning)
                sheet.cell(row=index, column=6, value=_build_example_value(row.example, row.word))
                sheet.cell(row=index, column=7, value=row.example_page)

                alignment = copy(sheet.cell(row=index, column=6).alignment)
                alignment.wrap_text = True
                sheet.cell(row=index, column=6).alignment = alignment

            workbook.save(output_path)
        finally:
            workbook.close()

    def _validate_headers(self, sheet) -> None:
        actual = [sheet.cell(row=2, column=index).value for index in range(1, 8)]
        if actual != EXPECTED_HEADERS:
            raise WorkbookTemplateError(
                f"固定模板表头不符合预期。第2行应为 {EXPECTED_HEADERS}，实际为 {actual}"
            )

    def _clear_existing_rows(self, sheet) -> None:
        for row_index in range(3, sheet.max_row + 1):
            for column_index in range(1, 8):
                sheet.cell(row=row_index, column=column_index, value=None)


def _build_example_value(example: str, term: str) -> str | CellRichText:
    spans = find_term_spans(example, term)
    if not spans:
        return example

    parts: list[str | TextBlock] = []
    cursor = 0
    for start, end in spans:
        if start > cursor:
            parts.append(example[cursor:start])
        parts.append(TextBlock(HIGHLIGHT_FONT, example[start:end]))
        cursor = end
    if cursor < len(example):
        parts.append(example[cursor:])
    return CellRichText(*parts)
