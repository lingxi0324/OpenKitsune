"""
图书馆读书功能后端 API。

书库根目录默认指向 CM-agentic(玄医融合) 的 lynzie/图书馆，
可通过环境变量 OPENKITSUNE_LIBRARY_ROOT 或 POST /api/library/config 修改。
所有文件访问均在书库根目录内解析，并做目录穿越防护。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_LIBRARY_ROOT = r"D:\ai\OpenKitsune-main\knowledge"

# 可直接以文本读取的扩展名（.md 单独归为 markdown 类型）
TEXT_EXTENSIONS = {
    ".md", ".markdown", ".mdown", ".mkd", ".mdx",
    ".txt", ".text", ".log", ".csv", ".tsv", ".tab",
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".html", ".htm", ".xml", ".rst", ".org", ".adoc", ".asciidoc",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".hpp", ".sh", ".bat", ".ps1", ".sql",
}

MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd", ".mdx"}

# 单文件读取上限（32MB），超出提示无法在线阅读
MAX_FILE_BYTES = 32 * 1024 * 1024


def _data_dir() -> Path:
    try:
        from openkitsune.config import settings

        data_dir = getattr(settings, "data_dir", None)
        if data_dir:
            return Path(data_dir)
    except Exception:
        pass
    try:
        return Path.cwd() / "data"
    except Exception:
        return Path.cwd()


def _config_path() -> Path:
    return _data_dir() / "library_config.json"


def _load_root() -> Path:
    env_root = os.environ.get("OPENKITSUNE_LIBRARY_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    try:
        cfg_path = _config_path()
        if cfg_path.is_file():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            root = str(data.get("root_path", "")).strip()
            if root:
                return Path(root)
    except Exception:
        logger.warning("Failed to read library config, falling back to default", exc_info=True)
    return Path(DEFAULT_LIBRARY_ROOT)


def _save_root(root: str) -> None:
    cfg_path = _config_path()
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps({"root_path": root}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("Failed to write library config: %s", exc)


def _resolve_path(root: Path, rel: str) -> Path:
    """把相对路径解析到书库根内并做目录穿越防护。"""
    rel = (rel or "").strip().replace("\\", "/").strip("/")
    if rel in ("", "."):
        return root
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise HTTPException(status_code=400, detail="路径超出书库根目录范围")
    return candidate


def _entry(root_resolved: Path, path: Path) -> dict:
    rel = str(path.relative_to(root_resolved)).replace("\\", "/")
    is_dir = path.is_dir()
    try:
        stat = path.stat()
        size = stat.st_size if not is_dir else None
        mtime = int(stat.st_mtime * 1000)
    except OSError:
        size = None
        mtime = None
    return {
        "name": path.name,
        "path": rel,
        "is_dir": is_dir,
        "size": size,
        "modified_at": mtime,
    }


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


# ─── Pydantic models ──────────────────────────────────────────────────


class LibraryConfigRequest(BaseModel):
    root_path: str


# ─── Routes ────────────────────────────────────────────────────────────


@router.get("/api/library/config")
async def get_library_config():
    """返回书库根目录配置与可用性。"""
    root = _load_root()
    return {
        "root_path": str(root),
        "default_root_path": DEFAULT_LIBRARY_ROOT,
        "exists": root.is_dir(),
    }


@router.post("/api/library/config")
async def set_library_config(body: LibraryConfigRequest):
    """保存书库根目录配置（写入 data/library_config.json）。"""
    root = (body.root_path or "").strip()
    if not root:
        raise HTTPException(status_code=400, detail="root_path 不能为空")
    path = Path(root)
    if not path.is_dir():
        raise HTTPException(status_code=400, detail=f"目录不存在: {root}")
    _save_root(root)
    return {"root_path": root, "default_root_path": DEFAULT_LIBRARY_ROOT, "exists": True}


@router.get("/api/library/tree")
async def list_library_tree(path: str = ""):
    """列出书库内指定目录的条目（目录在前，前端负责中文排序）。"""
    root = _load_root()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"书库根目录不存在: {root}")
    root_resolved = root.resolve()
    target = _resolve_path(root, path)
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="目标不是目录")
    try:
        entries = [p for p in target.iterdir() if not p.name.startswith(".")]
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"读取目录失败: {exc}")
    items = [_entry(root_resolved, p) for p in entries]
    items.sort(key=lambda e: (not e["is_dir"], e["name"]))
    return {
        "root_path": str(root),
        "current_path": str(target.relative_to(root_resolved)).replace("\\", "/")
        if target != root_resolved else "",
        "entries": items,
    }


@router.get("/api/library/file")
async def read_library_file(path: str = Query(..., min_length=1)):
    """读取书库内文本/Markdown 文件内容；非文本格式返回 supported=false。"""
    root = _load_root()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"书库根目录不存在: {root}")
    root_resolved = root.resolve()
    target = _resolve_path(root, path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    ext = target.suffix.lower()
    supported = ext in TEXT_EXTENSIONS
    rel = str(target.relative_to(root_resolved)).replace("\\", "/")
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"读取文件信息失败: {exc}")
    if not supported:
        return {
            "name": target.name,
            "path": rel,
            "size": size,
            "ext": ext,
            "supported": False,
            "content": "",
            "encoding": None,
        }
    if size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="文件过大，暂不支持在线阅读")
    raw = target.read_bytes()
    content, encoding = _decode(raw)
    return {
        "name": target.name,
        "path": rel,
        "size": size,
        "ext": ext,
        "supported": True,
        "content": content,
        "encoding": encoding,
    }
