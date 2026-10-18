"""Document parsers — CSV/TSV / Excel / PDF / Word to structured text.

Port of the CM-agentic ``agentic-extension-documents`` (documentParse) semantics
to OpenKitsune Python. A single ``parse_document`` entry returns a
:class:`ParsedDocument` with ``format``, ``metadata``, ``tables`` and ``text``,
so callers (knowledge ingestion, API routes) share one contract.

Design notes:
- Heavy backends (pypdf / python-docx / openpyxl) are optional imports; when a
  backend is missing the parser raises :class:`MissingDependency` instead of
  failing at import time, so the rest of the knowledge module keeps working.
- File-size guard (10 MB, same as CM-agentic) protects against memory blow-ups.
- CSV auto-detects delimiter (comma / tab / semicolon).
- PDF extraction is per-page; scanned/image-only PDFs yield empty text with a
  warning in metadata.
"""

from __future__ import annotations

import csv
import io
import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB — matches CM-agentic documentParse
TEXT_CHARS_CAP = 200_000  # same ceiling as local_kb.MAX_FILE_CHARS


class ParseError(Exception):
    """Base error for document parsing."""


class MissingDependency(ParseError):
    """A required parsing backend (pypdf / python-docx / openpyxl) is missing."""


class UnsupportedFormat(ParseError):
    """The file extension is not supported by any parser."""


class FileTooLarge(ParseError):
    """The file exceeds MAX_FILE_SIZE."""


@dataclass
class ParsedDocument:
    format: str  # "CSV" | "Excel" | "PDF" | "Word"
    metadata: dict = field(default_factory=dict)
    tables: list[dict] = field(default_factory=list)  # [{name, headers, rows}]
    text: str = ""

    def render_text(self, max_chars: int = 8000) -> str:
        """Text-mode rendering: metadata + tables preview + body text."""
        parts: list[str] = []
        if self.metadata:
            lines = [f"{k}: {v}" for k, v in self.metadata.items()]
            parts.append("元信息\n" + "\n".join(lines))
        if self.tables:
            table_blocks = []
            for table in self.tables:
                block = [f"表：{table['name']}"]
                headers = table.get("headers") or []
                if headers:
                    block.append(" | ".join(str(h) for h in headers))
                for row in table.get("rows", [])[:50]:
                    block.append(" | ".join(str(c) for c in row))
                if len(table.get("rows", [])) > 50:
                    block.append(f"… 共 {len(table['rows'])} 行")
                table_blocks.append("\n".join(block))
            parts.append("\n".join(table_blocks))
        if self.text:
            parts.append("正文\n" + self.text)
        rendered = "\n\n".join(parts)
        if len(rendered) > max_chars:
            return rendered[:max_chars] + "\n…（已截断）"
        return rendered

    def render_json(self) -> dict:
        return {
            "format": self.format,
            "metadata": self.metadata,
            "tables": self.tables,
            "text": self.text,
        }


# ---------------------------------------------------------------------------
# CSV / TSV
# ---------------------------------------------------------------------------


