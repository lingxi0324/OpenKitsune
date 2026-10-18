"""OCR extraction for scanned / image-only PDFs and images.

Ports the "scan OCR" capability into OpenKitsune: PyMuPDF renders each PDF page
to a bitmap, RapidOCR (onnxruntime, bundled Chinese+English models) recognises
the text. Results are cached per file (keyed by path + mtime + dpi) under
``data/knowledge/ocr_cache/`` so re-parses are instant.

Design notes:
- ``pymupdf`` and ``rapidocr_onnxruntime`` are optional imports; every public
  function degrades gracefully and reports availability via :func:`available`.
- The RapidOCR engine is a module-level singleton (model loading is slow).
- ``extract_pdf_text`` renders at ``dpi`` (default 150) and returns per-page
  text blocks so callers can track coverage.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

DEFAULT_DPI = 150
MAX_PAGES = 60  # hard cap per call; protects long-running OCR

_LOCK = threading.Lock()
_engine = None
_engine_guard = threading.Lock()


def available() -> tuple[bool, str]:
    """Return (available, reason). RapidOCR loads its models on first use."""
    try:
        import pymupdf  # noqa: F401
    except ImportError:
        return False, "解析 PDF 渲染需要安装 pymupdf（pip install pymupdf）"
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except ImportError:
        return False, "OCR 识别需要安装 rapidocr_onnxruntime（pip install rapidocr_onnxruntime）"
    return True, "ok"


def _get_engine():
    global _engine
    if _engine is None:
        with _engine_guard:
            if _engine is None:
                from rapidocr_onnxruntime import RapidOCR

                _engine = RapidOCR()
    return _engine


def project_root() -> Path:
    try:
        from openkitsune.config import settings

        return Path(settings.project_root)
    except Exception:
        return Path.cwd()


def ocr_cache_dir() -> Path:
    return project_root() / "data" / "knowledge" / "ocr_cache"


def _cache_key(path: Path, dpi: int) -> str:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0
    digest = hashlib.sha1(f"{path.resolve()}|{mtime}|{dpi}".encode("utf-8")).hexdigest()[:16]
    return digest


def _cache_load(path: Path, dpi: int) -> dict | None:
    cache_file = ocr_cache_dir() / f"{_cache_key(path, dpi)}.json"
    if not cache_file.is_file():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    if data.get("root") != str(path.resolve()):
        return None
    return data


def _cache_save(path: Path, dpi: int, payload: dict) -> None:
    cache_file = ocr_cache_dir() / f"{_cache_key(path, dpi)}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    from openkitsune.utils import atomic_io

    atomic_io.safe_write(cache_file, json.dumps(payload, ensure_ascii=False))


def _render_page(page, dpi: int):
    """Render a PDF page to PNG bytes at the given dpi."""
    pix = page.get_pixmap(dpi=dpi)
    return pix.tobytes("png"), pix.width, pix.height


def _ocr_image(png_bytes: bytes) -> list[str]:
    engine = _get_engine()
    # RapidOCR accepts raw bytes / ndarray / file path — not BytesIO.
    result, _ = engine(png_bytes)
    if not result:
        return []
    lines = []
    # result items: [box, text, score] — sort top-to-bottom by box y0, then x0
    scored = []
    for item in result:
        try:
            box, text, score = item
            y0 = float(box[0][1])
            x0 = float(box[0][0])
            conf = float(score)  # rapidocr returns score as str in some versions
        except (TypeError, ValueError, IndexError):
            continue
        if str(text).strip():
            scored.append((y0, x0, conf, str(text).strip()))
    scored.sort(key=lambda t: (round(t[0] / 12), t[1]))
    for _, _, conf, text in scored:
        if conf < 0.3:
            continue
        lines.append(text)
    return lines


def extract_pdf_text(path: str | Path, dpi: int = DEFAULT_DPI, max_pages: int = MAX_PAGES) -> dict:
    """OCR a scanned PDF page by page with on-disk caching.

    Returns:
        {
          "ok": bool, "error": str|None,
          "pages": int, "recognized_pages": int, "cached": bool,
          "duration_ms": int,
          "text": str,  # per-page blocks joined, capped
          "page_texts": [str, ...],
        }
    """
    ok, reason = available()
    if not ok:
        return {"ok": False, "error": reason, "text": "", "pages": 0, "recognized_pages": 0, "cached": False, "duration_ms": 0, "page_texts": []}

    import time

    import pymupdf

    file_path = Path(path)
    if not file_path.is_file():
        return {"ok": False, "error": f"文件不存在: {path}", "text": "", "pages": 0, "recognized_pages": 0, "cached": False, "duration_ms": 0, "page_texts": []}

    cached = _cache_load(file_path, dpi)
    cached_pages = 0
    page_texts: list[str] = []
    recognized = 0
    if cached is not None and cached.get("ok"):
        cached_pages = int(cached.get("ocr_pages", 0) or 0)
        page_texts = list(cached.get("page_texts") or [])
        recognized = int(cached.get("recognized_pages", 0) or 0)
        # The cache key does not include max_pages: a wider request extends it
        # incrementally instead of re-OCR-ing pages that are already covered.
        if cached_pages > 0 and cached_pages >= min(max_pages, int(cached.get("pages") or 0)):
            return {**cached, "cached": True}

    started = time.perf_counter()
    try:
        doc = pymupdf.open(str(file_path))
    except Exception as exc:
        return {"ok": False, "error": f"PDF 打开失败: {exc}", "text": "", "pages": 0, "recognized_pages": 0, "cached": False, "duration_ms": 0, "page_texts": []}

    total_pages = len(doc)
    limit = min(total_pages, max(1, max_pages))
    if len(page_texts) < total_pages:
        page_texts.extend([""] * (total_pages - len(page_texts)))

    for idx in range(max(cached_pages, 0), min(limit, total_pages)):
        page = doc[idx]
        try:
            png_bytes, _, _ = _render_page(page, dpi)
            lines = _ocr_image(png_bytes)
        except Exception:
            lines = []
        if lines:
            recognized += 1
        page_texts[idx] = "\n".join(lines)
    doc.close()

    text = "\n\n".join(
        f"【第 {i + 1} 页】\n{content}" for i, content in enumerate(page_texts) if content.strip()
    )
    payload = {
        "ok": True,
        "root": str(file_path.resolve()),
        "error": None,
        "pages": total_pages,
        "recognized_pages": recognized,
        "ocr_pages": limit,
        "dpi": dpi,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "cached": False,
        "page_texts": page_texts,
        "text": text,
    }
    with _LOCK:
        _cache_save(file_path, dpi, payload)
    return payload


def extract_image_text(path: str | Path) -> dict:
    """OCR a standalone image file (png/jpg)."""
    ok, reason = available()
    if not ok:
        return {"ok": False, "error": reason, "text": ""}
    import time

    file_path = Path(path)
    if not file_path.is_file():
        return {"ok": False, "error": f"文件不存在: {path}", "text": ""}
    started = time.perf_counter()
    try:
        lines = _ocr_image(file_path.read_bytes())
    except Exception as exc:
        return {"ok": False, "error": f"OCR 失败: {exc}", "text": ""}
    return {
        "ok": True,
        "text": "\n".join(lines),
        "lines": len(lines),
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }
