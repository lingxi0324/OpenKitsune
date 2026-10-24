"""Handlers for the 图书馆 (library) read-only tools.

``library_read_page`` lets the workspace agent read a library book page by
page (incremental batch reading) instead of receiving a whole-file dump.
All access is rooted at the configured library root with traversal
protection, mirroring the /api/library/* routes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.policy_v2 import ApprovalClass

if TYPE_CHECKING:
    from ...agent.core import Agent

logger = logging.getLogger(__name__)

# 与 api/routes/library.py 保持一致
DEFAULT_LIBRARY_ROOT = r"E:\agents\CM-agentic\lynzie\图书馆"
TEXT_EXTENSIONS = {
    ".md", ".markdown", ".mdown", ".mkd", ".mdx",
    ".txt", ".text", ".log", ".csv", ".tsv", ".tab",
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".html", ".htm", ".xml", ".rst", ".org", ".adoc", ".asciidoc",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".hpp", ".sh", ".bat", ".ps1", ".sql",
}
MAX_FILE_BYTES = 32 * 1024 * 1024
DEFAULT_PAGE_SIZE = 150
MAX_PAGE_SIZE = 2000
# 学习工具单次返回内容上限（字符）；达到上限即截断并提示继续
STUDY_CHAR_CAP = 16000
DEFAULT_STUDY_MAX_PAGES = 20
MAX_STUDY_MAX_PAGES = 60


def _data_dir() -> Path:
    try:
        from ...config import settings

        data_dir = getattr(settings, "data_dir", None)
        if data_dir:
            return Path(data_dir)
    except Exception:
        pass
    try:
        return Path.cwd() / "data"
    except Exception:
        return Path.cwd()


def load_library_root() -> Path:
    """解析书库根目录（环境变量 > data/library_config.json > 默认值）。"""
    import json
    import os

    env_root = os.environ.get("OPENKITSUNE_LIBRARY_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    cfg_path = _data_dir() / "library_config.json"
    try:
        if cfg_path.is_file():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            root = str(data.get("root_path", "")).strip()
            if root:
                return Path(root)
    except Exception:
        logger.warning("Failed to read library config, falling back to default", exc_info=True)
    return Path(DEFAULT_LIBRARY_ROOT)


def _resolve_path(root: Path, rel: str) -> Path:
    """把相对路径解析到书库根内并做目录穿越防护；越界返回 None。"""
    rel = (rel or "").strip().replace("\\", "/").strip("/")
    if rel in ("", "."):
        return root
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def _decode(raw: bytes) -> tuple[str, str]:
    for enc in ("utf-8", "utf-8-sig"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    try:
        return raw.decode("gbk"), "gbk"
    except UnicodeDecodeError:
        pass
    return raw.decode("latin-1"), "latin-1"


class LibraryHandler:
    TOOLS = ["library_read_page", "library_study"]
    TOOL_CLASSES = {
        "library_read_page": ApprovalClass.READONLY_SEARCH,
        "library_study": ApprovalClass.READONLY_SEARCH,
    }

    def __init__(self, agent: Agent | None = None) -> None:
        self.agent = agent

    async def handle(self, tool_name: str, params: dict[str, Any]) -> dict:
        if tool_name == "library_read_page":
            return await self._read_page(params)
        if tool_name == "library_study":
            return await self._study(params)
        return {"error": f"unknown library tool: {tool_name}"}

    # ── 通用：解析根/路径/读取文件 ──────────────────────────────
    def _load_text(self, rel: str) -> tuple[list[str], dict, str] | dict:
        """返回 (lines, meta, rel_path)；出错时返回 {"error": ...}。"""
        root = load_library_root()
        if not root.is_dir():
            return {"error": f"书库根目录不存在: {root}"}
        root_resolved = root.resolve()
        target = _resolve_path(root, rel)
        if target is None:
            return {"error": f"路径超出书库根目录范围: {rel}"}
        if not target.is_file():
            return {"error": f"文件不存在: {rel}"}
        ext = target.suffix.lower()
        if ext not in TEXT_EXTENSIONS:
            return {"error": f"不支持该格式在线阅读: {ext or '无扩展名'}"}
        try:
            size = target.stat().st_size
        except OSError as exc:
            return {"error": f"读取文件信息失败: {exc}"}
        if size > MAX_FILE_BYTES:
            return {"error": "文件过大，暂不支持阅读"}
        try:
            raw = target.read_bytes()
        except OSError as exc:
            return {"error": f"读取文件失败: {exc}"}
        content, encoding = _decode(raw)
        rel_pos = str(target.relative_to(root_resolved)).replace("\\", "/")
        return [line.rstrip("\r") for line in content.split("\n")], {
            "name": target.name,
            "path": rel_pos,
            "encoding": encoding,
        }, rel_pos

    async def _read_page(self, params: dict[str, Any]) -> dict:
        """读取书库内指定书籍的指定页（增量分批阅读）。"""
        rel = str(params.get("path", "") or "").strip()
        if not rel:
            return {"error": "缺少必填参数 path（书库内相对路径）"}
        try:
            page = max(1, int(params.get("page", 1)))
            page_size = max(1, min(int(params.get("page_size", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE))
        except (TypeError, ValueError):
            return {"error": "page/page_size 必须为整数"}

        loaded = self._load_text(rel)
        if isinstance(loaded, dict) and "error" in loaded:
            return loaded
        lines, meta, rel_pos = loaded
        total_lines = len(lines)
        total_pages = max(1, (total_lines + page_size - 1) // page_size)
        if page > total_pages:
            page = total_pages
        start = (page - 1) * page_size
        page_lines = lines[start : start + page_size]
        has_more = start + page_size < total_lines

        return {
            "name": meta["name"],
            "path": rel_pos,
            "page": page,
            "page_size": page_size,
            "total_lines": total_lines,
            "total_pages": total_pages,
            "has_more": has_more,
            "encoding": meta["encoding"],
            "content": "\n".join(page_lines).strip("\n"),
            "提示": (
                f"共 {total_lines} 行 / {total_pages} 页，本页为第 {page} 页"
                f"（行 {start + 1}-{min(start + page_size, total_lines)}）。"
                f"如需继续阅读请以 page={page + 1} 再次调用 library_read_page。"
            ),
        }

    async def _study(self, params: dict[str, Any]) -> dict:
        """学习工具：批量取回一段范围的页内容，提取章节标题，供 AI 系统学习。"""
        rel = str(params.get("path", "") or "").strip()
        if not rel:
            return {"error": "缺少必填参数 path（书库内相对路径）"}
        focus = str(params.get("focus", "") or "").strip()
        try:
            from_page = max(1, int(params.get("from_page", 1)))
            page_size = max(1, min(int(params.get("page_size", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE))
            max_pages = max(1, min(int(params.get("max_pages", DEFAULT_STUDY_MAX_PAGES)), MAX_STUDY_MAX_PAGES))
            to_page = None
            if params.get("to_page") not in (None, ""):
                to_page = max(from_page, int(params["to_page"]))
        except (TypeError, ValueError):
            return {"error": "from_page/to_page/max_pages/page_size 必须为整数"}

        loaded = self._load_text(rel)
        if isinstance(loaded, dict) and "error" in loaded:
            return loaded
        lines, meta, rel_pos = loaded
        total_lines = len(lines)
        total_pages = max(1, (total_lines + page_size - 1) // page_size)
        end_page = min(to_page or (from_page + max_pages - 1), total_pages)

        out_lines: list[str] = []
        headings: list[dict] = []
        chars = 0
        actual_end = from_page
        for p in range(from_page, end_page + 1):
            start = (p - 1) * page_size
            chunk = lines[start : start + page_size]
            for idx, line in enumerate(chunk):
                line_no = start + idx + 1
                out_lines.append(line)
                chars += len(line) + 1
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    headings.append({"line": line_no, "title": stripped.rstrip()})
            actual_end = p
            if chars >= STUDY_CHAR_CAP:
                break

        has_more = actual_end < total_pages
        return {
            "name": meta["name"],
            "path": rel_pos,
            "focus": focus or None,
            "from_page": from_page,
            "to_page": actual_end,
            "total_lines": total_lines,
            "total_pages": total_pages,
            "page_size": page_size,
            "read_pages": actual_end - from_page + 1,
            "headings": headings,
            "encoding": meta["encoding"],
            "content": "\n".join(out_lines).strip("\n"),
            "has_more": has_more,
            "提示": (
                f"已返回第 {from_page}-{actual_end} 页（共 {total_pages} 页，本文件 {total_lines} 行）。"
                + (f"学习重点：{focus}。" if focus else "")
                + (
                    f"内容已到单次上限（{STUDY_CHAR_CAP} 字符），如需继续请以 from_page={actual_end + 1} "
                    "再次调用 library_study。"
                    if has_more and chars >= STUDY_CHAR_CAP
                    else ("还有后续内容，如需继续请以 from_page={actual_end + 1} 再次调用 library_study。" if has_more else "已读到全书末尾。")
                )
            ),
        }


def create_library_handler(agent: Agent | None = None):
    """创建图书馆 handler（供 _agent_runtime._init_handlers 注册）。

    必须返回绑定方法：register() 通过 handler.__self__.TOOLS 建立
    tool_name -> handler 索引，返回实例会导致工具索引为空。
    """
    handler = LibraryHandler(agent)
    return handler.handle
