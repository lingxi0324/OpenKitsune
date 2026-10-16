"""Compression lineage — 压缩链式追踪 + 冷却期持久化 + 压缩锁 + 事务性压缩。

对标 Hermes SessionCompressionMixin 的完整能力集，适配 OpenKitsune 的
ContextManager + CompactionGuard 架构。

核心能力：
1. Lineage 链式追踪：parent_session_id → child_session_id 链，支持查找/恢复
2. 压缩锁：防止并发压缩导致 lineage 分裂（原子获取/释放/续期）
3. 冷却期持久化：压缩失败后冷却窗口可跨重启保留
4. 事务性压缩：validate 成功后才提交 lineage（补偿机制）
5. Watermark 机制：处理压缩期间新消息的归属问题
6. Turn Lease：跨进程压缩权限控制
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from openkitsune.runtime.context.continuity import content_digest

logger = logging.getLogger(__name__)


# ======================================================================
# 数据模型
# ======================================================================

@dataclass
class CompressionLineage:
    """压缩链式追踪记录。对标 Hermes sessions.parent_session_id 链。"""
    parent_session_id: str          # 压缩前的 session/conversation id
    child_session_id: str           # 压缩后的新 id（continuation）
    parent_digest: str              # 压缩前消息指纹
    child_digest: str               # 压缩后消息指纹
    compressed_at: float            # 压缩时间戳
    end_reason: str = "compression" # 结束原因
    source: str = "auto_compression"
    parent_message_count: int = 0
    child_message_count: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    quality: str = "validated"      # validated / failed / cancelled
    _branched_from: Optional[str] = None  # 并发压缩时的分支标记
    _delegate_from: Optional[str] = None  # 委派压缩标记
    watermark: Optional[int] = None   # 压缩开始时的消息水位线
    watermark_ceiling: Optional[int] = None  # 水位线上限

    def to_dict(self) -> dict:
        return {
            "parent_session_id": self.parent_session_id,
            "child_session_id": self.child_session_id,
            "parent_digest": self.parent_digest,
            "child_digest": self.child_digest,
            "compressed_at": self.compressed_at,
            "end_reason": self.end_reason,
            "source": self.source,
            "parent_message_count": self.parent_message_count,
            "child_message_count": self.child_message_count,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "quality": self.quality,
            "_branched_from": self._branched_from,
            "_delegate_from": self._delegate_from,
            "watermark": self.watermark,
            "watermark_ceiling": self.watermark_ceiling,
        }

    @staticmethod
    def from_dict(data: dict) -> CompressionLineage:
        return CompressionLineage(
            parent_session_id=data["parent_session_id"],
            child_session_id=data["child_session_id"],
            parent_digest=data["parent_digest"],
            child_digest=data["child_digest"],
            compressed_at=data["compressed_at"],
            end_reason=data.get("end_reason", "compression"),
            source=data.get("source", "auto_compression"),
            parent_message_count=data.get("parent_message_count", 0),
            child_message_count=data.get("child_message_count", 0),
            tokens_before=data.get("tokens_before", 0),
            tokens_after=data.get("tokens_after", 0),
            quality=data.get("quality", "validated"),
            _branched_from=data.get("_branched_from"),
            _delegate_from=data.get("_delegate_from"),
            watermark=data.get("watermark"),
            watermark_ceiling=data.get("watermark_ceiling"),
        )


@dataclass
class CompressionLock:
    """压缩锁（防止并发压缩分裂 lineage）。对标 Hermes compression_locks 表。"""
    session_id: str
    holder: str                     # 压缩器标识（进程+线程）
    acquired_at: float
    expires_at: float
    session_digest: str = ""        # 加锁时的消息指纹，防篡改

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "holder": self.holder,
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "session_digest": self.session_digest,
        }

    @staticmethod
    def from_dict(data: dict) -> CompressionLock:
        return CompressionLock(**data)


@dataclass
class CompressionCooldown:
    """压缩冷却期状态。对标 Hermes compression_failure_cooldown_until。"""
    cooldown_until: float = 0.0
    error: str = ""
    streak_ineffective: int = 0   # 连续无效压缩次数
    streak_fallback: int = 0      # 连续 fallback 次数
    recovery_deadline: float = 0.0  # 恢复窗口截止
    structural_backoff_until: float = 0.0  # 结构性 no-op 退避
    last_failure_error: str = ""    # 最近一次失败详情

    @property
    def is_active(self) -> bool:
        return time.time() < self.cooldown_until

    @property
    def is_recovered(self) -> bool:
        """恢复窗口已到期，允许一次探针。"""
        return self.recovery_deadline > 0 and time.time() >= self.recovery_deadline

    def to_dict(self) -> dict:
        return {
            "cooldown_until": self.cooldown_until,
            "error": self.error,
            "streak_ineffective": self.streak_ineffective,
            "streak_fallback": self.streak_fallback,
            "recovery_deadline": self.recovery_deadline,
            "structural_backoff_until": self.structural_backoff_until,
            "last_failure_error": self.last_failure_error[:500],
        }

    @staticmethod
    def from_dict(data: dict) -> CompressionCooldown:
        return CompressionCooldown(
            cooldown_until=data.get("cooldown_until", 0.0),
            error=data.get("error", ""),
            streak_ineffective=data.get("streak_ineffective", 0),
            streak_fallback=data.get("streak_fallback", 0),
            recovery_deadline=data.get("recovery_deadline", 0.0),
            structural_backoff_until=data.get("structural_backoff_until", 0.0),
            last_failure_error=data.get("last_failure_error", ""),
        )


# ======================================================================
# 压缩管理器 — 集成 Lineage、锁、冷却期
# ======================================================================

class CompressionManager:
    """上下文压缩管理器：lineage 链式追踪 + 冷却期 + 压缩锁 + 事务性压缩。

    对标 Hermes SessionCompressionMixin 的核心能力，但适配 OpenKitsune 的
    ContextManager + CompactionGuard 架构。

    设计原则：
    1. Lineage 持久化：每次压缩成功记录父子关系（可对接 DB）
    2. 冷却期可持久化：压缩失败后冷却窗口跨重启保留
    3. 压缩锁：防止并发压缩分裂 lineage
    4. 事务性压缩：validate 成功后才提交 lineage
    """

    def __init__(
        self,
        *,
        failure_cooldown_seconds: float = 600.0,
        max_ineffective_strikes: int = 2,
        max_fallback_streak: int = 2,
        recovery_seconds: float = 3600.0,
        structural_backoff_seconds: float = 300.0,
        lock_ttl_seconds: float = 300.0,
        store: Any | None = None,
        state_key: str = "compression_manager",
    ):
        self.failure_cooldown_seconds = failure_cooldown_seconds
        self.max_ineffective_strikes = max_ineffective_strikes
        self.max_fallback_streak = max_fallback_streak
        self.recovery_seconds = recovery_seconds
        self.structural_backoff_seconds = structural_backoff_seconds
        self.lock_ttl_seconds = lock_ttl_seconds

        # 持久化存储：支持两种接口
        # 1. 原生接口：get_compression_state / set_compression_state
        # 2. 通用接口：get_meta / set_meta（UnifiedStore / memory_manager.store）
        self._store = store
        self._state_key = state_key
        self._meta_mode = False
        if store is not None:
            self._meta_mode = (
                not hasattr(store, "get_compression_state")
                or not hasattr(store, "set_compression_state")
            )

        # Lineage 记录（进程内缓存；对接 DB 后由 load() 填充）
        self._lineage: Dict[str, CompressionLineage] = {}       # child_id → record
        self._parent_children: Dict[str, List[str]] = {}        # parent_id → [child_ids]
        self._parent_chain: Dict[str, str] = {}                 # child_id → parent_id

        # 压缩锁
        self._locks: Dict[str, CompressionLock] = {}            # session_id → lock

        # 冷却期
        self._cooldown = CompressionCooldown()

        # 负载荷
        self._load()

    # ------------------------------------------------------------------
    # 持久化接口（对标 Hermes 的 _read_ctx / _write_sql）
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """从 store 加载状态。对标 Hermes 的 _read_ctx 加载 cooldown/lock/lineage。

        支持两种持久化接口：
        1. 原生：get_compression_state / set_compression_state
        2. 通用：get_meta / set_meta（UnifiedStore）
        """
        if self._store is None:
            return
        try:
            if self._meta_mode:
                raw = self._store.get_meta(self._state_key)
            else:
                raw = self._store.get_compression_state(self._state_key)
            if not isinstance(raw, dict):
                return
            state = raw
        except Exception as exc:
            logger.warning("[CompressionManager] state load failed: %s", exc)
            return

        now = time.time()

        # 冷却期
        cooldown_data = state.get("cooldown")
        if isinstance(cooldown_data, dict):
            self._cooldown = CompressionCooldown.from_dict(cooldown_data)
            # 恢复窗口：只接受未来的 deadline
            if self._cooldown.recovery_deadline > 0 and self._cooldown.recovery_deadline < now:
                self._cooldown.recovery_deadline = 0.0
            # 结构性退避
            if self._cooldown.structural_backoff_until > 0 and self._cooldown.structural_backoff_until < now:
                self._cooldown.structural_backoff_until = 0.0

        # Lineage（可选：只保留最近 N 条）
        lineage_data = state.get("lineage")
        if isinstance(lineage_data, list):
            for item in lineage_data[-100:]:  # 保留最近 100 条
                try:
                    record = CompressionLineage.from_dict(item)
                    self._lineage[record.child_session_id] = record
                    parent_id = record.parent_session_id
                    child_id = record.child_session_id
                    self._parent_chain[child_id] = parent_id
                    if parent_id not in self._parent_children:
                        self._parent_children[parent_id] = []
                    self._parent_children[parent_id].append(child_id)
                except Exception as exc:
                    logger.debug("[CompressionManager] lineage load skipped: %s", exc)

        # 锁（不加载过期锁）
        lock_data = state.get("locks")
        if isinstance(lock_data, list):
            for item in lock_data:
                try:
                    lock = CompressionLock.from_dict(item)
                    if not lock.is_expired:
                        self._locks[lock.session_id] = lock
                except Exception as exc:
                    logger.debug("[CompressionManager] lock load skipped: %s", exc)

    def _persist(self) -> None:
        """将状态写入 store。对标 Hermes 的 _write_sql 持久化。

        支持两种持久化接口：
        1. 原生：get_compression_state / set_compression_state
        2. 通用：get_meta / set_meta（UnifiedStore）
        """
        if self._store is None:
            return
        try:
            if self._meta_mode:
                self._store.set_meta(self._state_key, json.dumps({
                    "cooldown": self._cooldown.to_dict(),
                    "lineage": [r.to_dict() for r in list(self._lineage.values())[-100:]],
                    "locks": [l.to_dict() for l in self._locks.values() if not l.is_expired],
                }, ensure_ascii=False))
            else:
                self._store.set_compression_state(
                    self._state_key,
                    {
                        "cooldown": self._cooldown.to_dict(),
                        "lineage": [r.to_dict() for r in list(self._lineage.values())[-100:]],
                        "locks": [l.to_dict() for l in self._locks.values() if not l.is_expired],
                    },
                )
        except Exception as exc:
            logger.warning("[CompressionManager] persist failed: %s", exc)

    # ------------------------------------------------------------------
    # Lineage 链式追踪（对标 Hermes parent_session_id 链）
    # ------------------------------------------------------------------

    def record_compression_success(
        self,
        parent_session_id: str,
        child_session_id: str,
        parent_messages: List[dict],
        child_messages: List[dict],
        tokens_before: int,
        tokens_after: int,
        watermark: Optional[int] = None,
        watermark_ceiling: Optional[int] = None,
    ) -> CompressionLineage:
        """记录一次成功的压缩。生成 lineage 记录并持久化。对标 Hermes publish_compression_child。"""
        parent_digest = content_digest(parent_messages)
        child_digest = content_digest(child_messages)

        record = CompressionLineage(
            parent_session_id=parent_session_id,
            child_session_id=child_session_id,
            parent_digest=parent_digest,
            child_digest=child_digest,
            compressed_at=time.time(),
            parent_message_count=len(parent_messages),
            child_message_count=len(child_messages),
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            quality="validated",
            watermark=watermark,
            watermark_ceiling=watermark_ceiling,
        )

        self._lineage[child_session_id] = record
        if parent_session_id not in self._parent_children:
            self._parent_children[parent_session_id] = []
        self._parent_children[parent_session_id].append(child_session_id)
        self._parent_chain[child_session_id] = parent_session_id

        self._persist()
        logger.info(
            "[CompressionLineage] recorded: parent=%s → child=%s "
            "(msgs %d→%d, tokens %d→%d, watermark=%s)",
            parent_session_id, child_session_id,
            record.parent_message_count, record.child_message_count,
            tokens_before, tokens_after, watermark,
        )
        return record

    def find_live_compression_child(self, parent_session_id: str) -> Optional[CompressionLineage]:
        """查找压缩父会话的活跃子会话。对标 Hermes find_live_compression_child。
        仅当恰好有一个子会话时返回；多个时返回 None（并发分裂，无法确定）。"""
        children = self._parent_children.get(parent_session_id, [])
        if len(children) == 1:
            return self._lineage.get(children[0])
        if len(children) > 1:
            logger.warning(
                "[CompressionLineage] Multiple children for parent=%s: %s — "
                "cannot determine live continuation",
                parent_session_id, children,
            )
        return None

    def get_compression_chain(self, session_id: str) -> List[CompressionLineage]:
        """获取从根会话到当前会话的完整压缩链。对标 Hermes walk lineage。"""
        chain: List[CompressionLineage] = []
        current = session_id
        seen = {current}
        while current in self._parent_chain:
            parent = self._parent_chain[current]
            record = self._lineage.get(current)
            if record:
                chain.append(record)
            if parent in seen:
                break  # 防环
            seen.add(parent)
            current = parent
        chain.reverse()
        return chain

    def reopen_orphaned_compression_session(
        self, session_id: str
    ) -> bool:
        """重新打开孤立的压缩会话。对标 Hermes reopen_orphaned_compression_session。
        仅当：(1) 无活跃子会话、(2) 无活跃锁 时重新打开。"""
        # 检查是否有子会话
        children = self._parent_children.get(session_id, [])
        if children:
            return False

        # 检查是否有活跃锁
        lock = self._locks.get(session_id)
        if lock and not lock.is_expired:
            return False

        # 清除 lineage 记录
        if session_id in self._parent_children:
            del self._parent_children[session_id]
        for child_id, record in list(self._lineage.items()):
            if record.parent_session_id == session_id:
                del self._lineage[child_id]
                if child_id in self._parent_chain:
                    del self._parent_chain[child_id]

        self._persist()
        logger.info("[CompressionLineage] reopened orphaned compression session: %s", session_id)
        return True

    # ------------------------------------------------------------------
    # 压缩锁（对标 Hermes compression_locks 表）
    # ------------------------------------------------------------------

    def try_acquire_lock(
        self, session_id: str, holder: str
    ) -> bool:
        """尝试获取压缩锁。对标 Hermes try_acquire_compression_lock。
        原子操作：删除过期锁 → 插入新锁 → 确认所有权。"""
        now = time.time()

        # 检查现有锁
        existing = self._locks.get(session_id)
        if existing:
            if existing.holder == holder and not existing.is_expired:
                return True  # 己锁且未过期
            if existing.is_expired:
                logger.info("[CompressionLock] reclaimed expired lock: session=%s holder=%s",
                            session_id, existing.holder)
            elif existing.holder != holder:
                return False  # 他锁活跃

        # 获取当前会话指纹
        session_digest = self._get_session_digest(session_id)

        lock = CompressionLock(
            session_id=session_id,
            holder=holder,
            acquired_at=now,
            expires_at=now + self.lock_ttl_seconds,
            session_digest=session_digest,
        )
        self._locks[session_id] = lock
        self._persist()
        logger.debug("[CompressionLock] acquired: session=%s holder=%s", session_id, holder)
        return True

    def refresh_lock(self, session_id: str, holder: str) -> bool:
        """续期压缩锁。对标 Hermes refresh_compression_lock。"""
        lock = self._locks.get(session_id)
        if not lock or lock.holder != holder:
            return False
        lock.expires_at = time.time() + self.lock_ttl_seconds
        self._persist()
        return True

    def release_lock(self, session_id: str, holder: str) -> None:
        """释放压缩锁。对标 Hermes release_compression_lock。"""
        lock = self._locks.get(session_id)
        if lock and lock.holder == holder:
            del self._locks[session_id]
            self._persist()

    def _get_session_digest(self, session_id: str) -> str:
        """获取会话当前消息指纹（对标 Hermes session_digest 防篡改）。"""
        try:
            if self._store is not None:
                # 优先使用原生接口
                get_messages = getattr(self._store, "get_session_messages", None)
                if callable(get_messages):
                    messages = get_messages(session_id)
                    if messages:
                        return content_digest(messages)
                # 回退到 meta 模式
                if hasattr(self._store, "get_meta"):
                    raw = self._store.get_meta(f"session_messages:{session_id}")
                    if isinstance(raw, str):
                        import json as _json
                        messages = _json.loads(raw)
                        if messages:
                            return content_digest(messages)
        except Exception:
            pass
        # 降级：随机指纹（表示无法验证）
        return f"unknown:{str(uuid.uuid4())[:8]}"

    # ------------------------------------------------------------------
    # Watermark 机制（对标 Hermes watermark 处理）
    # ------------------------------------------------------------------

    def compute_watermark(
        self,
        messages: list[dict],
        tail_count: int,
        soft_limit: int = 0,
        estimate_tokens_fn=None,
    ) -> tuple[Optional[int], Optional[int]]:
        """计算压缩水位线。对标 Hermes watermark 处理。

        压缩范围 = messages[:watermark]
        新消息（归属于子会话）= messages[watermark:]
        
        改进了基于 token 预算的水位线计算：
        1. 尾部保护：最近 tail_count 条消息不参与压缩
        2. Token 预算感知：基于 soft_limit 计算可压缩区的实际 token 数，
           确保压缩后剩余 token 不超过 soft_limit
        3. watermark 为压缩起始索引（messages[:watermark] 将被压缩），
           watermark_ceiling 为尾部保护起始索引（messages[watermark_ceiling:] 不参与压缩）
        
        Args:
            messages: 完整消息列表（压缩前）
            tail_count: 尾部保护消息数（最近 N 条不纳入压缩）
            soft_limit: 软限制 token 数（压缩后剩余预算）
            estimate_tokens_fn: token 估算函数 (messages) -> int
        
        Returns:
            (watermark, watermark_ceiling)
            - watermark: 压缩起始索引（含），None 表示不压缩
            - watermark_ceiling: 尾部保护起始索引（含），None 表示无尾部保护
        """
        n = len(messages)
        if n <= 0:
            return None, None

        # 尾部保护起点
        ceiling = n - tail_count if tail_count > 0 else n
        ceiling = max(0, min(ceiling, n))
        
        # 如果没有足够的消息进行压缩
        if ceiling <= 0:
            return None, ceiling

        # 如果未提供 soft_limit 或估算函数，回退到原始简单逻辑
        if soft_limit <= 0 or estimate_tokens_fn is None:
            return ceiling, ceiling

        # Token 预算感知的水位线计算：
        # 从尾部向前扫描，找到第一个位置使得 messages[:watermark] 的 token 数
        # 满足：总 tokens - messages[:watermark] tokens <= soft_limit
        # 即：messages[:watermark] tokens >= total_tokens - soft_limit
        total_tokens = estimate_tokens_fn(messages)
        available_for_compression = max(total_tokens - soft_limit, 0)

        # 二分查找：找到最小的 watermark，使得 messages[:watermark] tokens >= available_for_compression
        # 同时 watermark <= ceiling（尾部保护）
        low, high = 0, ceiling
        result_watermark = None

        while low <= high:
            mid = (low + high) // 2
            mid_tokens = estimate_tokens_fn(messages[:mid]) if mid > 0 else 0
            
            if mid_tokens >= available_for_compression and mid > 0:
                result_watermark = mid
                high = mid - 1  # 尝试更小的 watermark
            else:
                low = mid + 1

        # 如果找不到满足 token 预算的 watermark，使用 ceiling 作为保底
        if result_watermark is None:
            # 检查整个可压缩区是否超过 soft_limit
            ceiling_tokens = estimate_tokens_fn(messages[:ceiling]) if ceiling > 0 else 0
            if ceiling_tokens < available_for_compression:
                # 即使压缩整个可压缩区也无法满足预算 → 跳过压缩
                logger.debug(
                    "[Watermark] Skip: compressible tokens (%d) < needed (%d)",
                    ceiling_tokens, available_for_compression,
                )
                return None, ceiling
            result_watermark = ceiling

        return result_watermark, ceiling

    def split_watermark_messages(
        self,
        messages: list[dict],
        watermark: int | None,
        watermark_ceiling: int | None,
    ) -> tuple[list[dict], list[dict]]:
        """按 Watermark 拆分消息：压缩前消息 vs 压缩期间新消息。
        
        Args:
            messages: 完整消息列表
            watermark: 压缩起始索引（含）
            watermark_ceiling: 尾部保护起始索引（含）
        
        Returns:
            (parent_messages, child_messages)
            - parent_messages: messages[:watermark]（参与压缩的部分）
            - child_messages: messages[watermark:]（压缩期间新消息，归属于子会话）
        """
        if watermark is None:
            return [], list(messages)
        
        # 压缩范围 = [0, watermark)
        # 新消息（归属于子会话）= [watermark:, 包括尾部保护消息）
        parent_msgs = list(messages[:watermark])
        child_msgs = list(messages[watermark:])
        return parent_msgs, child_msgs

    # ------------------------------------------------------------------
    # Turn Lease 机制（对标 Hermes turn_lease）
    # ------------------------------------------------------------------

    def acquire_turn_lease(
        self, session_id: str, holder: str, ttl_seconds: float = 60.0
    ) -> bool:
        """尝试获取压缩 Turn Lease。对标 Hermes try_acquire_session_turn_lease。
        
        Turn Lease 防止多进程/多线程并发压缩同一会话。
        与压缩锁配合使用：Turn Lease 控制"谁可以发起压缩"，
        压缩锁控制"压缩期间的原子性"。
        """
        lease_key = f"turn_lease:{session_id}"
        now = time.time()
        
        existing = self._locks.get(lease_key)
        if existing:
            if existing.holder == holder and not existing.is_expired:
                return True  # 已有有效 lease
            if existing.is_expired:
                logger.debug("[TurnLease] reclaimed expired lease: session=%s", session_id)
            elif existing.holder != holder:
                return False  # 他方持有活跃 lease
        
        lease = CompressionLock(
            session_id=lease_key,
            holder=holder,
            acquired_at=now,
            expires_at=now + ttl_seconds,
            session_digest=f"lease:{session_id}",
        )
        self._locks[lease_key] = lease
        self._persist()
        logger.debug("[TurnLease] acquired: session=%s holder=%s", session_id, holder)
        return True

    def release_turn_lease(self, session_id: str, holder: str) -> None:
        """释放压缩 Turn Lease。对标 Hermes release_session_turn_lease。"""
        lease_key = f"turn_lease:{session_id}"
        lock = self._locks.get(lease_key)
        if lock and lock.holder == holder:
            del self._locks[lease_key]
            self._persist()

    def record_compression_failure(self, error: str = "", use_fallback: bool = False) -> None:
        """记录压缩失败。对标 Hermes record_compression_failure_cooldown。
        Merge-max：取更长的冷却时间，防止短冷却覆盖长冷却。"""
        now = time.time()
        # Merge-max：取更长的冷却时间
        if self._cooldown.cooldown_until > 0:
            self._cooldown.cooldown_until = max(self._cooldown.cooldown_until,
                                                now + self.failure_cooldown_seconds)
        else:
            self._cooldown.cooldown_until = now + self.failure_cooldown_seconds
        self._cooldown.last_failure_error = str(error)[:500]
        if use_fallback:
            self._cooldown.streak_fallback += 1
        self._persist()
        logger.warning(
            "[CompressionCooldown] failure recorded: cooldown_until=%s error=%s fallback_streak=%d",
            self._cooldown.cooldown_until, self._cooldown.last_failure_error, self._cooldown.streak_fallback,
        )

    def clear_cooldown(self) -> None:
        """压缩成功：清除冷却期与 streak。对标 Hermes clear_cooldown。

        注意：禁止命名为 record_compression_success —— 本类 326 行已有带参
        同名方法（记录 lineage 链）。同名后者覆盖前者，会让所有带参调用
        （parent_session_id=...）抛 TypeError，导致压缩链记录失败、压缩结果
        回滚、反复 413（2026-10-11 日志实证）。清冷却语义单独命名。
        """
        self._cooldown.cooldown_until = 0.0
        self._cooldown.last_failure_error = ""
        self._cooldown.streak_fallback = 0
        self._persist()

    def record_effective_compression(self) -> None:
        """有效压缩：清零无效计数。对标 Hermes 的无效计数清零。"""
        if self._cooldown.streak_ineffective:
            self._cooldown.streak_ineffective = 0
            self._persist()

    def record_ineffective_compression(self) -> None:
        """无效压缩：累计 strike，达上限触发熔断。对标 Hermes record_ineffective。"""
        self._cooldown.streak_ineffective += 1
        logger.warning(
            "[CompressionCooldown] ineffective count: %d/%d",
            self._cooldown.streak_ineffective, self.max_ineffective_strikes,
        )
        if self._cooldown.streak_ineffective >= self.max_ineffective_strikes:
            self._arm_recovery_deadline()

    def record_structural_no_op(self, reason: str) -> None:
        """记录结构性 no-op（窗口为空/消息太少），进入短退避。对标 Hermes structural_backoff。"""
        now = time.time()
        self._cooldown.structural_backoff_until = now + self.structural_backoff_seconds
        logger.debug("[CompressionCooldown] structural no-op (%s), backing off", reason)
        self._persist()

    def _arm_recovery_deadline(self) -> None:
        """武装恢复窗口。对标 Hermes _anti_thrash_recovery_deadline。"""
        now = time.time()
        if self._cooldown.recovery_deadline <= 0 or (
            now - self._cooldown.recovery_deadline > self.recovery_seconds
        ):
            self._cooldown.recovery_deadline = now + self.recovery_seconds
            self._persist()

    def check_recovery_window(self) -> bool:
        """检查恢复窗口是否到期。对标 Hermes evaluation_is_probe / can_resume。
        到期放行一次探针，strike 降到 1。"""
        now = time.time()
        if self._cooldown.recovery_deadline <= 0:
            return False
        if now >= self._cooldown.recovery_deadline:
            # 窗口到期：放行一次探针
            self._cooldown.recovery_deadline = 0.0
            if self._cooldown.streak_ineffective >= self.max_ineffective_strikes:
                self._cooldown.streak_ineffective = 1
            if self._cooldown.streak_fallback >= self.max_fallback_streak:
                self._cooldown.streak_fallback = 1
            logger.info(
                "[CompressionCooldown] recovery window elapsed — allowing one probe "
                "(ineffective=%d fallback=%d)",
                self._cooldown.streak_ineffective, self._cooldown.streak_fallback,
            )
            self._persist()
            return True
        return False

    def get_cooldown_state(self) -> dict:
        """获取冷却期完整状态。对标 Hermes get_compression_failure_cooldown + get_row。"""
        now = time.time()
        remaining = 0.0
        is_active = False
        if self._cooldown.cooldown_until > 0:
            is_active = True
            remaining = self._cooldown.cooldown_until - now
        
        return {
            "cooldown_until": self._cooldown.cooldown_until,
            "remaining_seconds": max(0.0, remaining),
            "is_active": is_active,
            "error": self._cooldown.last_failure_error,
            "streak_ineffective": self._cooldown.streak_ineffective,
            "streak_fallback": self._cooldown.streak_fallback,
            "recovery_deadline": self._cooldown.recovery_deadline,
            "recovery_elapsed": (self._cooldown.recovery_deadline - now) if self._cooldown.recovery_deadline > 0 else 0,
            "structural_backoff_until": self._cooldown.structural_backoff_until,
            "structural_backoff_remaining": max(0.0, self._cooldown.structural_backoff_until - now),
            "tripped": self._cooldown.streak_ineffective >= self.max_ineffective_strikes or
                       self._cooldown.streak_fallback >= self.max_fallback_streak,
        }

    def is_cooldown_active(self) -> bool:
        """冷却期是否活跃。"""
        return self._cooldown.is_active

    def get_cooldown_remaining_seconds(self) -> float:
        """冷却期剩余秒数。"""
        if not self._cooldown.is_active:
            return 0.0
        return self._cooldown.cooldown_until - time.time()

    # ------------------------------------------------------------------
    # 可行性跳过（对标 Hermes _feasibility_skip）
    # ------------------------------------------------------------------

    def feasibility_skip(self, middle_tokens: int, soft_limit: int) -> bool:
        """中间可压缩区过小且已有无效记录时，跳过 LLM 摘要。
        对标 Hermes _feasibility_skip。"""
        if self._cooldown.streak_ineffective < 1:
            return False
        if middle_tokens >= int(soft_limit * 0.25):  # 25% 阈值
            return False
        logger.warning(
            "[CompressionCooldown] feasibility skip: middle=%d tokens < %.0f%% of soft limit %d "
            "(ineffective_count=%d) — skipping LLM summarization",
            middle_tokens, 25, soft_limit, self._cooldown.streak_ineffective,
        )
        return True

    # ------------------------------------------------------------------
    # 事务性压缩（对标 Hermes publish_compression_child 原子发布）
    # ------------------------------------------------------------------

    async def transactional_compression(
        self,
        session_id: str,
        holder: str,
        compress_func,
        validate_func,
        **kwargs,
    ) -> Tuple[bool, str]:
        """事务性压缩：锁 → 压缩 → 验证 → 提交 lineage → 释放锁。
        对标 Hermes publish_compression_child 的事务性保证。
        
        Args:
            session_id: 会话 ID
            holder: 压缩器标识
            compress_func: 压缩函数 (messages, **kwargs) -> (compressed_messages, tokens_before, tokens_after)
            validate_func: 验证函数 (compressed_messages, **kwargs) -> None (抛 CompressionError 表示验证失败)
        
        Returns:
            (success: bool, error_message: str)
        """
        # 1. 获取压缩锁
        if not self.try_acquire_lock(session_id, holder):
            return False, "Failed to acquire compression lock: another compressor holds the lock"

        try:
            # 2. 执行压缩
            old_messages = kwargs.get("messages", [])
            compressed_messages, tokens_before, tokens_after = compress_func(old_messages, **kwargs)
            
            # 3. 验证压缩结果
            try:
                validate_func(compressed_messages, **kwargs)
            except Exception as e:
                return False, f"Compression validation failed: {e}"
            
            # 4. 生成 lineage 记录
            child_session_id = str(uuid.uuid4())[:12]
            watermark = kwargs.get("watermark")
            watermark_ceiling = kwargs.get("watermark_ceiling")
            
            record = self.record_compression_success(
                parent_session_id=session_id,
                child_session_id=child_session_id,
                parent_messages=old_messages,
                child_messages=compressed_messages,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                watermark=watermark,
                watermark_ceiling=watermark_ceiling,
            )
            
            # 5. 压缩成功：清除冷却期
            self._cooldown.cooldown_until = 0.0
            self._cooldown.last_failure_error = ""
            self._cooldown.streak_fallback = 0
            if self._cooldown.streak_ineffective:
                self._cooldown.streak_ineffective = 0
            self._persist()
            
            logger.info(
                "[CompressionTransaction] successful: parent=%s → child=%s "
                "(msgs %d→%d, tokens %d→%d)",
                session_id, child_session_id,
                len(old_messages), len(compressed_messages),
                tokens_before, tokens_after,
            )
            return True, ""
            
        except Exception as e:
            # 6. 压缩失败：记录失败，不提交 lineage
            logger.warning("[CompressionTransaction] failed: %s", e)
            self.record_compression_failure(str(e), use_fallback=False)
            return False, str(e)
            
        finally:
            # 7. 释放压缩锁
            self.release_lock(session_id, holder)

    # ------------------------------------------------------------------
    # 状态快照（诊断/遥测）
    # ------------------------------------------------------------------

    def snapshot(self) -> dict:
        """完整状态快照。对标 Hermes 的诊断接口。"""
        return {
            "lineage_count": len(self._lineage),
            "active_locks": len(self._locks),
            "cooldown": self.get_cooldown_state(),
            "parent_children": {k: len(v) for k, v in self._parent_children.items()},
            "lineage_chain_sample": [
                r.to_dict() for r in list(self._lineage.values())[-5:]
            ],
        }

    def reset(self) -> None:
        """重置全部状态（新会话）。"""
        self._lineage.clear()
        self._parent_children.clear()
        self._parent_chain.clear()
        self._locks.clear()
        self._cooldown = CompressionCooldown()
        self._persist()
