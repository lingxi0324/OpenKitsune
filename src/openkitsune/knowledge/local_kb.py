"""Local knowledge-base scanner, index cache and graph engine.

Port of the CM-agentic ``graph-scanner.ts`` semantics to OpenKitsune, frozen by
``temp/kb_integration_contract.md``. Only the knowledge module and the API
routes in ``api/routes/knowledge.py`` are exposed to callers.

Node ids are stable: ``dir:<rel>`` / ``file:<rel>`` (rel uses forward slashes,
relative to the configured root).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from openkitsune.utils import atomic_io, env_config

# ---------------------------------------------------------------------------
# Contract constants (frozen — do not rename)
# ---------------------------------------------------------------------------

SCAN_EXTS = {".md", ".markdown", ".txt", ".text"}
# Binary formats ingested through knowledge.parsers (documentParse port)
BINARY_EXTS = {".pdf", ".docx", ".xls", ".xlsx", ".xlsm", ".csv", ".tsv"}
SCAN_EXTS |= BINARY_EXTS
SKIP_PATTERNS = (".meta.json", "_archive", "_system", "node_modules", ".git", "backup")
MAX_FILE_CHARS = 200_000
REF_BODY_CHARS = 30_000
GROUP_PARTICIPANT_CAP = 400
KEYWORD_TOP_N = 8
KEYWORD_COOCCURRENCE = 2

CATEGORY_COLORS = {
    "概念": "#6c8cff",
    "人物": "#f87171",
    "典籍": "#fbbf24",
    "方剂": "#4ade80",
    "穴位": "#c084fc",
    "脏腑": "#fb923c",
    "书籍": "#fbbf24",
    "文档": "#60a5fa",
    "目录": "#94a3b8",
    "其他": "#94a3b8",
}

STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "他", "她", "它", "们", "这个", "那个", "什么", "怎么", "为",
    "因为", "所以", "但是", "如果", "虽然", "而且", "并且", "或者", "还是", "不是",
    "可以", "可能", "应该", "需要", "必须", "已经", "正在", "将要", "之", "其", "此",
    "与", "及", "等", "中", "内", "外", "前", "后", "间", "时", "地", "得", "过",
}

KNOWN_ROOT_FALLBACK = Path(r"E:\agents\CM-agentic\lynzie")
ENV_KEY = "KNOWLEDGE_LOCAL_ROOT"

_SCAN_LOCK = threading.Lock()


class LocalKBError(Exception):
    """400-semantic error raised for path escapes / invalid config."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------------------
# Root resolution & cache locations
# ---------------------------------------------------------------------------


def project_root() -> Path:
    try:
        from openkitsune.config import settings

        return Path(settings.project_root)
    except Exception:
        return Path.cwd()


def cache_dir() -> Path:
    return project_root() / "data" / "knowledge"


def index_cache_path() -> Path:
    return cache_dir() / "local_kb_index.json"


def graph_cache_path() -> Path:
    return cache_dir() / "local_kb_graph.json"


def resolve_root() -> Path:
    """``KNOWLEDGE_LOCAL_ROOT`` (env or .env) > existing lynzie > project data dir."""
    root = os.environ.get(ENV_KEY, "").strip()
    if not root:
        try:
            root = env_config.read_env_file(project_root() / ".env").get(ENV_KEY, "").strip()
        except Exception:
            root = ""
    if root:
        return Path(root).expanduser()
    if KNOWN_ROOT_FALLBACK.is_dir():
        return KNOWN_ROOT_FALLBACK
    return cache_dir()


def persist_root(root: str) -> Path:
    path = Path(root.strip()).expanduser()
    if not path.is_dir():
        raise LocalKBError(f"根目录不存在或不是目录: {path}")
    path = path.resolve()
    env_config.update_env_file(
        project_root() / ".env", entries={ENV_KEY: str(path)}
    )
    os.environ[ENV_KEY] = str(path)
    return path


