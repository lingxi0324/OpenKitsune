"""KV 驱逐桥接：把 ContextManager 的 compacted_spans 接到 llama.cpp server。

OpenKitsune 与 F:\\llama-cpp-server 的适配层（services/kv_evict_llamacpp.py）
解耦桥接：适配层可导入时构造 LlamaCppKvEvictor 并绑定
``context_manager.kv_cache_evict_callback``；任何失败（导入/配置/网络）仅
记录并静默降级，绝不阻断 Agent 启动。

挂接入口（AgentRuntime 主链路初始化后调用）::

    attach_kv_evict_callback(context_manager, settings)
"""

from __future__ import annotations

import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)


def attach_kv_evict_callback(
    context_manager: Any,
    settings: Any,
) -> bool:
    """按配置把 KV 驱逐回调挂到 context_manager 上。

    Returns:
        True 表示已挂接成功；False 表示未启用或挂接失败（静默降级）。
    """
    enabled = getattr(settings, "kv_evict_llamacpp_enabled", False)
    if not enabled:
        return False
    adapter_path = getattr(settings, "kv_evict_llamacpp_adapter_path", "") or ""
    if not adapter_path:
        logger.warning("[KVEvictBridge] kv_evict adapter path not configured; skip")
        return False
    try:
        # 适配层位于 F:\\llama-cpp-server\\services（独立服务资产，不属于
        # OpenKitsune 包），动态加入 sys.path 后按名导入，避免硬编码包依赖。
        if adapter_path not in sys.path:
            sys.path.insert(0, adapter_path)
        from kv_evict_llamacpp import LlamaCppKvEvictor  # type: ignore

        evictor = LlamaCppKvEvictor(
            base_url=str(getattr(settings, "kv_evict_llamacpp_base_url", "http://127.0.0.1:8220")),
            manager_url=str(getattr(settings, "kv_evict_llamacpp_manager_url", "http://127.0.0.1:8240")),
            model_id=str(getattr(settings, "kv_evict_llamacpp_model_id", "")),
            restart_threshold=float(getattr(settings, "kv_evict_llamacpp_restart_threshold", 0.50)),
            restart_cooldown_seconds=float(
                getattr(settings, "kv_evict_llamacpp_restart_cooldown_seconds", 600)
            ),
            enable_restart=bool(getattr(settings, "kv_evict_llamacpp_enable_restart", False)),
            enable_gap_pause=bool(getattr(settings, "kv_evict_llamacpp_enable_gap_pause", False)),
            log_dir=str(getattr(settings, "kv_evict_llamacpp_log_dir", "")),
        )
        context_manager.kv_cache_evict_callback = evictor.evict
        # 间隙驱逐回调：工具执行阶段（引擎空闲）「暂停 → 清理 → 恢复」。
        # 由 AgentRuntime 在工具执行间隙调用 context_manager.drain_gap_kv_evict()。
        if getattr(evictor, "enable_gap_pause", False):
            context_manager.kv_gap_evict_callback = evictor.evict_at_gap
            logger.info(
                f"[KVEvictBridge] gap eviction armed "
                f"(min_coverage={getattr(settings, 'kv_evict_llamacpp_gap_pause_min_coverage', 0.30)})"
            )
        logger.info(
            "[KVEvictBridge] attached LlamaCppKvEvictor "
            f"(model={evictor.model_id}, base={evictor.base_url})"
        )
        return True
    except Exception as exc:
        logger.warning(f"[KVEvictBridge] attach failed, KV eviction disabled: {exc}")
        return False