def _parse_csv(path: Path) -> ParsedDocument:
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    text = _decode(data)
    sample = text[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t") if sample.strip() else None
    delimiter = (dialect.delimiter if dialect else ",") or ","
    delimiter_label = {"\t": "Tab", ";": "分号"}.get(delimiter, "逗号")

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    headers = rows[0] if rows else []
    body_rows = rows[1:] if rows else []
    table = {
        "name": path.stem,
        "headers": headers,
        "rows": [[str(c) for c in row] for row in body_rows],
    }
    return ParsedDocument(
        format="CSV",
        metadata={"行数": str(len(rows)), "列数": str(len(headers)), "分隔符": delimiter_label},
        tables=[table],
        text="",
    )


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def _parse_excel(path: Path) -> ParsedDocument:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise MissingDependency("解析 .xlsx 需要安装 openpyxl（pip install openpyxl）") from exc

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    tables: list[dict] = []
    total_rows = 0
    for sheet_name in workbook.sheetnames:
        sheet = workbook[sheet_name]
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            values = ["" if v is None else str(v) for v in row]
            if any(v.strip() for v in values):
                rows.append(values)
        if not rows:
            continue
        headers = rows[0]
        body = rows[1:]
        total_rows += len(body)
        tables.append({"name": sheet_name, "headers": headers, "rows": body})
    workbook.close()
    return ParsedDocument(
        format="Excel",
        metadata={"工作表数": str(len(tables)), "数据行数": str(total_rows)},
        tables=tables,
        text="",
    )


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _parse_pdf(path: Path, ocr_max_pages: int | None = None) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise MissingDependency("解析 .pdf 需要安装 pypdf（pip install pypdf）") from exc

    reader = PdfReader(str(path))
    page_texts: list[str] = []
    for page in reader.pages:
        try:
            page_texts.append(page.extract_text() or "")
        except Exception:
            page_texts.append("")
    extracted_pages = sum(1 for t in page_texts if t.strip())
    text = "\n\n".join(f"【第 {i + 1} 页】\n{content}" for i, content in enumerate(page_texts) if content.strip())

    metadata: dict = {
        "页数": str(len(reader.pages)),
        "可提取文本页数": str(extracted_pages),
        "标题": str(reader.metadata.title) if reader.metadata and reader.metadata.title else "",
    }

    # Scanned / image-only PDF: fall back to OCR when the text layer is missing
    # or covers less than 30% of pages (port of the CM documentParse "扫描件可能
    # 无法提取" limitation, solved via OCR).
    total = len(reader.pages)
    coverage = (extracted_pages / total) if total else 1.0
    if coverage < 0.3:
        from openkitsune.knowledge import ocr

        ocr_result = ocr.extract_pdf_text(path, max_pages=ocr_max_pages or ocr.MAX_PAGES)
        if ocr_result.get("ok") and ocr_result.get("text"):
            metadata["ocr_used"] = True
            metadata["ocr_pages"] = str(ocr_result.get("ocr_pages", 0))
            metadata["ocr_recognized"] = str(ocr_result.get("recognized_pages", 0))
            metadata["ocr_duration_ms"] = str(ocr_result.get("duration_ms", 0))
            metadata["ocr_cached"] = str(bool(ocr_result.get("cached", False)))
            # OCR text takes precedence for scanned documents
            text = ocr_result["text"][:TEXT_CHARS_CAP]
        else:
            metadata["ocr_used"] = False
            metadata["ocr_note"] = ocr_result.get("error") or "OCR 不可用或未识别到文本"

    return ParsedDocument(
        format="PDF",
        metadata=metadata,
        tables=[],
        text=text,
    )


# ---------------------------------------------------------------------------
# Word
# ---------------------------------------------------------------------------


def _parse_word(path: Path) -> ParsedDocument:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise MissingDependency("解析 .docx 需要安装 python-docx（pip install python-docx）") from exc

    document = Document(str(path))
    paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs)

    table_rows = 0
    tables: list[dict] = []
    for idx, table in enumerate(document.tables):
        rows: list[list[str]] = []
        for row in table.rows:
            values = [cell.text.strip() for cell in row.cells]
            if any(v for v in values):
                rows.append(values)
        if rows:
            table_rows += len(rows) - 1
            tables.append({"name": f"表格{idx + 1}", "headers": rows[0], "rows": rows[1:]})

    props = document.core_properties
    metadata: dict = {}
    if props.title:
        metadata["标题"] = props.title
    if props.author:
        metadata["作者"] = props.author
    if props.created:
        metadata["创建时间"] = str(props.created)
    if props.modified:
        metadata["修改时间"] = str(props.modified)
    metadata["段落数"] = str(len(paragraphs))
    metadata["表格行数"] = str(table_rows)
    return ParsedDocument(format="Word", metadata=metadata, tables=tables, text=text[:TEXT_CHARS_CAP])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_PARSERS = {
    ".csv": _parse_csv,
    ".tsv": _parse_csv,
    ".xlsx": _parse_excel,
    ".xls": _parse_excel,
    ".xlsm": _parse_excel,
    ".pdf": _parse_pdf,
    ".docx": _parse_word,
    ".doc": _parse_word,
}


def parse_document(
    path: str | Path,
    max_size: int = MAX_FILE_SIZE,
    ocr_max_pages: int | None = None,
) -> ParsedDocument:
    """Parse a supported document file into structured text.

    PDFs without a text layer (scanned) are OCR'd automatically when the OCR
    backends are installed; ``ocr_max_pages`` caps how many pages are rendered.

    Raises:
        FileTooLarge: file exceeds ``max_size``.
        UnsupportedFormat: extension not supported.
        MissingDependency / ParseError: backend or content failure.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise ParseError(f"文件不存在: {path}")
    size = os.path.getsize(file_path)
    if size > max_size:
        raise FileTooLarge(f"文件过大（{size // (1024 * 1024)} MB），最大支持 {max_size // (1024 * 1024)} MB")

    ext = file_path.suffix.lower()
    if ext == ".pdf":
        return _parse_pdf(file_path, ocr_max_pages=ocr_max_pages)
    parser = _PARSERS.get(ext)
    if parser is None:
        supported = "、".join(sorted({e.lstrip(".") for e in _PARSERS}))
        raise UnsupportedFormat(f"不支持的文件格式 '.{ext}'。支持: {supported}。纯文本/代码文件请直接读取。")
    return parser(file_path)


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gb18030")
        except Exception:
            return raw.decode("utf-8", errors="replace")
