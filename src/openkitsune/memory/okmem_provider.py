"""okmem 记忆系统接入适配器（仅记忆，不含自愈大脑）。

把旧工程 ``E:\\agents\\openkitsune-brain`` 中的两层记忆能力接入
:mod:`openkitsune.memory.public_api`：

1. **okmem（读写）** —— 九格式记忆 + 六记忆池 + 四维图谱 + 进度层。
   通过 ``okmem.MemorySystem`` 进程内调用，不需要 brain-bus 服务在线。
2. **okmem 知识库（只读）** —— 原 fusion-memory 数据目录 ``data/fusion-memory/xuan-yi/knowledge.db``
   中的 memories / entities / relations / formulas / acupoints 等真实知识数据。

自愈大脑（cases / incidents / 故障动作）不在本适配器范围内，避免把运维状态
混入对话记忆。

接入方式::

    from openkitsune.memory import create_memory_api
    from openkitsune.memory.okmem_provider import create_okmem_provider

    api = create_memory_api(agent.memory_manager)
    api.register_provider(create_okmem_provider(), mode="augment")

    hits = await api.search("河图洛书 五行")
    context = await api.get_injection_context("帮我复习五行与五脏")

除标准 Provider 方法外，本适配器还把 okmem 的高价值方法暴露为工具，
见 :data:`OKMEM_TOOL_SCHEMAS` 与 :func:`dispatch_okmem_tool`。

读取策略：
- 不做静默截断。``search`` / ``get`` 返回的都是显式内容页，附带
  ``content_total`` / ``has_more`` / ``next_offset``；
- 用 ``read_content(memory_id, offset, limit)`` 或公共接口
  ``MemorySystemAPI.get_content`` 可无损续读全文；
- 上下文注入按预算做增量加载，放不下的记录只输出
  ``memory_read(...)`` 清单，不切断句子。

执行策略：
- 不并发写 SQLite。所有 okmem 操作进入单线程异步队列（FIFO），
  队列指标通过 ``queue_stats()`` / ``stats()["queue"]`` 查看。
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import json
import logging
import math
import os
import re
import socket
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .public_api import MemoryRecord, build_page_token, content_hash
from .types import normalize_tags

if TYPE_CHECKING:
    from okmem import MemorySystem as OkmemMemorySystem

logger = logging.getLogger(__name__)


def _normalize_okmem_home(value: str | Path) -> str:
    """把 Windows 盘符路径转换为 WSL 挂载路径（仅在非 Windows 平台）。"""
    raw = str(value or "").strip()
    if not raw or os.name == "nt":
        return raw
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", raw)
    if match:
        rest = match.group(2).replace("\\", "/").lstrip("/")
        return f"/mnt/{match.group(1).lower()}/{rest}"
    return raw


def _default_okmem_home() -> str:
    """自动选择可用的 okmem 数据目录。

    优先级：环境变量 > WSL 挂载路径 > Windows 路径 > 用户目录。
    """
    env_home = os.environ.get("OPENKITSUNE_OKMEM_HOME")
    if env_home:
        return _normalize_okmem_home(env_home)

    candidates = (
        Path("/mnt/e/agents/openkitsune-brain"),
        Path(r"E:\agents\openkitsune-brain"),
        Path.home() / "openkitsune-brain",
    )
    for candidate in candidates:
        if (candidate / "okmem").is_dir():
            return str(candidate)
    return str(candidates[-1])


DEFAULT_OKMEM_HOME = _default_okmem_home()

# 公共记忆类型 → okmem 九格式
_OKMEM_FMT_BY_TYPE = {
    "fact": "semantic",
    "preference": "semantic",
    "rule": "semantic",
    "skill": "procedural",
    "error": "reflective",
    "experience": "reflective",
    "context": "working",
}

# okmem 九格式 → 公共记忆类型
_TYPE_BY_OKMEM_FMT = {
    "semantic": "fact",
    "episodic": "experience",
    "working": "context",
    "session": "context",
    "task": "context",
    "procedural": "skill",
    "reflective": "experience",
    "experiential": "experience",
    "conceptual": "fact",
    "operational": "skill",
    "self_model": "persona_trait",
    "graph": "fact",
}

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_TERM_SPLIT = re.compile(r"[\s,，、;；:：/|()（）\[\]【】]+")
# 高频虚词：含这些字符的 bigram 噪声大，不参与召回
_STOP_CHARS = set(
    "的了与和及是在有我你他她它这那请帮吗呢吧啊就都也还又很更最把被给让向从对为以于而之其"
)
_DEFAULT_SEARCH_PAGE_SIZE = 1200
_DEFAULT_CONTENT_PAGE_SIZE = 4000
# 单 worker 优先级队列：不并发，只决定谁先执行
PRIORITY_READ = 0
PRIORITY_WRITE = 1
PRIORITY_INDEX = 2
PRIORITY_MAINTENANCE = 3
_PRIORITY_NAMES = {
    PRIORITY_READ: "P0",
    PRIORITY_WRITE: "P1",
    PRIORITY_INDEX: "P2",
    PRIORITY_MAINTENANCE: "P3",
}
_PRIORITY_DEADLINE_S = {
    PRIORITY_READ: 3.0,
    PRIORITY_WRITE: 10.0,
    PRIORITY_INDEX: 30.0,
    PRIORITY_MAINTENANCE: 60.0,
}
_P0_BACKPRESSURE_LIMIT = 20
# 跨源融合权重（RRF）
_SOURCE_WEIGHTS = {
    "okmem": 1.0,
    "okmem-kb": 1.0,
    "okmem-kb-fts": 0.85,
    "okmem-kb-entity": 0.9,
    "pending": 1.2,
}
# 领域同义词扩展（只用于召回，不参与词法重叠打分）
_QUERY_SYNONYMS = {
    "五行": ("五脏", "五色", "五音"),
    "五脏": ("五行", "五藏"),
    "桂枝汤": ("伤寒论",),
    "伤寒论": ("桂枝汤",),
    "河图": ("洛书",),
    "洛书": ("河图",),
    "体用": ("体用框架",),
    "五运六气": ("子午流注",),
    "子午流注": ("五运六气",),
}
# 多信号情绪规则（快路径）；低置信度不注入上下文
_EMOTION_RULES: dict[str, tuple[str, ...]] = {
    "疲惫": ("累", "疲惫", "困", "乏力", "没精神", "没力气"),
    "焦虑": ("焦虑", "紧张", "压力", "担心", "不安", "慌"),
    "低落": ("难过", "低落", "沮丧", "失落", "郁闷", "想哭"),
    "愤怒": ("生气", "愤怒", "火大", "烦死", "恼火"),
    "平静": ("平静", "放松", "安心", "舒服", "轻松"),
}


def _expand_terms(terms: list[str], limit: int = 12) -> list[str]:
    expanded = list(terms)
    for term in terms:
        for synonym in _QUERY_SYNONYMS.get(term, ()):
            if synonym not in expanded:
                expanded.append(synonym)
    return expanded[:limit]


def detect_emotion_signal(text: str) -> dict[str, Any]:
    """规则 + 语气/标点多信号情绪识别；低置信度返回 neutral。"""
    text = str(text or "").strip()
    if not text:
        return {
            "emotion": "neutral",
            "intensity": 0.0,
            "evidence": [],
            "confidence": 0.0,
        }
    best_label = "neutral"
    best_evidence: list[str] = []
    for label, keywords in _EMOTION_RULES.items():
        matches = [keyword for keyword in keywords if keyword in text]
        if len(matches) > len(best_evidence):
            best_label = label
            best_evidence = matches
    if not best_evidence:
        return {
            "emotion": "neutral",
            "intensity": 0.0,
            "evidence": [],
            "confidence": 0.2,
        }

    intensity = 0.5 + 0.12 * (len(best_evidence) - 1)
    if any(mark in text for mark in ("！", "!", "非常", "特别", "太")):
        intensity += 0.15
    if any(mark in text for mark in ("…", "...", "有点", "稍微")):
        intensity -= 0.1
    confidence = 0.55 + 0.1 * (len(best_evidence) - 1)
    if any(mark in text for mark in ("…", "...", "也许", "可能", "好像")):
        confidence -= 0.15
    return {
        "emotion": best_label,
        "intensity": round(max(0.0, min(1.0, intensity)), 2),
        "evidence": best_evidence,
        "confidence": round(max(0.0, min(0.95, confidence)), 2),
    }


def _page_text(content: str, offset: int = 0, limit: int = _DEFAULT_CONTENT_PAGE_SIZE) -> str:
    """取一页内容，并尽量在段落/句子边界结束，避免把句子切成两半。"""
    total = len(content)
    offset = max(0, min(int(offset), total))
    limit = max(1, int(limit))
    end = min(total, offset + limit)
    if end < total:
        window = content[offset:end]
        candidates = [
            window.rfind("\n\n"),
            window.rfind("\n"),
            window.rfind("。"),
            window.rfind("；"),
            window.rfind("！"),
            window.rfind("？"),
        ]
        cut = max(candidates)
        # 边界太靠前会浪费预算，至少保留页面的 60%
        if cut >= int(len(window) * 0.6):
            boundary = 2 if window[cut : cut + 2] == "\n\n" else 1
            end = offset + cut + boundary
        else:
            # 页面内没有合适边界：向后找最近边界（最多多取 200 字），
            # 宁可页面略超预算，也不把一句话切成两半。
            tail = content[end : min(total, end + 200)]
            tail_candidates = [
                tail.find("\n\n"),
                tail.find("\n"),
                tail.find("。"),
                tail.find("；"),
                tail.find("！"),
                tail.find("？"),
            ]
            tail_cut = min((i for i in tail_candidates if i >= 0), default=-1)
            if tail_cut >= 0:
                boundary = 2 if tail[tail_cut : tail_cut + 2] == "\n\n" else 1
                end = end + tail_cut + boundary
    return content[offset:end]


def _page_payload(
    memory_id: str,
    content: str,
    *,
    provider: str = "",
    offset: int = 0,
    limit: int = _DEFAULT_CONTENT_PAGE_SIZE,
) -> dict[str, Any]:
    total = len(content)
    offset = max(0, min(int(offset), total))
    chunk = _page_text(content, offset, limit)
    next_offset = offset + len(chunk)
    full_hash = content_hash(content)
    snapshot = full_hash[:12]

    def token(at: int) -> str:
        return build_page_token(
            memory_id=memory_id,
            provider=provider,
            offset=at,
            limit=limit,
            content_hash_value=full_hash,
            snapshot_version=snapshot,
        )

    return {
        "ok": True,
        "memory_id": memory_id,
        "provider": provider,
        "content": chunk,
        "offset": offset,
        "total": total,
        "has_more": next_offset < total,
        "next_offset": next_offset,
        "content_hash": full_hash,
        "snapshot_version": snapshot,
        "page_soft_limit": len(chunk) > limit,
        "page_token": token(offset),
        "next_page_token": token(next_offset) if next_offset < total else "",
    }


def _readonly_uri(path: Path) -> str:
    return path.resolve().as_uri() + "?mode=ro"


def _query_terms(query: str, limit: int = 8) -> list[str]:
    """把查询拆成整串 + 分词 + 中文 bigram，供 LIKE 召回使用。

    bigram 会过滤含高频虚词的组合（如「行与」「与五」），并按长度降序，
    优先保留信息量更高的词。
    """
    text = (query or "").strip()
    if not text:
        return []
    terms: list[str] = [text]
    terms.extend(t for t in _TERM_SPLIT.split(text) if len(t) >= 2)
    for run in _CJK_RUN.findall(text):
        for i in range(len(run) - 1):
            bigram = run[i : i + 2]
            if bigram[0] in _STOP_CHARS or bigram[1] in _STOP_CHARS:
                continue
            terms.append(bigram)
    unique = {term for term in terms if term}
    ordered = sorted(unique, key=len, reverse=True)
    return ordered[:limit]


def _port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _count_tables(db: Path, names: tuple[str, ...]) -> dict[str, int]:
    """只读统计若干表的行数；表缺失时跳过。"""
    result: dict[str, int] = {}
    if not db.exists():
        return result
    try:
        conn = sqlite3.connect(_readonly_uri(db), uri=True, timeout=5)
        try:
            for name in names:
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
                except sqlite3.Error:
                    continue
                result[name] = int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("[Okmem] count %s failed: %s", db, exc)
    return result


class OkmemProvider:
    """okmem 记忆 Provider（okmem 读写 + 知识库只读）。"""

    name = "okmem"

    def __init__(
        self,
        *,
        name: str = "okmem",
        home: str | Path | None = None,
        okmem_db: str | Path | None = None,
        knowledge_db: str | Path | None = None,
        session_id: str = "openkitsune",
        dim: int | None = None,
        embed_url: str | None = None,
        auto_embed: bool = True,
        search_page_size: int = _DEFAULT_SEARCH_PAGE_SIZE,
        content_page_size: int = _DEFAULT_CONTENT_PAGE_SIZE,
    ) -> None:
        self.name = name or "okmem"
        self.home = Path(home or DEFAULT_OKMEM_HOME)
        self.okmem_db = Path(
            okmem_db or os.environ.get("OKMEM_DB") or self.home / "data" / "okmem" / "memory.db"
        )
        self.knowledge_db = Path(
            knowledge_db or self.home / "data" / "fusion-memory" / "xuan-yi" / "knowledge.db"
        )
        self.session_id = session_id
        self.dim = dim
        self.embed_url = embed_url
        self.auto_embed = auto_embed
        self.embed_mode = "uninitialized"
        self.search_page_size = max(200, int(search_page_size))
        self.content_page_size = max(self.search_page_size, int(content_page_size))
        self._ms: OkmemMemorySystem | None = None
        self._okmem_error = ""
        self._lock = threading.RLock()
        # 单 worker 优先级队列：所有 okmem 调用串行进入单线程执行器。
        # 读 P0 / 写 P1 / 索引 P2 / 维护 P3，避免后台任务阻塞用户读。
        self._queue: asyncio.PriorityQueue | None = None
        self._queue_worker: asyncio.Task | None = None
        self._queue_loop: asyncio.AbstractEventLoop | None = None
        self._queue_seq = 0
        self._queue_depths = dict.fromkeys(_PRIORITY_NAMES, 0)
        self._queue_waits: list[float] = []
        self._queue_processed_by = dict.fromkeys(_PRIORITY_NAMES, 0)
        self._queue_rejected = 0
        self._queue_timeouts = 0
        self._queue_cancelled = 0
        # 两阶段写入：先登记 pending（立即可被检索），后台 P1 落盘。
        self._pending_writes: dict[str, dict[str, Any]] = {}
        self._event_results: dict[str, dict[str, Any]] = {}
        self._background_tasks: set[asyncio.Task] = set()
        # 只读知识/案例内容的页级缓存（10 分钟，最多 128 条）
        self._content_cache: dict[str, tuple[float, str]] = {}
        self._content_cache_hits = 0
        self._content_cache_misses = 0
        self._content_cache_ttl = 600.0
        self._content_cache_max = 128
        # okmem 内部持有 sqlite3 连接（默认 check_same_thread=True）。所有
        # okmem 调用都必须落在同一个工作线程，否则切线程会触发 ProgrammingError。
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="okmem")

    def _resolve_embed_url(self) -> str:
        """显式配置 > 环境变量 > 本机 8120 自动探测 > 哈希伪嵌入。"""
        if self.embed_url:
            return self.embed_url
        env_url = os.environ.get("OKMEM_EMBED_URL", "")
        if env_url:
            return env_url
        if self.auto_embed and _port_open("127.0.0.1", 8120):
            return "http://127.0.0.1:8120/v1/embeddings"
        return ""

    def _ensure_queue(self, loop: asyncio.AbstractEventLoop) -> None:
        if (
            self._queue is not None
            and self._queue_loop is loop
            and self._queue_worker is not None
            and not self._queue_worker.done()
        ):
            return
        if self._queue_worker is not None and not self._queue_worker.done():
            self._queue_worker.cancel()
        self._queue = asyncio.PriorityQueue()
        self._queue_loop = loop
        self._queue_worker = loop.create_task(self._queue_worker_loop())
        self._queue_worker.add_done_callback(self._consume_worker_result)

    @staticmethod
    def _consume_worker_result(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        with contextlib.suppress(Exception):
            task.exception()

    async def _queue_worker_loop(self) -> None:
        """单 worker：按优先级串行执行，永不并发访问 SQLite。"""
        queue = self._queue
        loop = self._queue_loop
        if queue is None or loop is None:
            return
        while True:
            item = await queue.get()
            if item is None:
                queue.task_done()
                return
            priority, _seq, future, fn, args, kwargs, deadline = item
            self._queue_depths[priority] = max(0, self._queue_depths[priority] - 1)
            if future.cancelled():
                self._queue_cancelled += 1
                queue.task_done()
                continue
            if loop.time() > deadline:
                self._queue_timeouts += 1
                if not future.done():
                    future.set_exception(
                        TimeoutError(f"queue timeout at {_PRIORITY_NAMES[priority]}")
                    )
                queue.task_done()
                continue
            try:
                result = await loop.run_in_executor(
                    self._executor, functools.partial(fn, *args, **kwargs)
                )
            except asyncio.CancelledError:
                if not future.done():
                    future.cancel()
                queue.task_done()
                raise
            except Exception as exc:  # noqa: BLE001
                if not future.done():
                    future.set_exception(exc)
            else:
                if not future.done():
                    future.set_result(result)
            finally:
                queue.task_done()

    async def _enqueue(self, priority: int, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """按优先级入队并等待结果；P0 拥塞时对 P2/P3 施加背压。"""
        loop = asyncio.get_running_loop()
        self._ensure_queue(loop)
        priority = int(priority)
        if (
            priority >= PRIORITY_INDEX
            and self._queue_depths[PRIORITY_READ] > _P0_BACKPRESSURE_LIMIT
        ):
            self._queue_rejected += 1
            raise RuntimeError("background queue full: P0 backpressure")
        future = loop.create_future()
        self._queue_seq += 1
        self._queue_depths[priority] += 1
        deadline = loop.time() + _PRIORITY_DEADLINE_S.get(priority, 10.0)
        await self._queue.put((priority, self._queue_seq, future, fn, args, kwargs, deadline))
        started = time.perf_counter()
        try:
            result = await future
        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            self._queue_cancelled += 1
            raise
        finally:
            self._queue_waits.append((time.perf_counter() - started) * 1000)
            if len(self._queue_waits) > 200:
                self._queue_waits.pop(0)
            self._queue_processed_by[priority] += 1
        return result

    async def _thread(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """兼容旧调用：默认按写任务（P1）排队。"""
        return await self._enqueue(PRIORITY_WRITE, fn, *args, **kwargs)

    def queue_stats(self) -> dict[str, Any]:
        waits = sorted(self._queue_waits)
        p95 = waits[int(0.95 * (len(waits) - 1))] if waits else 0.0
        return {
            "mode": "serial_priority_queue",
            "depth_by_priority": {
                name: self._queue_depths[priority] for priority, name in _PRIORITY_NAMES.items()
            },
            "processed_by_priority": {
                name: self._queue_processed_by[priority]
                for priority, name in _PRIORITY_NAMES.items()
            },
            "waiting": sum(self._queue_depths.values()),
            "p95_wait_ms": round(p95, 2),
            "max_wait_ms": round(max(waits), 2) if waits else 0.0,
            "rejected_p2_p3": self._queue_rejected,
            "timeouts": self._queue_timeouts,
            "cancelled": self._queue_cancelled,
        }

    def _cancel_queue(self) -> None:
        worker = self._queue_worker
        if worker is not None and not worker.done():
            worker.cancel()
        self._queue_worker = None
        self._queue = None

    # ------------------------------------------------------------------
    # okmem 生命周期
    # ------------------------------------------------------------------

    @property
    def okmem_available(self) -> bool:
        if self._ms is not None:
            return True
        if self._okmem_error:
            return False
        return (self.home / "okmem").is_dir()

    def _ensure_okmem(self) -> OkmemMemorySystem | None:
        if self._ms is not None:
            return self._ms
        if self._okmem_error:
            return None
        home = str(self.home)
        if home not in sys.path:
            sys.path.insert(0, home)
        try:
            from okmem import MemorySystem

            self.okmem_db.parent.mkdir(parents=True, exist_ok=True)
            resolved_embed = self._resolve_embed_url()
            self.embed_mode = "real" if resolved_embed else "hash"
            self._ms = MemorySystem(
                db_path=str(self.okmem_db),
                dim=self.dim,
                embed_url=resolved_embed or None,
                session_id=self.session_id,
            )
        except Exception as exc:  # noqa: BLE001 —— 外部项目不可用不能阻断宿主
            self._okmem_error = str(exc)
            logger.warning("[Okmem] okmem unavailable at %s: %s", self.home, exc)
            return None
        return self._ms

    def close(self) -> None:
        for task in list(self._background_tasks):
            task.cancel()
        self._cancel_queue()
        if self._ms is None:
            self._executor.shutdown(wait=False)
            return
        try:
            self._executor.submit(self._close_sync).result(timeout=10)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Okmem] close failed: %s", exc)
        finally:
            self._executor.shutdown(wait=False)

    def _close_sync(self) -> None:
        if self._ms is not None:
            with self._lock:
                self._ms.close()
            self._ms = None

    # ------------------------------------------------------------------
    # MemoryProvider 标准接口
    # ------------------------------------------------------------------

    async def add(self, memory: MemoryRecord) -> str:
        return await self._enqueue(PRIORITY_WRITE, self._add_sync, memory)

    async def add_deferred(self, memory: MemoryRecord) -> dict[str, Any]:
        """两阶段写入：立即返回 event_id，后台队列完成落盘与索引。"""
        event_id = f"evt-{time.time_ns():x}"
        self._pending_writes[event_id] = {
            "record": memory,
            "status": "queued",
            "enqueued_at": time.time(),
        }
        loop = asyncio.get_running_loop()

        async def runner() -> None:
            try:
                memory_id = await self._enqueue(PRIORITY_WRITE, self._add_sync, memory)
            except Exception as exc:  # noqa: BLE001
                self._pending_writes.pop(event_id, None)
                self._record_event(
                    event_id,
                    {"status": "failed", "error": str(exc), "memory_id": ""},
                )
                return
            self._pending_writes.pop(event_id, None)
            self._record_event(
                event_id,
                {"status": "indexed", "error": "", "memory_id": memory_id},
            )

        task = loop.create_task(runner())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return {"event_id": event_id, "status": "queued", "index_pending": True}

    def _record_event(self, event_id: str, payload: dict[str, Any]) -> None:
        self._event_results[event_id] = payload
        if len(self._event_results) > 200:
            oldest = next(iter(self._event_results))
            self._event_results.pop(oldest, None)

    async def event_status(self, event_id: str) -> dict[str, Any]:
        if event_id in self._pending_writes:
            return {"event_id": event_id, "status": "queued", "index_pending": True}
        result = self._event_results.get(event_id)
        if result is None:
            return {"event_id": event_id, "status": "unknown", "index_pending": False}
        return {
            "event_id": event_id,
            "status": result.get("status", "unknown"),
            "memory_id": result.get("memory_id", ""),
            "error": result.get("error", ""),
            "index_pending": result.get("status") != "indexed",
        }

    def _pending_record(self, event_id: str, *, score: float = 0.5) -> MemoryRecord | None:
        entry = self._pending_writes.get(event_id)
        if not entry:
            return None
        source: MemoryRecord = entry["record"]
        return MemoryRecord(
            id=f"pending:{event_id}",
            content=source.content,
            type=source.type,
            priority=source.priority,
            importance=source.importance,
            subject=source.subject,
            predicate=source.predicate,
            tags=list(source.tags),
            source=source.source,
            created_at=source.created_at,
            updated_at=source.updated_at,
            content_total=len(source.content),
            next_offset=len(source.content),
            score=score,
            provider=self.name,
            metadata={"backend": "pending", "pending": True, "event_id": event_id},
        )

    def _pending_search(self, query: str, limit: int) -> list[MemoryRecord]:
        """读己之写：未落盘的 pending 记录也参与本轮检索。"""
        if not self._pending_writes:
            return []
        terms = _query_terms(query) if query else []
        records: list[MemoryRecord] = []
        for event_id, entry in list(self._pending_writes.items()):
            source: MemoryRecord = entry["record"]
            if query:
                haystack = f"{source.content} {' '.join(source.tags)}".lower()
                overlap = (
                    sum(1 for term in terms if term.lower() in haystack) / len(terms)
                    if terms
                    else 0.0
                )
                if overlap == 0:
                    continue
                score = 0.5 + 0.5 * overlap
            else:
                score = 0.5
            record = self._pending_record(event_id, score=score)
            if record is not None:
                records.append(record)
        return self._rank(records, limit)

    def _add_sync(self, memory: MemoryRecord) -> str:
        ms = self._ensure_okmem()
        if ms is None:
            raise RuntimeError(f"okmem unavailable: {self._okmem_error}")
        metadata = dict(memory.metadata or {})
        entities = metadata.get("entities") or None
        with self._lock:
            mid = ms.write(
                memory.content,
                fmt=_OKMEM_FMT_BY_TYPE.get(memory.type, "semantic"),
                source=memory.source or "openkitsune",
                entities=entities,
                tags=memory.tags or None,
                observed_at=memory.created_at or None,
                confidence=memory.importance,
                salience=memory.importance,
                meta=metadata or None,
                session_id=self.session_id,
                summary=memory.predicate or None,
            )
        return f"okmem:{mid}"

    async def search(self, query: str = "", limit: int = 10) -> list[MemoryRecord]:
        return await self._enqueue(PRIORITY_READ, self._search_sync, query, limit)

    def _search_sync(self, query: str, limit: int) -> list[MemoryRecord]:
        sources: dict[str, list[MemoryRecord]] = {}
        ms = self._ensure_okmem()
        if ms is not None:
            with self._lock:
                if query:
                    hits = ms.query(
                        query,
                        topk=limit,
                        # 真实 embedding 维度被截断到 64，纯向量排序噪声较大；
                        # 提高关键词权重，向量保留语义兜底。
                        weights={"vec": 0.2, "kw": 0.5, "graph": 0.1, "time": 0.1, "salience": 0.1},
                    )
                else:
                    hits = ms.store.active_memories()[:limit]
            sources["okmem"] = [
                self._okmem_record(hit, page_size=self.search_page_size) for hit in hits
            ]
        else:
            sources["okmem"] = []
        sources["okmem-kb"] = self._knowledge_search(query, limit)
        sources["okmem-kb-fts"] = self._knowledge_fts_search(query, limit)
        sources["okmem-kb-entity"] = self._knowledge_entity_search(query, limit)
        sources["pending"] = self._pending_search(query, limit)
        return self._fuse_sources(sources, limit, query=query)

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return await self._enqueue(PRIORITY_READ, self._get_sync, memory_id)

    def _strip_provider_prefix(self, memory_id: str) -> str:
        prefix = f"{self.name}:"
        return memory_id[len(prefix) :] if memory_id.startswith(prefix) else memory_id

    def _get_sync(self, memory_id: str) -> MemoryRecord | None:
        memory_id = self._strip_provider_prefix(str(memory_id))
        if memory_id.startswith("pending:"):
            return self._pending_record(memory_id.split(":", 1)[1])
        source, _, raw_id = memory_id.partition(":")
        if source in ("", "okmem"):
            mid = raw_id or str(memory_id)
            ms = self._ensure_okmem()
            if ms is None or not mid.isdigit():
                return None
            with self._lock:
                hit = ms.store.get_memory(int(mid))
            if not hit or hit.get("state") != "active":
                return None
            return self._okmem_record(hit, page_size=self.content_page_size)
        if source in ("okmem-kb", "knowledge"):
            return self._knowledge_get(raw_id)
        if source in ("okmem-kb-fts", "knowledge-fts"):
            return self._knowledge_fts_get(raw_id)
        return None

    async def delete(self, memory_id: str) -> bool:
        return await self._enqueue(PRIORITY_WRITE, self._delete_sync, memory_id)

    def _delete_sync(self, memory_id: str) -> bool:
        memory_id = self._strip_provider_prefix(str(memory_id))
        if memory_id.startswith("pending:"):
            return self._pending_writes.pop(memory_id.split(":", 1)[1], None) is not None
        source, _, raw_id = memory_id.partition(":")
        if source not in ("", "okmem"):
            return False  # 知识库为只读数据源
        mid = raw_id or str(memory_id)
        ms = self._ensure_okmem()
        if ms is None or not mid.isdigit():
            return False
        with self._lock:
            row = ms.store.get_memory(int(mid))
            if not row or row.get("state") != "active":
                return False
            ms.store.update_memory(int(mid), state="forgotten")
        return True

    async def stats(self) -> dict[str, Any]:
        return await self._enqueue(PRIORITY_WRITE, self._stats_sync)

    def _stats_sync(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "okmem": {},
            "knowledge": {},
            "embed": {"mode": self.embed_mode},
            "queue": self.queue_stats(),
            "cache": self.cache_stats(),
        }
        ms = self._ensure_okmem()
        if ms is not None:
            with self._lock:
                result["okmem"] = ms.stats()
                with contextlib.suppress(Exception):
                    result["embed"] = {"mode": self.embed_mode, **ms.embed_status()}
        result["knowledge"] = _count_tables(
            self.knowledge_db,
            (
                "memories",
                "memories_fts",
                "entities",
                "relations",
                "formulas",
                "acupoints",
                "chengyao_medicine",
            ),
        )
        return result

    async def get_injection_context(self, query: str = "", max_tokens: int = 700) -> str:
        return await self._enqueue(PRIORITY_READ, self._context_sync, query, max_tokens)

    async def build_context(self, query: str = "", max_tokens: int = 700) -> dict[str, Any]:
        """返回 ContextBundle：text + manifest + tokens_used。"""
        return await self._enqueue(PRIORITY_READ, self._build_context_sync, query, max_tokens)

    def _context_sync(self, query: str, max_tokens: int) -> str:
        return str(self._build_context_sync(query, max_tokens)["text"])

    def _build_context_sync(self, query: str, max_tokens: int) -> dict[str, Any]:
        budget = max(200, int(max_tokens) * 4)
        parts: list[str] = []
        manifest: list[dict[str, Any]] = []
        used = 0

        def add(text: str) -> bool:
            nonlocal used
            if not text:
                return False
            cost = len(text) + (2 if parts else 0)
            if used + cost > budget:
                return False
            parts.append(text)
            used += cost
            return True

        def add_paged(
            label: str,
            content: str,
            total: int,
            memory_id: str,
            content_hash_value: str,
        ) -> None:
            # 预留 header + manifest 的空间；预算太小时只放清单，不放半句内容
            remaining = budget - used - 140
            if remaining < 120:
                add(f"- [{label}] {memory_id}（预算不足，未加载；可调用 memory_read 继续）")
                manifest.append(
                    {
                        "memory_id": memory_id,
                        "loaded_offset": 0,
                        "total": total,
                        "next_token": "",
                        "reason": "budget",
                    }
                )
                return
            page = _page_text(content, 0, min(remaining, self.content_page_size))
            if not page:
                return
            if not add(f"- [{label}] {page}"):
                return
            end = len(page)
            if end < total:
                next_token = build_page_token(
                    memory_id=memory_id,
                    provider=self.name,
                    offset=end,
                    limit=self.content_page_size,
                    content_hash_value=content_hash_value,
                )
                add(
                    f"  ↳ 未完全加载：{memory_id} 已加载 {end}/{total} 字，"
                    f'可调用 memory_read(memory_id="{memory_id}", offset={end}) 继续'
                )
                manifest.append(
                    {
                        "memory_id": memory_id,
                        "loaded_offset": end,
                        "total": total,
                        "next_token": next_token,
                        "reason": "budget",
                    }
                )

        ms = self._ensure_okmem()
        if ms is not None and query:
            try:
                with self._lock:
                    working_set = ms.assemble(query)
                text = str(working_set.get("text") or "").strip()
                if text:
                    limit = max(120, budget - used - 120)
                    page = _page_text(text, 0, limit)
                    if add("【okmem 工作集】\n" + page) and len(page) < len(text):
                        add(
                            f"[okmem 工作集未完全加载：{len(page)}/{len(text)} 字，"
                            "可调用 okmem_progress 或 memory_read 继续]"
                        )
                        manifest.append(
                            {
                                "memory_id": "okmem:workset",
                                "loaded_offset": len(page),
                                "total": len(text),
                                "next_token": "",
                                "reason": "workset_budget",
                            }
                        )
            except Exception as exc:  # noqa: BLE001
                logger.debug("[Okmem] assemble failed: %s", exc)

            signal = detect_emotion_signal(query)
            if signal["confidence"] >= 0.5:
                with contextlib.suppress(Exception):
                    with self._lock:
                        emotion = ms.emotion_state()
                    if emotion:
                        text = "【情绪状态】" + json.dumps(
                            {"detected": signal, "state": emotion},
                            ensure_ascii=False,
                            default=str,
                        )
                        add(_page_text(text, 0, max(120, budget - used)))

        records = self._search_sync(query, 8) if query else []
        records = self._filter_context_records(records)
        if records and add("【跨库召回】"):
            for record in records[:8]:
                remaining = budget - used - 140
                if remaining < 120:
                    add(
                        f"- [{_record_label(record)}] {record.id}"
                        "（预算不足，未加载；可调用 memory_read 继续）"
                    )
                    manifest.append(
                        {
                            "memory_id": record.id,
                            "loaded_offset": 0,
                            "total": record.content_total or len(record.content),
                            "next_token": record.page_token,
                            "reason": "budget",
                        }
                    )
                    continue
                page = self._read_content_sync(record.id, 0, min(remaining, self.content_page_size))
                if page.get("ok"):
                    add_paged(
                        _record_label(record),
                        str(page["content"]),
                        int(page["total"]),
                        record.id,
                        str(page.get("content_hash") or ""),
                    )
                else:
                    add_paged(
                        _record_label(record),
                        record.content,
                        record.content_total or len(record.content),
                        record.id,
                        content_hash(record.content),
                    )

        return {
            "text": "\n\n".join(parts),
            "manifest": manifest,
            "tokens_used": used,
            "budget": budget,
        }

    @staticmethod
    def _filter_context_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
        """上下文注入优先长期记忆：session/working 最多保留 2 条。"""
        filtered: list[MemoryRecord] = []
        ephemeral = 0
        for record in records:
            fmt = str(record.metadata.get("fmt") or "")
            if fmt in ("session", "working"):
                if ephemeral >= 2:
                    continue
                ephemeral += 1
            filtered.append(record)
        return filtered

    # ------------------------------------------------------------------
    # okmem 高级方法（暴露为工具）
    # ------------------------------------------------------------------

    async def recall_pipeline(
        self,
        user_input: str,
        *,
        scene: str = "mix",
        budget_chars: int = 4000,
    ) -> dict[str, Any]:
        return await self._enqueue(
            PRIORITY_WRITE,
            self._call_okmem,
            "recall_pipeline",
            user_input,
            scene=scene,
            budget_chars=budget_chars,
            # 主动回忆是读操作。okmem 默认会把 user_input 原样回写成一条
            # protected 的 session 记忆，工具每被调用一次就污染一次长期库；
            # 跨会话持久化统一走 end_session 的 save_turn 通道，避免双写。
            include_write_back=False,
        )

    async def proactive_review(self, *, limit: int = 30) -> dict[str, Any]:
        return await self._enqueue(
            PRIORITY_INDEX, self._call_okmem, "proactive_review", limit=limit
        )

    async def health(self) -> dict[str, Any]:
        return await self._enqueue(PRIORITY_INDEX, self._call_okmem, "health")

    async def pool_stats(self) -> dict[str, Any]:
        return await self._enqueue(PRIORITY_INDEX, self._call_okmem, "pool_stats")

    async def progress(self, *, session_id: str = "") -> dict[str, Any]:
        return await self._enqueue(PRIORITY_INDEX, self._progress_sync, session_id)

    def _progress_sync(self, session_id: str) -> dict[str, Any]:
        ms = self._ensure_okmem()
        if ms is None:
            return {}
        with self._lock:
            if session_id:
                ms.session_id = session_id
                ms.progress.session_id = session_id
            return {
                "snapshot": ms.progress_get(),
                "inject": ms.progress_inject(1200),
            }

    async def recall_cards(self, *, limit: int = 10) -> list[dict[str, Any]]:
        return await self._enqueue(PRIORITY_INDEX, self._call_okmem, "cards", limit=limit)

    async def record_emotion(
        self,
        label: str = "",
        *,
        text: str = "",
        intensity: float = 0.5,
        trigger_event: str = "",
        need_type: str = "",
        boundary: str = "",
    ) -> dict[str, Any]:
        if not label and text:
            signal = detect_emotion_signal(text)
            label = signal["emotion"]
            intensity = signal["intensity"]
        return await self._enqueue(
            PRIORITY_WRITE,
            self._record_emotion_sync,
            label or "neutral",
            intensity,
            trigger_event or text,
            need_type,
            boundary,
        )

    def _record_emotion_sync(
        self,
        label: str,
        intensity: float,
        trigger_event: str,
        need_type: str,
        boundary: str,
    ) -> dict[str, Any]:
        ms = self._ensure_okmem()
        if ms is None:
            return {}
        with self._lock:
            emotion_id = ms.record_emotion(
                label,
                intensity=intensity,
                trigger_event=trigger_event,
                need_type=need_type,
                boundary=boundary,
                session_id=self.session_id,
            )
            return {"emotion_id": emotion_id, "state": ms.emotion_state()}

    async def emotion_state(self) -> dict[str, Any] | None:
        return await self._enqueue(PRIORITY_READ, self._emotion_state_sync)

    def detect_emotion(self, text: str) -> dict[str, Any]:
        """多信号情绪识别（规则 + 语气/标点），低置信度返回 neutral。"""
        return detect_emotion_signal(text)

    async def maintain_sessions(
        self, *, ttl_days: float = 7.0, apply: bool = False
    ) -> dict[str, Any]:
        """Session 记忆 TTL 归档：默认只演练，apply=True 可逆归档。"""
        return await self._enqueue(
            PRIORITY_MAINTENANCE, self._maintain_sessions_sync, ttl_days, apply
        )

    def _maintain_sessions_sync(self, ttl_days: float, apply: bool) -> dict[str, Any]:
        ms = self._ensure_okmem()
        if ms is None:
            return {"ok": False, "reason": self._okmem_error or "okmem unavailable"}
        now = datetime.now()
        expired: list[int] = []
        with self._lock:
            rows = ms.store.active_memories(fmts=["session"])
            for row in rows:
                raw = row.get("observed_at") or row.get("created_at")
                if not raw:
                    continue
                try:
                    ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00").replace(" ", "T"))
                except ValueError:
                    continue
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
                if (now - ts).total_seconds() > ttl_days * 86400:
                    expired.append(int(row["id"]))
            if apply:
                for mid in expired:
                    ms.store.update_memory(mid, state="archived")
        return {
            "ok": True,
            "apply": apply,
            "ttl_days": ttl_days,
            "scanned": len(rows),
            "expired": len(expired),
            "archived": len(expired) if apply else 0,
        }

    def _emotion_state_sync(self) -> dict[str, Any] | None:
        ms = self._ensure_okmem()
        if ms is None:
            return None
        with self._lock:
            return ms.emotion_state()

    async def save_turn(
        self,
        user_message: str = "",
        assistant_answer: str | None = None,
        *,
        session_id: str = "",
        signals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._enqueue(
            PRIORITY_WRITE,
            self._save_turn_sync,
            user_message,
            assistant_answer,
            session_id,
            signals,
        )

    def _save_turn_sync(
        self,
        user_message: str,
        assistant_answer: str | None,
        session_id: str,
        signals: dict[str, Any] | None,
    ) -> dict[str, Any]:
        ms = self._ensure_okmem()
        if ms is None:
            return {}
        with self._lock:
            return ms.save_turn(
                user_message=user_message,
                assistant_answer=assistant_answer,
                session_id=session_id or self.session_id,
                signals=signals,
                source="openkitsune",
            )

    async def knowledge_search(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        return await self._enqueue(PRIORITY_READ, self._knowledge_search, query, limit)

    async def backfill_knowledge(
        self,
        *,
        limit: int = 200,
        dry_run: bool = True,
        source: str = "memories",
        since_ts: str = "",
        last_rowid: int = 0,
    ) -> dict[str, Any]:
        """分源增量回填：memories / fts，带水位线且幂等。"""
        return await self._enqueue(
            PRIORITY_MAINTENANCE,
            self._backfill_sync,
            limit,
            dry_run,
            source,
            since_ts,
            last_rowid,
        )

    def _backfill_sync(
        self,
        limit: int,
        dry_run: bool,
        source: str,
        since_ts: str,
        last_rowid: int,
    ) -> dict[str, Any]:
        ms = self._ensure_okmem()
        if ms is None:
            return {"ok": False, "reason": self._okmem_error or "okmem unavailable"}
        limit = max(1, int(limit))

        rows: list[Any] = []
        watermark = ""
        try:
            if source == "memories":
                if not self.knowledge_db.exists():
                    return {"ok": False, "reason": "knowledge db not found"}
                conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    sql = (
                        "SELECT id, key, content, category, kind, importance, updated_at "
                        "FROM memories WHERE superseded_by IS NULL"
                    )
                    params: list[Any] = []
                    if since_ts:
                        sql += " AND updated_at > ?"
                        params.append(since_ts)
                    sql += " ORDER BY updated_at ASC, id ASC LIMIT ?"
                    params.append(limit)
                    rows = conn.execute(sql, params).fetchall()
                finally:
                    conn.close()
            elif source == "fts":
                if not self.knowledge_db.exists():
                    return {"ok": False, "reason": "knowledge db not found"}
                conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute(
                        "SELECT f.rowid, f.key, f.content, f.category, f.kind, "
                        "f.importance FROM memories_fts f "
                        "WHERE f.rowid > ? ORDER BY f.rowid ASC LIMIT ?",
                        (int(last_rowid), limit),
                    ).fetchall()
                finally:
                    conn.close()
            else:
                return {"ok": False, "reason": f"unknown source: {source}"}
        except sqlite3.Error as exc:
            return {"ok": False, "reason": str(exc)}

        with self._lock:
            existing = {str(row.get("content_hash") or "") for row in ms.store.active_memories()}

        imported = 0
        skipped = 0
        for row in rows:
            content = str(row["content"] or "")
            fmt = "semantic"
            tags = normalize_tags([row["category"], row["kind"]])
            summary = str(row["key"] or "")
            source_name = "okmem-kb:fts" if source == "fts" else "okmem-kb"
            importance = float(row["importance"] or 0.5)
            if source == "fts":
                watermark = str(row["rowid"])
            else:
                watermark = str(row["updated_at"] or watermark)

            if not content.strip():
                skipped += 1
                continue
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest in existing:
                skipped += 1
                continue
            if not dry_run:
                with self._lock:
                    ms.write(
                        content,
                        fmt=fmt,
                        source=source_name,
                        tags=tags,
                        summary=summary,
                        confidence=importance,
                        salience=importance,
                        session_id=self.session_id,
                        extract=False,
                        mount=False,
                    )
                existing.add(digest)
            imported += 1

        if not dry_run and imported:
            with self._lock, contextlib.suppress(Exception):
                ms.mount_segments()

        result: dict[str, Any] = {
            "ok": True,
            "source": source,
            "dry_run": dry_run,
            "scanned": len(rows),
            "imported": imported,
            "skipped": skipped,
            "watermark": watermark,
        }
        if source == "fts":
            result["next_rowid"] = int(watermark or last_rowid)
        else:
            result["next_since_ts"] = watermark
        return result

    def _cached_content(self, key: str, loader: Any) -> str | None:
        now = time.time()
        cached = self._content_cache.get(key)
        if cached and now - cached[0] <= self._content_cache_ttl:
            self._content_cache_hits += 1
            return cached[1]
        self._content_cache_misses += 1
        content = loader()
        if content is not None:
            self._content_cache[key] = (now, content)
            if len(self._content_cache) > self._content_cache_max:
                oldest = next(iter(self._content_cache))
                self._content_cache.pop(oldest, None)
        return content

    def cache_stats(self) -> dict[str, Any]:
        total = self._content_cache_hits + self._content_cache_misses
        return {
            "size": len(self._content_cache),
            "hits": self._content_cache_hits,
            "misses": self._content_cache_misses,
            "hit_rate": round(self._content_cache_hits / total, 3) if total else 0.0,
            "ttl_s": self._content_cache_ttl,
        }

    def _call_okmem(self, method: str, *args: Any, **kwargs: Any) -> Any:
        ms = self._ensure_okmem()
        if ms is None:
            return {}
        fn = getattr(ms, method, None)
        if not callable(fn):
            return {}
        with self._lock:
            return fn(*args, **kwargs)

    # ------------------------------------------------------------------
    # 数据源实现
    # ------------------------------------------------------------------

    def _okmem_record(self, hit: dict[str, Any], *, page_size: int | None = None) -> MemoryRecord:
        fmt = str(hit.get("fmt") or "semantic")
        observed_at = str(hit.get("observed_at") or "")
        content = str(hit.get("content") or "")
        record = MemoryRecord(
            id=f"okmem:{hit.get('id')}",
            content=content,
            type=_TYPE_BY_OKMEM_FMT.get(fmt, "fact"),
            importance=float(hit.get("salience") or hit.get("score") or 0.5),
            tags=normalize_tags(hit.get("tags")),
            source=str(hit.get("source") or "okmem"),
            created_at=observed_at,
            updated_at=observed_at,
            content_total=len(content),
            next_offset=len(content),
            score=float(hit.get("score") or 0.0),
            provider=self.name,
            metadata={
                "backend": "okmem",
                "fmt": fmt,
                "confidence": hit.get("confidence"),
                "hits": hit.get("hits"),
                "session_id": hit.get("session_id"),
            },
        )
        if page_size and len(content) > page_size:
            self._apply_page(record, content, page_size)
        return record

    def _apply_page(
        self, record: MemoryRecord, full_content: str, page_size: int, offset: int = 0
    ) -> MemoryRecord:
        """把全文的一页写入 record，并补齐 page_token / snapshot_version。"""
        total = len(full_content)
        if offset == 0 and total <= page_size:
            record.content_total = total
            record.next_offset = total
            record.has_more = False
            record.snapshot_version = content_hash(full_content)[:12]
            return record
        chunk = _page_text(full_content, offset, page_size)
        full_hash = content_hash(full_content)
        snapshot = full_hash[:12]
        next_offset = offset + len(chunk)

        def token(at: int) -> str:
            return build_page_token(
                memory_id=record.id,
                provider=self.name,
                offset=at,
                limit=page_size,
                content_hash_value=full_hash,
                snapshot_version=snapshot,
            )

        record.apply_content_page(
            chunk,
            offset=offset,
            total=total,
            snapshot_version=snapshot,
            page_soft_limit=len(chunk) > page_size,
            page_token=token(offset),
            next_page_token=token(next_offset) if next_offset < total else "",
        )
        return record

    def _knowledge_search(self, query: str, limit: int) -> list[MemoryRecord]:
        if not self.knowledge_db.exists():
            return []
        base_terms = _query_terms(query)
        recall_terms = _expand_terms(base_terms, 12)
        terms = base_terms
        # LIKE 候选必须放大：先按更新时间截断会把「中成药」这类高频词的
        # 真正高匹配文档挤出候选集，导致排序失真。
        candidate_limit = min(2000, max(200, limit * 50))
        if not recall_terms:
            sql = (
                "SELECT id, key, content, category, kind, importance, "
                "created_at, updated_at, pinned FROM memories "
                "WHERE superseded_by IS NULL ORDER BY pinned DESC, updated_at DESC LIMIT ?"
            )
            params: list[Any] = [limit]
        else:
            clause = " OR ".join(["key LIKE ? OR content LIKE ?"] * len(recall_terms))
            sql = (
                "SELECT id, key, content, category, kind, importance, "
                "created_at, updated_at, pinned FROM memories "
                f"WHERE superseded_by IS NULL AND ({clause}) "
                "ORDER BY pinned DESC, importance DESC, updated_at DESC LIMIT ?"
            )
            params = []
            for term in recall_terms:
                like = f"%{term}%"
                params.extend([like, like])
            params.append(candidate_limit)

        try:
            conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("[Okmem] knowledge search failed: %s", exc)
            return []

        records: list[MemoryRecord] = []
        for row in rows:
            content = str(row["content"] or "")
            haystack = f"{row['key'] or ''}\n{content}".lower()
            matched = sum(1 for term in terms if term.lower() in haystack)
            importance = float(row["importance"] or 0.5)
            if terms:
                ratio = matched / len(terms)
                score = 0.2 + 0.6 * ratio + 0.1 * importance
                if str(row["key"] or "").lower() in (query or "").lower():
                    score = min(0.99, score + 0.1)
                if (query or "").strip().lower() in haystack:
                    score = min(0.99, score + 0.15)
            else:
                score = 0.0
            record = MemoryRecord(
                id=f"okmem-kb:{row['id']}",
                content=content,
                type="fact",
                importance=importance,
                tags=normalize_tags([row["category"], row["kind"]]),
                source="okmem-kb",
                created_at=str(row["created_at"] or ""),
                updated_at=str(row["updated_at"] or ""),
                content_total=len(content),
                next_offset=len(content),
                score=score,
                provider=self.name,
                metadata={
                    "backend": "okmem-kb",
                    "key": row["key"],
                    "category": row["category"],
                    "kind": row["kind"],
                    "pinned": bool(row["pinned"]),
                    "content_length": len(content),
                },
            )
            if len(content) > self.search_page_size:
                self._apply_page(record, content, self.search_page_size)
            records.append(record)
        return self._rank(records, limit * 2)

    def _knowledge_entity_search(self, query: str, limit: int) -> list[MemoryRecord]:
        """实体倒排召回：先命中实体名，再找提及该实体的记忆。"""
        if not query or not self.knowledge_db.exists():
            return []
        terms = _expand_terms(_query_terms(query, 6), 8)
        if not terms:
            return []
        try:
            conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                name_clause = " OR ".join(["name LIKE ?"] * len(terms))
                names = [
                    str(row["name"])
                    for row in conn.execute(
                        f"SELECT name FROM entities WHERE ({name_clause}) "
                        "ORDER BY importance DESC LIMIT 10",
                        [f"%{term}%" for term in terms],
                    ).fetchall()
                    if len(str(row["name"] or "")) >= 2
                ]
                if not names:
                    return []
                mention_clause = " OR ".join(["key LIKE ? OR content LIKE ?"] * len(names))
                params: list[Any] = []
                for name in names:
                    params.extend([f"%{name}%", f"%{name}%"])
                params.append(limit * 2)
                rows = conn.execute(
                    "SELECT id, key, content, category, kind, importance, "
                    "created_at, updated_at FROM memories "
                    f"WHERE superseded_by IS NULL AND ({mention_clause}) "
                    "ORDER BY importance DESC, updated_at DESC LIMIT ?",
                    params,
                ).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.debug("[Okmem] entity search failed: %s", exc)
            return []

        records: list[MemoryRecord] = []
        for row in rows:
            content = str(row["content"] or "")
            mentioned = [name for name in names if name in content or name in str(row["key"] or "")]
            importance = float(row["importance"] or 0.5)
            score = 0.3 + 0.05 * len(mentioned) + 0.1 * importance
            record = MemoryRecord(
                id=f"okmem-kb:{row['id']}",
                content=content,
                type="fact",
                importance=importance,
                tags=normalize_tags([row["category"], row["kind"]] + mentioned[:3]),
                source="okmem-kb:entity",
                created_at=str(row["created_at"] or ""),
                updated_at=str(row["updated_at"] or ""),
                content_total=len(content),
                next_offset=len(content),
                score=score,
                provider=self.name,
                metadata={
                    "backend": "okmem-kb-entity",
                    "key": row["key"],
                    "category": row["category"],
                    "kind": row["kind"],
                    "entities": mentioned[:5],
                },
            )
            if len(content) > self.search_page_size:
                self._apply_page(record, content, self.search_page_size)
            records.append(record)
        return self._rank(records, limit)

    def _knowledge_fts_search(self, query: str, limit: int) -> list[MemoryRecord]:
        """补充检索 memories_fts：部分图谱节点/索引只存在于 FTS 表。"""
        terms = _query_terms(query)
        if not terms or not self.knowledge_db.exists():
            return []
        clause = " OR ".join(["f.key LIKE ? OR f.content LIKE ?"] * len(terms))
        sql = (
            "SELECT f.rowid, f.key, f.content, f.category, f.kind, f.importance, "
            "m.created_at, m.updated_at "
            "FROM memories_fts f LEFT JOIN memories m ON m.key = f.key "
            f"WHERE ({clause}) LIMIT ?"
        )
        params: list[Any] = []
        for term in terms:
            like = f"%{term}%"
            params.extend([like, like])
        params.append(min(300, max(40, limit * 10)))

        try:
            conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(sql, params).fetchall()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.debug("[Okmem] knowledge FTS search failed: %s", exc)
            return []

        records: list[MemoryRecord] = []
        phrase = (query or "").strip().lower()
        for row in rows:
            content = str(row["content"] or "")
            haystack = f"{row['key'] or ''}\n{content}".lower()
            matched = sum(1 for term in terms if term.lower() in haystack)
            ratio = matched / len(terms)
            importance = float(row["importance"] or 0.5)
            score = 0.2 + 0.6 * ratio + 0.1 * importance
            if phrase and phrase in haystack:
                score = min(0.99, score + 0.12)
            record = MemoryRecord(
                id=f"okmem-kb-fts:{row['rowid']}",
                content=content,
                type="fact",
                importance=importance,
                tags=normalize_tags([row["category"], row["kind"]]),
                source="okmem-kb:fts",
                created_at=str(row["created_at"] or ""),
                updated_at=str(row["updated_at"] or ""),
                content_total=len(content),
                next_offset=len(content),
                score=score,
                provider=self.name,
                metadata={
                    "backend": "okmem-kb-fts",
                    "key": row["key"],
                    "category": row["category"],
                    "kind": row["kind"],
                    "content_length": len(content),
                    "ts_missing": not bool(row["created_at"] or row["updated_at"]),
                },
            )
            if len(content) > self.search_page_size:
                self._apply_page(record, content, self.search_page_size)
            records.append(record)
        return self._rank(records, limit)

    def _knowledge_fts_get(self, memory_id: str) -> MemoryRecord | None:
        if not memory_id.isdigit() or not self.knowledge_db.exists():
            return None
        try:
            conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT f.rowid, f.key, f.content, f.category, f.kind, f.importance, "
                    "m.created_at, m.updated_at "
                    "FROM memories_fts f LEFT JOIN memories m ON m.key = f.key "
                    "WHERE f.rowid=?",
                    (int(memory_id),),
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("[Okmem] knowledge FTS get failed: %s", exc)
            return None
        if row is None:
            return None
        content = str(row["content"] or "")
        record = MemoryRecord(
            id=f"okmem-kb-fts:{row['rowid']}",
            content=content,
            type="fact",
            importance=float(row["importance"] or 0.5),
            tags=normalize_tags([row["category"], row["kind"]]),
            source="okmem-kb:fts",
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
            content_total=len(content),
            next_offset=len(content),
            provider=self.name,
            metadata={
                "backend": "okmem-kb-fts",
                "key": row["key"],
                "category": row["category"],
                "kind": row["kind"],
                "content_length": len(content),
                "ts_missing": not bool(row["created_at"] or row["updated_at"]),
            },
        )
        if len(content) > self.content_page_size:
            self._apply_page(record, content, self.content_page_size)
        return record

    def _knowledge_get(self, memory_id: str) -> MemoryRecord | None:
        if not self.knowledge_db.exists():
            return None
        try:
            conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT id, key, content, category, kind, importance, "
                    "created_at, updated_at, pinned FROM memories WHERE id=?",
                    (memory_id,),
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("[Okmem] knowledge get failed: %s", exc)
            return None
        if row is None:
            return None
        content = str(row["content"] or "")
        record = MemoryRecord(
            id=f"okmem-kb:{row['id']}",
            content=content,
            type="fact",
            importance=float(row["importance"] or 0.5),
            tags=normalize_tags([row["category"], row["kind"]]),
            source="okmem-kb",
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
            content_total=len(content),
            next_offset=len(content),
            provider=self.name,
            metadata={
                "backend": "okmem-kb",
                "key": row["key"],
                "category": row["category"],
                "kind": row["kind"],
                "pinned": bool(row["pinned"]),
                "content_length": len(content),
            },
        )
        if len(content) > self.content_page_size:
            self._apply_page(record, content, self.content_page_size)
        return record

    async def read_content(
        self, memory_id: str, *, offset: int = 0, limit: int | None = None
    ) -> dict[str, Any]:
        """按 ID 分页读取全文；页面可无损拼接，不做隐式截断。"""
        return await self._enqueue(PRIORITY_READ, self._read_content_sync, memory_id, offset, limit)

    def _read_content_sync(self, memory_id: str, offset: int, limit: int | None) -> dict[str, Any]:
        memory_id = self._strip_provider_prefix(str(memory_id))
        limit = max(1, int(limit or self.content_page_size))
        if memory_id.startswith("pending:"):
            record = self._pending_record(memory_id.split(":", 1)[1])
            if record is None:
                return {
                    "ok": False,
                    "memory_id": memory_id,
                    "content": "",
                    "offset": 0,
                    "total": 0,
                    "has_more": False,
                    "next_offset": 0,
                }
            return _page_payload(
                memory_id, record.content, provider=self.name, offset=offset, limit=limit
            )
        source, _, raw_id = str(memory_id).partition(":")
        full: str | None = None

        if source in ("", "okmem"):
            mid = raw_id or str(memory_id)
            ms = self._ensure_okmem()
            if ms is not None and mid.isdigit():
                with self._lock:
                    row = ms.store.get_memory(int(mid))
                if row and row.get("state") == "active":
                    full = str(row.get("content") or "")
        elif source in ("okmem-kb", "knowledge"):
            full = self._knowledge_content(raw_id)
        elif source in ("okmem-kb-fts", "knowledge-fts"):
            full = self._knowledge_fts_content(raw_id)

        if full is None:
            return {
                "ok": False,
                "memory_id": memory_id,
                "content": "",
                "offset": 0,
                "total": 0,
                "has_more": False,
                "next_offset": 0,
            }
        return _page_payload(memory_id, full, provider=self.name, offset=offset, limit=limit)

    def _knowledge_content(self, memory_id: str) -> str | None:
        return self._cached_content(
            f"okmem-kb:{memory_id}", lambda: self._load_knowledge_content(memory_id)
        )

    def _load_knowledge_content(self, memory_id: str) -> str | None:
        if not self.knowledge_db.exists():
            return None
        try:
            conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
            try:
                row = conn.execute(
                    "SELECT content FROM memories WHERE id=?", (memory_id,)
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("[Okmem] knowledge content read failed: %s", exc)
            return None
        return str(row[0] or "") if row else None

    def _knowledge_fts_content(self, memory_id: str) -> str | None:
        return self._cached_content(
            f"okmem-kb-fts:{memory_id}",
            lambda: self._load_knowledge_fts_content(memory_id),
        )

    def _load_knowledge_fts_content(self, memory_id: str) -> str | None:
        if not memory_id.isdigit() or not self.knowledge_db.exists():
            return None
        try:
            conn = sqlite3.connect(_readonly_uri(self.knowledge_db), uri=True, timeout=5)
            try:
                row = conn.execute(
                    "SELECT content FROM memories_fts WHERE rowid=?", (int(memory_id),)
                ).fetchone()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            logger.warning("[Okmem] knowledge FTS content read failed: %s", exc)
            return None
        return str(row[0] or "") if row else None

    @staticmethod
    def _rank(records: list[MemoryRecord], limit: int) -> list[MemoryRecord]:
        records.sort(key=lambda record: (record.score, record.importance), reverse=True)
        return records[:limit]

    def _fuse_sources(
        self,
        sources: dict[str, list[MemoryRecord]],
        limit: int,
        *,
        query: str,
    ) -> list[MemoryRecord]:
        """跨源 RRF 融合 + 词法重叠 + 短语命中 + 时间衰减。"""
        if not query:
            ordered: list[MemoryRecord] = []
            for name in (
                "pending",
                "okmem",
                "okmem-kb",
                "okmem-kb-fts",
                "okmem-kb-entity",
            ):
                ordered.extend(sources.get(name, []))
            return self._merge(ordered, limit)

        phrase = query.strip().lower()
        terms = _query_terms(query)
        aggregated: dict[str, dict[str, Any]] = {}
        for source, records in sources.items():
            if not records:
                continue
            weight = _SOURCE_WEIGHTS.get(source, 0.8)
            ordered = sorted(
                records,
                key=lambda record: (float(record.score or 0.0), record.importance),
                reverse=True,
            )
            for rank, record in enumerate(ordered, 1):
                key = record.id or content_hash(record.content)[:16]
                entry = aggregated.setdefault(
                    key,
                    {
                        "record": record,
                        "rrf": 0.0,
                        "raw": float(record.score or 0.0),
                        "sources": set(),
                    },
                )
                entry["rrf"] += weight / (60.0 + rank)
                entry["raw"] = max(entry["raw"], float(record.score or 0.0))
                entry["sources"].add(source)

        scored: list[tuple[float, MemoryRecord]] = []
        for entry in aggregated.values():
            record: MemoryRecord = entry["record"]
            raw = float(entry["raw"])
            haystack = f"{record.content} {record.metadata.get('key') or ''}".lower()
            overlap = (
                sum(1 for term in terms if term.lower() in haystack) / len(terms) if terms else 0.0
            )
            # 无词法交集且语义置信不足：丢弃伪相关的向量噪声
            if overlap == 0.0 and raw < 0.8:
                continue
            bonus = 0.0
            if phrase and phrase in record.content.lower():
                bonus += 0.08
            key_text = str(record.metadata.get("key") or "").lower()
            if phrase and key_text and phrase in key_text:
                bonus += 0.1
            fused = (
                5.0 * float(entry["rrf"])
                + 0.25 * overlap
                + 0.05 * min(1.0, record.importance)
                + bonus
            )
            fused *= self._time_decay(record)
            record.metadata["raw_score"] = round(raw, 4)
            record.metadata["lexical_overlap"] = round(overlap, 3)
            record.metadata["rrf_sources"] = sorted(entry["sources"])
            record.score = round(fused, 4)
            record.metadata["okmem_score"] = record.score
            scored.append((fused, record))

        scored.sort(key=lambda item: item[0], reverse=True)
        return self._merge([record for _, record in scored], limit)

    @staticmethod
    def _time_decay(record: MemoryRecord) -> float:
        """轻量时间衰减：新记忆 1.0，一年前约 0.94，无时间戳不衰减。"""
        raw = record.created_at or record.updated_at
        if not raw:
            return 1.0
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00").replace(" ", "T"))
        except ValueError:
            return 1.0
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
        return 0.9 + 0.1 * math.exp(-age_days / 365.0)

    @staticmethod
    def _merge(records: list[MemoryRecord], limit: int) -> list[MemoryRecord]:
        """按 id / 内容去重，保留先出现的来源顺序（okmem → 知识库 → 案例库）。"""
        merged: list[MemoryRecord] = []
        seen_ids: set[str] = set()
        seen_content: set[str] = set()
        for record in records:
            if not record.content:
                continue
            content_key = record.content.strip().lower()
            if record.id and record.id in seen_ids:
                continue
            if content_key in seen_content:
                continue
            if record.id:
                seen_ids.add(record.id)
            seen_content.add(content_key)
            merged.append(record)
            if len(merged) >= limit:
                break
        return merged


class OkmemRetrievalSource:
    """把 :class:`OkmemProvider` 适配为 RetrievalEngine 的外部检索源。

    ``MemoryManager.retrieval_engine._external_sources`` 只要求
    ``source_name`` + ``async retrieve(query, limit)``，本适配器把 Provider 的
    ``MemoryRecord`` 转换为候选字典，并保留来源、分数与元数据。
    """

    source_name = "okmem"

    def __init__(self, provider: OkmemProvider | None = None) -> None:
        self.provider = provider or create_okmem_provider()

    async def retrieve(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        records = await self.provider.search(query, limit=limit)
        return [
            {
                "id": record.id,
                "content": record.content,
                "relevance": float(record.score or 0.0),
                "metadata": dict(record.metadata or {}),
            }
            for record in records
            if record.content
        ]

    def close(self) -> None:
        self.provider.close()


def _record_label(record: MemoryRecord) -> str:
    if record.id.startswith("okmem-kb:") or record.id.startswith("okmem-kb-fts:"):
        return "知识"
    return "记忆"


# ---------------------------------------------------------------------------
# 工具描述与分发
# ---------------------------------------------------------------------------

OKMEM_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "okmem_recall",
        "category": "Memory",
        "description": (
            "Run the okmem six-pool active recall pipeline and return "
            "prompt-ready memory context for the current user input."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_input": {"type": "string", "description": "当前用户输入"},
                "scene": {
                    "type": "string",
                    "enum": ["mix", "task", "emotion"],
                    "default": "mix",
                },
                "budget_chars": {"type": "integer", "default": 4000},
            },
            "required": ["user_input"],
        },
    },
    {
        "name": "okmem_knowledge_search",
        "category": "Memory",
        "description": "Search the okmem knowledge base (TCM / xuan-yi notes).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "okmem_save_turn",
        "category": "Memory",
        "description": "Persist one conversation turn (user / assistant) into okmem.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_message": {"type": "string"},
                "assistant_answer": {"type": "string"},
            },
            "required": ["user_message"],
        },
    },
    {
        "name": "okmem_proactive_review",
        "category": "Memory",
        "description": "Get the proactive review queue: conflicts, weak memories, open hypotheses, tasks.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "default": 30}},
        },
    },
    {
        "name": "okmem_health",
        "category": "Memory",
        "description": "Get the okmem memory health report.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "okmem_progress",
        "category": "Memory",
        "description": "Get the L1 progress snapshot (goal / tasks / decisions / next action).",
        "input_schema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
        },
    },
    {
        "name": "okmem_backfill",
        "category": "Memory",
        "description": (
            "Backfill okmem knowledge base notes into okmem. "
            "Dry-run by default; set dry_run=false to actually import."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 200},
                "dry_run": {"type": "boolean", "default": True},
                "source": {
                    "type": "string",
                    "enum": ["memories", "fts"],
                    "default": "memories",
                },
                "since_ts": {"type": "string", "default": ""},
                "last_rowid": {"type": "integer", "default": 0},
            },
        },
    },
    {
        "name": "okmem_record_emotion",
        "category": "Memory",
        "description": "Record the current emotional state into the emotion memory pool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "情绪标签，如 疲惫/焦虑/平静"},
                "intensity": {"type": "number", "default": 0.5},
                "trigger_event": {"type": "string"},
                "need_type": {"type": "string"},
                "boundary": {"type": "string"},
            },
            "required": ["label"],
        },
    },
    {
        "name": "okmem_emotion_state",
        "category": "Memory",
        "description": "Get the latest emotional state for the current session.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "okmem_detect_emotion",
        "category": "Memory",
        "description": "Detect emotion from free text using multi-signal rules.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "okmem_maintain_sessions",
        "category": "Memory",
        "description": (
            "Archive expired session memories by TTL. Dry-run by default; "
            "set apply=true for reversible archiving."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ttl_days": {"type": "number", "default": 7},
                "apply": {"type": "boolean", "default": False},
            },
        },
    },
]

OKMEM_TOOL_NAMES: tuple[str, ...] = tuple(schema["name"] for schema in OKMEM_TOOL_SCHEMAS)


async def dispatch_okmem_tool(
    provider: OkmemProvider,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把 okmem 的方法调用分发为 JSON 结果。"""
    name = str(tool_name or "").strip()
    args = dict(arguments or {})

    if name == "okmem_recall":
        result = await provider.recall_pipeline(
            str(args.get("user_input", "") or ""),
            scene=str(args.get("scene", "mix") or "mix"),
            budget_chars=int(args.get("budget_chars", 4000) or 4000),
        )
        return {"ok": True, "result": result}

    if name == "okmem_knowledge_search":
        records = await provider.knowledge_search(
            str(args.get("query", "") or ""),
            limit=int(args.get("limit", 10) or 10),
        )
        return {
            "ok": True,
            "count": len(records),
            "items": [record.to_dict() for record in records],
        }

    if name == "okmem_save_turn":
        result = await provider.save_turn(
            user_message=str(args.get("user_message", "") or ""),
            assistant_answer=args.get("assistant_answer"),
        )
        return {"ok": bool(result), "result": result}

    if name == "okmem_proactive_review":
        return {
            "ok": True,
            "result": await provider.proactive_review(limit=int(args.get("limit", 30) or 30)),
        }

    if name == "okmem_health":
        return {"ok": True, "result": await provider.health()}

    if name == "okmem_progress":
        return {
            "ok": True,
            "result": await provider.progress(session_id=str(args.get("session_id", "") or "")),
        }

    if name == "okmem_backfill":
        result = await provider.backfill_knowledge(
            limit=int(args.get("limit", 200) or 200),
            dry_run=bool(args.get("dry_run", True)),
            source=str(args.get("source", "memories") or "memories"),
            since_ts=str(args.get("since_ts", "") or ""),
            last_rowid=int(args.get("last_rowid", 0) or 0),
        )
        return {"ok": bool(result.get("ok")), "result": result}

    if name == "okmem_record_emotion":
        result = await provider.record_emotion(
            str(args.get("label", "") or "unknown"),
            intensity=float(args.get("intensity", 0.5) or 0.5),
            trigger_event=str(args.get("trigger_event", "") or ""),
            need_type=str(args.get("need_type", "") or ""),
            boundary=str(args.get("boundary", "") or ""),
        )
        return {"ok": bool(result), "result": result}

    if name == "okmem_emotion_state":
        return {"ok": True, "result": await provider.emotion_state()}

    if name == "okmem_detect_emotion":
        return {
            "ok": True,
            "result": provider.detect_emotion(str(args.get("text", "") or "")),
        }

    if name == "okmem_maintain_sessions":
        result = await provider.maintain_sessions(
            ttl_days=float(args.get("ttl_days", 7) or 7),
            apply=bool(args.get("apply", False)),
        )
        return {"ok": bool(result.get("ok")), "result": result}

    raise ValueError(f"Unknown okmem tool: {name!r}")


def create_okmem_provider(**kwargs: Any) -> OkmemProvider:
    """创建 okmem Provider（参数透传构造器）。"""
    return OkmemProvider(**kwargs)