def resolve_safe(root: Path, rel: str | None) -> Path:
    """Resolve ``rel`` inside ``root``; raise ``LocalKBError`` on any escape."""
    root_resolved = root.resolve()
    candidate = (root_resolved / (rel or "")).resolve()
    if candidate != root_resolved and not candidate.is_relative_to(root_resolved):
        raise LocalKBError(f"路径越界（必须位于知识库根目录内）: {rel}")
    return candidate


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


# ---------------------------------------------------------------------------
# File reading, meta parsing, text extraction
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("gb18030")
        except Exception:
            text = raw.decode("utf-8", errors="replace")
    return text[:MAX_FILE_CHARS]


def _read_any_text(path: Path) -> str:
    """Read a knowledge file as text, parsing binary formats via knowledge.parsers.

    PDF / Word / Excel / CSV are extracted into their text/table rendering so
    they join the same index, graph and search pipeline as markdown files.
    """
    if path.suffix.lower() in BINARY_EXTS:
        try:
            from openkitsune.knowledge import parsers

            parsed = parsers.parse_document(path)
            return parsed.render_text(max_chars=REF_BODY_CHARS)[:MAX_FILE_CHARS]
        except Exception:
            return ""
    return _read_text(path)


def _load_meta(path: Path) -> dict:
    meta_path = path.with_name(path.name + ".meta.json")
    if not meta_path.is_file():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_title(content: str, file_name: str, meta: dict) -> str:
    meta_title = str(meta.get("title") or "").strip()
    if meta_title:
        return meta_title[:50]
    for line in content.splitlines():
        trimmed = line.strip()
        match = re.match(r"^#{1,3}\s+(.+)$", trimmed)
        if match and match.group(1).strip():
            return match.group(1).strip()[:50]
    stem = re.sub(r"\.(md|markdown|txt|text)$", "", file_name, flags=re.IGNORECASE)
    return stem[:50]


def _extract_summary(content: str, max_chars: int = 200) -> str:
    lines = []
    for line in content.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#") or trimmed.startswith("---"):
            continue
        if len(trimmed) <= 5:
            continue
        lines.append(trimmed)
    summary = " ".join(lines[:5])
    summary = re.sub(r"[*_`>#-]", "", summary)
    if len(summary) > max_chars:
        return summary[:max_chars] + "…"
    return summary


def _extract_keywords(content: str, top_n: int = KEYWORD_TOP_N) -> list[str]:
    freq: Counter[str] = Counter()
    for word in re.findall(r"[\u4e00-\u9fa5]{2,4}", content):
        if word in STOP_WORDS:
            continue
        freq[word] += 1
    for word in (w.lower() for w in re.findall(r"[a-zA-Z]{3,}", content)):
        freq[word] += 1
    items = [(word, count) for word, count in freq.items() if count >= 2]
    items.sort(key=lambda item: (-item[1], item[0]))
    return [word for word, _ in items[:top_n]]


