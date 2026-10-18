"""Dynamic knowledge-graph learning engine.

Port of the CM-agentic dynamic-graph semantics (``DynamicGraphStore`` + the
learning-oriented dynamic-graph engine) to OpenKitsune Python:

- **Dynamic store** — AI-writable nodes/edges with JSON persistence in
  ``data/knowledge/dynamic_graph.json``, frontend-compatible with the existing
  KnowledgeGraph view (snake_case fields, same category colors).
- **Document ingestion** — feed parsed documents in, auto-extract candidate
  nodes (titles / chapter headings / high-frequency concepts) and
  co-occurrence relations.
- **Hebbian-style learning** — co-activated node pairs get their relation
  weight reinforced; repeated retrieval of a node raises its importance.
- **Community detection** — lightweight label-propagation clustering over the
  dynamic graph, mirroring the "社区发现" capability of the CM engine.
- **Hybrid retrieval** — keyword scoring over the static index (local_kb) plus
  graph-neighborhood expansion and weight-boosted ranking.

All mutations are guarded by a module-level lock and persisted atomically.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openkitsune.utils import atomic_io

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

DEFAULT_CATEGORY = "概念"
DEFAULT_EDGE_LABEL = "关联"
HEBBIAN_STRENGTHEN = 0.15       # weight added on each co-activation
HEBBIAN_DECAY = 0.02            # weight subtracted on each scan pass (forgetting)
IMPORTANCE_STRENGTHEN = 0.1     # importance bump per retrieval
IMPORTANCE_CAP = 1.0
MAX_DOC_NODES = 60              # candidate nodes per ingested document
MAX_DOC_EDGES = 120
STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "他", "她", "它", "们", "这个", "那个", "什么", "怎么", "为",
    "因为", "所以", "但是", "如果", "虽然", "而且", "并且", "或者", "还是", "不是",
    "可以", "可能", "应该", "需要", "必须", "已经", "正在", "将要", "之", "其", "此",
    "与", "及", "等", "中", "内", "外", "前", "后", "间", "时", "地", "得", "过",
}

_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------


def project_root() -> Path:
    try:
        from openkitsune.config import settings

        return Path(settings.project_root)
    except Exception:
        return Path.cwd()


def dynamic_graph_path() -> Path:
    return project_root() / "data" / "knowledge" / "dynamic_graph.json"


# ---------------------------------------------------------------------------
# Data model helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(label: str) -> str:
    return re.sub(r"[\s/\\:*?\"<>|]+", "-", label.strip())[:80] or "node"


def _node_id(label: str) -> str:
    return f"dyn:{_slugify(label)}"


def _edge_id(source: str, target: str, label: str) -> str:
    return f"edge:{source}|{target}|{label}"


def category_color(category: str) -> str:
    return CATEGORY_COLORS.get(category, CATEGORY_COLORS["其他"])


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class LearningError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def empty_graph() -> dict:
    return {"nodes": [], "edges": [], "version": 1, "updated_at": _now_iso()}


def _load_graph() -> dict:
    path = dynamic_graph_path()
    if not path.is_file():
        return empty_graph()
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return empty_graph()
    if not isinstance(data, dict) or "nodes" not in data:
        return empty_graph()
    return data


def _save_graph(graph: dict) -> None:
    graph["updated_at"] = _now_iso()
    dynamic_graph_path().parent.mkdir(parents=True, exist_ok=True)
    atomic_io.safe_write(
        dynamic_graph_path(), json.dumps(graph, ensure_ascii=False, indent=1)
    )


def _node_index(graph: dict) -> dict[str, dict]:
    return {node["id"]: node for node in graph["nodes"]}


def _edge_index(graph: dict) -> dict[str, dict]:
    return {edge["id"]: edge for edge in graph["edges"]}


# ---------------------------------------------------------------------------
# Node / edge CRUD (mirrors CM DynamicGraphStore ops)
# ---------------------------------------------------------------------------


def add_node(
    label: str,
    category: str | None = None,
    description: str = "",
    color: str | None = None,
    source_path: str | None = None,
    node_id: str | None = None,
    x: float | None = None,
    y: float | None = None,
) -> dict:
    """Create or update a dynamic node by label."""
    with _LOCK:
        graph = _load_graph()
        by_label = {n["label"]: n for n in graph["nodes"]}
        now = _now_iso()
        cat = category or DEFAULT_CATEGORY
        if node_id and node_id in _node_index(graph):
            node = _node_index(graph)[node_id]
            node["label"] = label
            node["category"] = cat
            node["color"] = color or category_color(cat)
            node["updated_at"] = now
            if description:
                node["description"] = description
            if source_path:
                node["source_path"] = source_path
            result = dict(node)
        elif label in by_label:
            node = by_label[label]
            node["category"] = cat
            node["color"] = color or category_color(cat)
            node["updated_at"] = now
            if description:
                node["description"] = description
            if source_path:
                node["source_path"] = source_path
            result = dict(node)
        else:
            node = {
                "id": node_id or _node_id(label),
                "label": label,
                "category": cat,
                "description": description,
                "x": x if x is not None else 0.0,
                "y": y if y is not None else 0.0,
                "color": color or category_color(cat),
                "source_path": source_path,
                "importance": 0.5,
                "created_at": now,
                "updated_at": now,
            }
            graph["nodes"].append(node)
            result = dict(node)
        _save_graph(graph)
        return result


def remove_node(node_id: str) -> dict:
    with _LOCK:
        graph = _load_graph()
        before = len(graph["nodes"])
        graph["nodes"] = [n for n in graph["nodes"] if n["id"] != node_id]
        graph["edges"] = [
            e for e in graph["edges"] if e["source"] != node_id and e["target"] != node_id
        ]
        if len(graph["nodes"]) == before:
            raise LearningError(f"节点不存在: {node_id}")
        _save_graph(graph)
        return {"ok": True, "removed": before - len(graph["nodes"])}


def get_node(node_id: str) -> dict:
    graph = _load_graph()
    node = _node_index(graph).get(node_id)
    if node is None:
        raise LearningError(f"节点不存在: {node_id}")
    return dict(node)


def list_nodes(limit: int = 100, category: str | None = None) -> dict:
    graph = _load_graph()
    nodes = graph["nodes"]
    if category and category != "all":
        nodes = [n for n in nodes if n["category"] == category]
    nodes = sorted(nodes, key=lambda n: n.get("importance", 0.0), reverse=True)
    return {"nodes": nodes[: max(1, min(limit, 500))], "total": len(nodes)}


def add_relation(
    source: str,
    target: str,
    label: str = DEFAULT_EDGE_LABEL,
    weight: float | None = None,
) -> dict:
    with _LOCK:
        graph = _load_graph()
        index = _node_index(graph)
        source_id = _resolve_node_ref(index, source)
        target_id = _resolve_node_ref(index, target)
        edge_id = _edge_id(source_id, target_id, label)
        now = _now_iso()
        weight = weight if weight is not None else 1.0
        if edge_id in _edge_index(graph):
            edge = _edge_index(graph)[edge_id]
            edge["weight"] = weight
            edge["updated_at"] = now
            result = dict(edge)
        else:
            edge = {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "label": label,
                "weight": weight,
                "created_at": now,
                "updated_at": now,
            }
            graph["edges"].append(edge)
            result = dict(edge)
        _save_graph(graph)
        return result


def remove_relation(edge_id: str) -> dict:
    with _LOCK:
        graph = _load_graph()
        before = len(graph["edges"])
        graph["edges"] = [e for e in graph["edges"] if e["id"] != edge_id]
        if len(graph["edges"]) == before:
            raise LearningError(f"关系不存在: {edge_id}")
        _save_graph(graph)
        return {"ok": True}


def _resolve_node_ref(index: dict[str, dict], ref: str) -> str:
    if ref in index:
        return ref
    by_label = {n["label"]: n["id"] for n in index.values()}
    if ref in by_label:
        return by_label[ref]
    raise LearningError(f"节点不存在（可用 label 或 id）: {ref}")


def get_related(node_id: str, limit: int = 20) -> dict:
    graph = _load_graph()
    index = _node_index(graph)
    node = index.get(node_id)
    if node is None:
        raise LearningError(f"节点不存在: {node_id}")
    related: list[dict] = []
    seen: set[str] = set()
    for edge in graph["edges"]:
        other = None
        if edge["source"] == node_id:
            other = edge["target"]
        elif edge["target"] == node_id:
            other = edge["source"]
        if other and other not in seen and other in index:
            seen.add(other)
            related.append(
                {
                    "node": index[other],
                    "relation": edge["label"],
                    "weight": edge.get("weight", 1.0),
                }
            )
    related.sort(key=lambda item: item["weight"], reverse=True)
    return {"node": node, "related": related[: max(1, limit)]}


def get_stats() -> dict:
    graph = _load_graph()
    by_category: dict[str, int] = Counter(n["category"] for n in graph["nodes"])
    by_label: dict[str, int] = Counter(e["label"] for e in graph["edges"])
    return {
        "nodes": len(graph["nodes"]),
        "edges": len(graph["edges"]),
        "by_category": dict(by_category),
        "by_relation": dict(by_label),
        "version": graph.get("version", 1),
        "updated_at": graph.get("updated_at"),
    }


def export_json() -> dict:
    return _load_graph()


def clear_all() -> dict:
    with _LOCK:
        _save_graph(empty_graph())
        return {"ok": True}


# ---------------------------------------------------------------------------
# Document ingestion ("AI 学习" from documents)
# ---------------------------------------------------------------------------


def _extract_concepts(text: str, top_n: int = 12) -> list[str]:
    freq: Counter[str] = Counter()
    for word in re.findall(r"[\u4e00-\u9fa5]{2,6}", text):
        if word in STOP_WORDS:
            continue
        freq[word] += 1
    items = [(w, c) for w, c in freq.items() if c >= 2]
    items.sort(key=lambda item: (-item[1], item[0]))
    return [w for w, _ in items[:top_n]]


def _extract_headings(text: str, top_n: int = 10) -> list[str]:
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        match = re.match(r"^#{1,4}\s+(.+)$", stripped)
        if match:
            title = re.sub(r"[*_`#]", "", match.group(1)).strip()
            if 2 <= len(title) <= 40 and title not in headings:
                headings.append(title)
        if len(headings) >= top_n:
            break
    return headings


def ingest_document(
    title: str,
    text: str,
    source_path: str | None = None,
    category_hint: str | None = None,
) -> dict:
    """Learn from a parsed document: auto-create nodes and co-occurrence edges.

    Mirrors the CM dynamic-graph "文档摄入" capability: a document becomes a
    ``文档`` node; its headings and frequent concepts become candidate nodes
    (``概念``/``典籍`` by hint); each candidate co-occurring with another in the
    body gains a ``关联`` edge with weight proportional to shared appearance.
    """
    with _LOCK:
        graph = _load_graph()
        now = _now_iso()

        doc_node = {
            "id": _node_id(f"doc-{title}"),
            "label": title,
            "category": "文档",
            "description": text[:200] if text else "",
            "x": 0.0,
            "y": 0.0,
            "color": CATEGORY_COLORS["文档"],
            "source_path": source_path,
            "importance": 0.5,
            "created_at": now,
            "updated_at": now,
        }
        by_label = {n["label"]: n for n in graph["nodes"]}
        if title not in by_label:
            graph["nodes"].append(doc_node)

        candidates: list[str] = []
        seen: set[str] = set()
        for heading in _extract_headings(text, top_n=10):
            if heading and heading not in seen:
                seen.add(heading)
                candidates.append(heading)
        for concept in _extract_concepts(text, top_n=12):
            if concept not in seen:
                seen.add(concept)
                candidates.append(concept)
        candidates = candidates[:MAX_DOC_NODES]

        # co-occurrence within a sliding window of lines
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        window: list[str] = []
        cooccur: Counter[tuple[str, str]] = Counter()
        for line in lines:
            window.append(line)
            if len(window) > 12:
                window.pop(0)
            present = [c for c in candidates if c in line]
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    a, b = present[i], present[j]
                    if a == b:
                        continue
                    cooccur[(a, b) if a < b else (b, a)] += 1

        created_nodes = 0
        created_edges = 0
        for label in candidates:
            if label not in by_label:
                cat = category_hint or ("典籍" if "经" in label or "藏" in label else "概念")
                graph["nodes"].append(
                    {
                        "id": _node_id(label),
                        "label": label,
                        "category": cat,
                        "description": "",
                        "x": 0.0,
                        "y": 0.0,
                        "color": category_color(cat),
                        "source_path": source_path,
                        "importance": 0.5,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                by_label[label] = graph["nodes"][-1]
                created_nodes += 1

        edge_index = {e["id"]: e for e in graph["edges"]}
        for (a, b), count in cooccur.most_common(MAX_DOC_EDGES):
            edge_id = _edge_id(by_label[a]["id"], by_label[b]["id"], "关联")
            if edge_id in edge_index:
                edge_index[edge_id]["weight"] = min(
                    5.0, (edge_index[edge_id].get("weight", 1.0) + count * 0.5)
                )
            else:
                graph["edges"].append(
                    {
                        "id": edge_id,
                        "source": by_label[a]["id"],
                        "target": by_label[b]["id"],
                        "label": "关联",
                        "weight": min(5.0, 1.0 + count * 0.5),
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                edge_index[edge_id] = graph["edges"][-1]
                created_edges += 1

        _save_graph(graph)
        return {
            "ok": True,
            "document": title,
            "candidates": len(candidates),
            "created_nodes": created_nodes,
            "created_edges": created_edges,
            "total_nodes": len(graph["nodes"]),
            "total_edges": len(graph["edges"]),
        }


# ---------------------------------------------------------------------------
# Hebbian-style learning & forgetting
# ---------------------------------------------------------------------------


def strengthen(node_ids: list[str], co_occur: list[tuple[str, str]] | None = None) -> dict:
    """Hebbian reinforcement: bump node importance and co-activated edge weights.

    Called when the user retrieves a set of nodes together — the relation among
    them is reinforced; unrelated edges slowly decay (forgetting).
    """
    with _LOCK:
        graph = _load_graph()
        index = _node_index(graph)
        now = _now_iso()
        touched = 0
        for node_id in node_ids:
            node = index.get(node_id)
            if node is None:
                continue
            node["importance"] = min(
                IMPORTANCE_CAP, node.get("importance", 0.5) + IMPORTANCE_STRENGTHEN
            )
            node["updated_at"] = now
            touched += 1

        edge_index = _edge_index(graph)
        strengthened = 0
        for source, target in co_occur or []:
            s = _resolve_node_ref(index, source)
            t = _resolve_node_ref(index, target)
            edge_id = _edge_id(s, t, "关联")
            if edge_id in edge_index:
                edge = edge_index[edge_id]
                edge["weight"] = min(5.0, edge.get("weight", 1.0) + HEBBIAN_STRENGTHEN)
                edge["updated_at"] = now
                strengthened += 1

        # forgetting: decay edges untouched in this pass
        decayed = 0
        for edge in graph["edges"]:
            if edge.get("updated_at") != now:
                new_weight = edge.get("weight", 1.0) - HEBBIAN_DECAY
                if new_weight <= 0.2:
                    edge["weight"] = 0.2
                else:
                    edge["weight"] = round(new_weight, 3)
                decayed += 1

        _save_graph(graph)
        return {
            "ok": True,
            "nodes_touched": touched,
            "edges_strengthened": strengthened,
            "edges_decayed": decayed,
        }


# ---------------------------------------------------------------------------
# Community detection (label propagation, simplified)
# ---------------------------------------------------------------------------


def community_detect(min_cluster: int = 3, max_iterations: int = 20) -> dict:
    """Label-propagation clustering over the dynamic graph.

    Nodes sharing strong ``关联`` edges converge to the same community label;
    communities smaller than ``min_cluster`` are reported as singletons.
    """
    graph = _load_graph()
    nodes = graph["nodes"]
    if not nodes:
        return {"communities": [], "total": 0}

    labels = {node["id"]: node["id"] for node in nodes}
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for edge in graph["edges"]:
        if edge["label"] != "关联":
            continue
        weight = edge.get("weight", 1.0)
        adjacency[edge["source"]].append((edge["target"], weight))
        adjacency[edge["target"]].append((edge["source"], weight))

    for _ in range(max_iterations):
        changed = False
        for node_id in list(labels):
            neighbors = adjacency.get(node_id, [])
            if not neighbors:
                continue
            counts: Counter[str] = Counter()
            for neighbor, weight in neighbors:
                counts[labels.get(neighbor, neighbor)] += weight
            if not counts:
                continue
            best_label = counts.most_common(1)[0][0]
            if best_label != labels[node_id]:
                labels[node_id] = best_label
                changed = True
        if not changed:
            break

    communities: dict[str, list[str]] = defaultdict(list)
    for node_id, label in labels.items():
        communities[label].append(node_id)

    result = []
    for label, members in communities.items():
        if len(members) < min_cluster:
            for member in members:
                result.append({"label": member, "size": 1, "members": [member]})
        else:
            result.append({"label": label, "size": len(members), "members": members})
    result.sort(key=lambda c: c["size"], reverse=True)
    return {"communities": result, "total": len(nodes)}


# ---------------------------------------------------------------------------
# Hybrid retrieval (keyword + graph neighborhood)
# ---------------------------------------------------------------------------


def hybrid_search(query: str, limit: int = 10, include_graph: bool = True) -> dict:
    """Keyword search over static index (local_kb) boosted by graph relevance.

    Score = keyword score (title 3 / keywords 2 / description 1) + graph boost
    (node importance + edge weight of neighbors matching the query).
    """
    started = time.perf_counter()
    from openkitsune.knowledge import local_kb

    index = local_kb.ensure_cache()
    terms = local_kb._tokenize(query)
    if not terms:
        return {"ok": True, "duration_ms": 0, "results": []}

    graph = _load_graph()
    dyn_nodes = graph["nodes"]
    dyn_by_label = {n["label"]: n for n in dyn_nodes}

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
        if score <= 0:
            continue
        if include_graph:
            dyn = dyn_by_label.get(record["label"])
            if dyn:
                score += dyn.get("importance", 0.5) * 2
            # neighbor boost
            for edge in graph["edges"]:
                if edge["source"] == f"file:{record['path']}" or edge["target"] == f"file:{record['path']}":
                    score += edge.get("weight", 1.0) * 0.5
        scored.append((score, record))

    scored.sort(key=lambda item: (-item[0], item[1]["path"]))
    root = local_kb.resolve_root()
    results = []
    for score, record in scored[: max(1, limit)]:
        body = ""
        try:
            body = local_kb._read_text(root / record["path"])
        except Exception:
            body = ""
        results.append(
            {
                "path": record["path"],
                "title": record["label"],
                "category": record["category"],
                "domain": record.get("domain"),
                "keywords": record.get("keywords") or [],
                "score": round(score, 3),
                "snippet": local_kb._snippet(body, terms),
            }
        )
    return {
        "ok": True,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "results": results,
    }