def _merge_keywords(meta: dict, extracted: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for bucket in (meta.get("topics") or [], meta.get("keywords") or []):
        if not isinstance(bucket, list):
            continue
        for item in bucket:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    for word in extracted:
        if word not in seen:
            seen.add(word)
            merged.append(word)
        if len(merged) >= KEYWORD_TOP_N:
            break
    return merged[:KEYWORD_TOP_N]


def infer_category(rel_path: str, name: str, is_dir: bool) -> str:
    if is_dir:
        return "目录"
    text = (rel_path + " " + name).lower()
    if "方剂" in text or "汤" in text:
        return "方剂"
    if "穴位" in text or "经络" in text or "针灸" in text:
        return "穴位"
    if (
        "脏腑" in text
        or "五脏" in text
        or any(ch in text for ch in "肝心脾肺肾")
    ):
        return "脏腑"
    if (
        "典籍" in text
        or "道藏" in text
        or "医藏" in text
        or "图书馆" in text
        or "经" in text
    ):
        return "典籍"
    if "人物" in text or "传" in text:
        return "人物"
    if "概念" in text or "理论" in text or "公理" in text:
        return "概念"
    return "文档"


def _infer_domain(rel_path: str, meta_domain) -> str | None:
    if meta_domain:
        return str(meta_domain)
    parts = rel_path.split("/")
    top = parts[0]
    if top == "图书馆" and len(parts) > 1:
        return parts[1]
    return top or None


def _iso_mtime(path: Path) -> str | None:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()


def _should_skip(name: str) -> bool:
    lower = name.lower()
    return any(pattern in lower for pattern in SKIP_PATTERNS)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def scan(root: Path) -> dict:
    """Full recursive scan. Returns stats, file index records, nodes and edges."""
    started = time.perf_counter()
    root = root.resolve()

    walked_dirs: list[Path] = []
    file_paths: list[Path] = []
    dir_children: dict[Path, list[Path]] = defaultdict(list)

    for dirpath, dirnames, filenames in os.walk(root):
        # prune skipped directories in-place
        kept = [d for d in dirnames if not _should_skip(d)]
        dirnames[:] = kept
        current = Path(dirpath)
        walked_dirs.append(current)
        for name in filenames:
            if _should_skip(name):
                continue
            ext = Path(name).suffix.lower()
            if ext in SCAN_EXTS:
                file_paths.append(current / name)
        for sub in kept:
            dir_children[current].append(current / sub)

    records: list[dict] = []
    failed: list[dict] = []
    skipped = 0
    meta_count = 0
    access_values: list[tuple[dict, int]] = []

    for path in file_paths:
        rel = _rel(path, root)
        try:
            content = _read_any_text(path)
        except Exception as exc:
            failed.append({"path": str(path), "reason": str(exc)})
            continue
        if len(content.strip()) < 10:
            skipped += 1
            continue
        meta = _load_meta(path)
        if meta:
            meta_count += 1
        title = _extract_title(content, path.name, meta)
        category = infer_category(rel, path.name, is_dir=False)
        record = {
            "id": f"file:{rel}",
            "path": rel,
            "name": path.name,
            "label": title,
            "category": category,
            "description": _extract_summary(content),
            "keywords": _merge_keywords(meta, _extract_keywords(content)),
            "domain": _infer_domain(rel, meta.get("domain")),
            "is_directory": False,
            "color": CATEGORY_COLORS.get(category, CATEGORY_COLORS["其他"]),
            "importance": None,  # normalized in a second pass
            "file_size": path.stat().st_size if path.exists() else None,
            "modified": _iso_mtime(path),
            "meta": meta,
            "_body": content,
        }
        access = meta.get("access_count")
        try:
            access_int = int(access) if access is not None else 0
        except (TypeError, ValueError):
            access_int = 0
        access_values.append((record, access_int))
        records.append(record)

    # importance: meta.importance_score first, else access_count normalized, else 0.5
    max_access = max((value for _, value in access_values), default=0)
    for record, access_int in access_values:
        meta = record["meta"]
        score = meta.get("importance_score")
        if score is not None:
            try:
                record["importance"] = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                record["importance"] = 0.5
        elif max_access > 0:
            record["importance"] = round(access_int / max_access, 4)
        else:
            record["importance"] = 0.5

    files_by_dir: dict[Path, list[dict]] = defaultdict(list)
    for record in records:
        files_by_dir[(root / record["path"]).parent].append(record)

    # directory nodes: every non-root walked dir that holds files or node children
    dir_nodes: dict[Path, dict] = {}

    def ensure_dir_node(path: Path) -> dict | None:
        if path == root:
            return None
        if path in dir_nodes:
            return dir_nodes[path]
        rel = _rel(path, root)
        category = infer_category(rel, path.name, is_dir=True)
        node = {
            "id": f"dir:{rel}",
            "label": path.name,
            "category": category,
            "description": f"目录：{rel or path.name}",
            "keywords": [],
            "domain": _infer_domain(rel, None),
            "path": rel,
            "is_directory": True,
            "color": CATEGORY_COLORS["目录"],
            "importance": 0.5,
            "file_size": None,
            "modified": None,
        }
        dir_nodes[path] = node
        return node

    for dirpath in walked_dirs:
        if dirpath == root:
            continue
        if files_by_dir.get(dirpath):
            ensure_dir_node(dirpath)
    # parent containment requires nodes on both sides, so expand upward
    changed = True
    while changed:
        changed = False
        for dirpath in list(dir_nodes):
            parent = dirpath.parent
            if parent != root and parent not in dir_nodes:
                ensure_dir_node(parent)
                changed = True

    edges: list[dict] = []
    edge_keys: set[tuple[str, str, str]] = set()

    def add_edge(source: str, target: str, label: str, weight: float) -> None:
        if source == target:
            return
        key = (frozenset((source, target)), label)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append(
            {
                "id": f"edge:{source}|{target}|{label}",
                "source": source,
                "target": target,
                "label": label,
                "weight": weight,
            }
        )

    # 1. 包含 (w=2): dir -> files, parent dir -> child dir
    for dirpath, node in dir_nodes.items():
        for record in files_by_dir.get(dirpath, []):
            add_edge(node["id"], record["id"], "包含", 2.0)
        for child in dir_children.get(dirpath, []):
            child_node = dir_nodes.get(child)
            if child_node:
                add_edge(node["id"], child_node["id"], "包含", 2.0)

    # group = top-level sub-library (first path segment)
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        groups[record["path"].split("/")[0]].append(record)

    # 2. 引用 (w=1.5): body contains another file's title (len>=4), same group,
    #    body capped at 30K chars, participants capped at 400 by importance.
    for group_files in groups.values():
        participants = sorted(
            group_files, key=lambda r: r["importance"], reverse=True
        )[:GROUP_PARTICIPANT_CAP]
        by_id = {r["id"]: r for r in participants}
        for source in participants:
            body = source["_body"][:REF_BODY_CHARS]
            for target in participants:
                if source is target:
                    continue
                title = target["label"]
                if len(title) >= 4 and title in body:
                    add_edge(source["id"], target["id"], "引用", 1.5)
        del by_id

    # 3. 相关 (w=1.5): meta.related_slugs -> file stem or title
    slug_index: dict[str, str] = {}
    for record in records:
        slug_index[Path(record["name"]).stem.lower()] = record["id"]
        slug_index[record["label"].lower()] = record["id"]
    for record in records:
        for slug in record["meta"].get("related_slugs") or []:
            normalized = str(slug).strip().lower()
            normalized = re.sub(r"\.(md|markdown|txt|text)$", "", normalized)
            normalized = normalized.split("/")[-1]
            target_id = slug_index.get(normalized)
            if target_id:
                add_edge(record["id"], target_id, "相关", 1.5)

    # 4. 关联 (w=0.5 x shared): keyword co-occurrence >=2, same group;
    #    inverted-index accumulation keeps all-pairs quadratic blow-up away.
    for group_files in groups.values():
        kw_index: dict[str, list[str]] = defaultdict(list)
        for record in group_files:
            for word in set(record["keywords"]):
                kw_index[word].append(record["id"])
        pair_counts: dict[tuple[str, str], int] = defaultdict(int)
        for ids in kw_index.values():
            if len(ids) < 2:
                continue
            ids = sorted(ids)
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pair_counts[(ids[i], ids[j])] += 1
        for (source, target), shared in pair_counts.items():
            if shared >= KEYWORD_COOCCURRENCE:
                add_edge(source, target, "关联", round(shared * 0.5, 2))

    duration_ms = round((time.perf_counter() - started) * 1000)

    nodes = list(dir_nodes.values()) + [
        {key: value for key, value in r.items() if key != "_body" and key != "meta"}
        for r in records
    ]
    stats = {
        "total_files": len(file_paths),
        "indexed_files": len(records),
        "dirs": len(dir_nodes),
        "meta_files": meta_count,
        "skipped": skipped,
        "failed": failed,
        "duration_ms": duration_ms,
    }
    return {
        "root": str(root),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "records": records,
        "nodes": nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Cache read/write
# ---------------------------------------------------------------------------


def _strip_bodies(records: list[dict]) -> list[dict]:
    cleaned = []
    for record in records:
        cleaned.append({k: v for k, v in record.items() if k != "_body"})
    return cleaned


def save_cache(result: dict) -> None:
    cache_dir().mkdir(parents=True, exist_ok=True)
    index_payload = {
        "root": result["root"],
        "scanned_at": result["scanned_at"],
        "stats": result["stats"],
        "files": _strip_bodies(result["records"]),
    }
    graph_payload = {
        "root": result["root"],
        "scanned_at": result["scanned_at"],
        "stats": result["stats"],
        "nodes": result["nodes"],
        "edges": result["edges"],
    }
    atomic_io.safe_write(
        index_cache_path(), json.dumps(index_payload, ensure_ascii=False, indent=1)
    )
    atomic_io.safe_write(
        graph_cache_path(), json.dumps(graph_payload, ensure_ascii=False, indent=1)
    )


def load_cache() -> dict | None:
    index_path = index_cache_path()
    graph_path = graph_cache_path()
    if not index_path.is_file() or not graph_path.is_file():
        return None
    try:
        index_payload = json.loads(
            index_path.read_text(encoding="utf-8", errors="replace")
        )
        graph_payload = json.loads(
            graph_path.read_text(encoding="utf-8", errors="replace")
        )
    except Exception:
        return None
    root = str(resolve_root().resolve())
    if index_payload.get("root") != root or graph_payload.get("root") != root:
        return None
    return {**index_payload, "nodes": graph_payload.get("nodes", []),
            "edges": graph_payload.get("edges", [])}


def ensure_cache() -> dict:
    """Return cached index; on miss, run one synchronous full scan."""
    cached = load_cache()
    if cached is not None:
        return cached
    with _SCAN_LOCK:
        cached = load_cache()
        if cached is not None:
            return cached
        result = scan(resolve_root())
        save_cache(result)
        return {
            **{k: v for k, v in result.items() if k != "records"},
            "files": _strip_bodies(result["records"]),
        }


# ---------------------------------------------------------------------------
# Config / status
# ---------------------------------------------------------------------------


def config_status() -> dict:
    root = resolve_root()
    cached = load_cache()
    stats = (cached or {}).get("stats") or {}
    index_path = index_cache_path()
    index_age_ms = None
    if index_path.is_file():
        try:
            index_age_ms = round((time.time() - index_path.stat().st_mtime) * 1000)
        except OSError:
            index_age_ms = None
    return {
        "ok": True,
        "root": str(root),
        "root_exists": root.is_dir(),
        "stats": {
            "files": stats.get("total_files", 0),
            "dirs": stats.get("dirs", 0),
            "meta_files": stats.get("meta_files", 0),
            "indexed": stats.get("indexed_files", 0),
            "last_scan_at": (cached or {}).get("scanned_at"),
            "index_age_ms": index_age_ms,
        },
    }


# ---------------------------------------------------------------------------
# Browse / doc / search / graph
# ---------------------------------------------------------------------------


def browse(rel: str | None, limit: int = 200) -> dict:
    root = resolve_root()
    target = resolve_safe(root, rel)
    if not target.is_dir():
        raise LocalKBError(f"目录不存在: {rel}")
    index = ensure_cache()
    index_by_path = {record["path"]: record for record in index.get("files", [])}

    entries = []
    for child in target.iterdir():
        if _should_skip(child.name):
            continue
        is_dir = child.is_dir()
        child_rel = _rel(child, root)
        record = index_by_path.get(child_rel)
        entry = {
            "name": child.name,
            "rel_path": child_rel,
            "is_dir": is_dir,
            "is_doc": bool(record and not is_dir),
            "size": child.stat().st_size if not is_dir else None,
            "mtime": _iso_mtime(child),
        }
        if record:
            entry["title"] = record["label"]
            entry["category"] = record["category"]
            entry["domain"] = record["domain"]
        entries.append(entry)

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    return {
        "ok": True,
        "path": _rel(target, root) if target != root else "",
        "entries": entries[: max(1, limit)],
    }


def read_doc(rel: str) -> dict:
    root = resolve_root()
    target = resolve_safe(root, rel)
    if not target.is_file():
        raise LocalKBError(f"文档不存在: {rel}")
    index = ensure_cache()
    index_by_id = {record["path"]: record for record in index.get("files", [])}
    record = index_by_id.get(rel) or {}
    meta = record.get("meta") or _load_meta(target)

    content = _read_any_text(target)
    preview = content[:400]
    node_id = record.get("id") or f"file:{rel}"

    related: list[dict] = []
    related_ids = set()
    node_by_id = {node["id"]: node for node in index.get("nodes", [])}
    for edge in index.get("edges", []):
        if edge["label"] not in ("相关", "引用"):
            continue
        other = None
        if edge["source"] == node_id:
            other = edge["target"]
        elif edge["target"] == node_id:
            other = edge["source"]
        if other and other not in related_ids and other in node_by_id:
            related_ids.add(other)
            related.append(node_by_id[other])

    return {
        "ok": True,
        "path": rel,
        "title": record.get("label") or target.stem,
        "category": record.get("category") or infer_category(rel, target.name, False),
        "domain": record.get("domain"),
        "keywords": record.get("keywords") or [],
        "related": related,
        "preview": preview,
        "content": content,
        "meta": meta,
    }


def _tokenize(query: str) -> list[str]:
    terms: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", query):
        terms.add(run)
        for gram in re.findall(r"[\u4e00-\u9fa5]{2,4}", run):
            terms.add(gram)
    for word in (w.lower() for w in re.findall(r"[a-zA-Z]{3,}", query)):
        terms.add(word)
    return [t for t in terms if t.strip()]


def _snippet(body: str, terms: list[str]) -> str:
    lowered = body.lower()
    hit = -1
    for term in terms:
        hit = lowered.find(term.lower())
        if hit >= 0:
            break
    if hit < 0:
        return body[:200]
    start = max(0, hit - 60)
    return body[start : start + 240].replace("\n", " ").strip()


def search(query: str, limit: int = 10, include_body: bool = False) -> dict:
    started = time.perf_counter()
    index = ensure_cache()
    terms = _tokenize(query)
    if not terms:
        return {
            "ok": True,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "results": [],
        }

    scored: list[tuple[float, dict]] = []
    for record in index.get("files", []):
        title_l = record["label"].lower()
        kw_l = " ".join(record.get("keywords") or []).lower()
        desc_l = (record.get("description") or "").lower()
        score = 0.0
        for term in terms:
            tl = term.lower()
            if tl in title_l:
                score += 3
            if tl in kw_l:
                score += 2
            if tl in desc_l:
                score += 1
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda item: (-item[0], item[1]["path"]))
    root = resolve_root()
    results = []
    for score, record in scored[: max(1, limit)]:
        body = ""
        try:
            body = _read_any_text(root / record["path"])
        except Exception:
            body = ""
        body_score = sum(
            1 for term in terms if term.lower() in body.lower()
        )
        result = {
            "path": record["path"],
            "title": record["label"],
            "category": record["category"],
            "domain": record.get("domain"),
            "keywords": record.get("keywords") or [],
            "score": score + body_score,
            "snippet": _snippet(body, terms),
            "meta": record.get("meta") or {},
        }
        if include_body:
            result["content"] = body
        results.append(result)

    return {
        "ok": True,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "results": results,
    }


def graph(limit: int = 600, category: str = "all", q: str | None = None) -> dict:
    index = ensure_cache()
    nodes = list(index.get("nodes", []))
    if q and q.strip():
        needle = q.strip().lower()
        nodes = [
            n
            for n in nodes
            if needle in n["label"].lower()
            or needle in " ".join(n.get("keywords") or []).lower()
        ]
    if category and category != "all":
        nodes = [n for n in nodes if n["category"] == category]

    nodes.sort(key=lambda n: n.get("importance", 0.0), reverse=True)
    selected = nodes[: max(1, limit)]
    selected_ids = {n["id"] for n in selected}
    edges = [
        e
        for e in index.get("edges", [])
        if e["source"] in selected_ids and e["target"] in selected_ids
    ]
    by_category: dict[str, int] = defaultdict(int)
    for node in selected:
        by_category[node["category"]] += 1
    return {
        "ok": True,
        "stats": {
            "nodes": len(selected),
            "edges": len(edges),
            "by_category": dict(by_category),
        },
        "nodes": selected,
        "edges": edges,
    }
