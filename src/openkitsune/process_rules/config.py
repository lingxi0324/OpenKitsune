"""
流程规则引擎配置（整改版 v2.0 阈值集中定义）

所有阈值与《流程规则整改-v2.md》一致；可通过 settings.process_rules_*
或环境变量覆盖（pydantic settings 前缀 process_rules_ 自动映射）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 默认启用集合（R1-R5, R7, autonomy；R6 模糊补全边界由 preflight/ask 路径承载）
_DEFAULT_ENABLED: tuple[str, ...] = (
    "todo_policy",      # R1
    "checkpoints",      # R2
    "preflight",        # R3
    "arbiter",          # R4
    "exception_tree",   # R5
    "memory_events",    # R7
    "autonomy",         # AI 自主决策层
)


@dataclass
class ProcessRulesConfig:
    """流程规则阈值与开关。默认值 = 整改文档 v2.0 的阈值。"""

    # ── 总开关 ──────────────────────────────────────────────
    enabled: bool = True
    enabled_rules: set[str] = field(default_factory=lambda: set(_DEFAULT_ENABLED))
    # fail-open：规则引擎自身异常只记录，不阻断主流程
    fail_open: bool = True
    # 审计 JSONL 落盘路径（空 = 只走 logging）
    audit_dir: str = ""

    # ── R1 todo 常态化 ──────────────────────────────────────
    todo_min_steps: int = 2          # 步骤数 ≥2 且非纯问答 → 建 todo
    todo_max_steps: int = 8          # 超过 8 条则合并/分层
    # Plan 模式风险信号（命中任一即进 Plan）
    plan_risk_signals: tuple[str, ...] = (
        "irreversible",   # 删除/覆盖/重置/移动用户文件
        "external",       # 对外发送消息/发布/写入共享系统/资金
        "permission",     # 需授权/凭证/跨账号写入
        "user_requested",  # 用户点名先出计划
        "first_time",     # 首次执行的陌生长流程
    )

    # ── R2 检查点 ───────────────────────────────────────────
    checkpoint_enabled: bool = True
    selfcheck_max_seconds: int = 30  # 单次自检 ≤30s
    # 阶段边界：连续 N 个 todo 顺利 → 合并一次核对
    checkpoint_merge_after: int = 3

    # ── R3 工具预检分层 ─────────────────────────────────────
    preflight_enabled: bool = True
    # 同会话已成功调用 ≥N 次 → 快检（不重复预检）
    preflight_fast_check_threshold: int = 2
    # 详检对象：首次使用 / 高风险动作 / 上次失败过 / schema 不确定
    preflight_detail_checks: int = 4  # 详检清单项数

    # ── R4 多 Agent 裁决 ────────────────────────────────────
    arbiter_enabled: bool = True
    # 分歧点 ≥N 或涉核心结论 → 必须走完整裁决流程
    arbiter_dispute_threshold: int = 2

    # ── R5 异常决策树 ───────────────────────────────────────
    exception_tree_enabled: bool = True
    retry_max_transient: int = 2      # 瞬时错误重试上限
    retry_backoff_seconds: tuple[float, float] = (1.0, 3.0)  # 1s → 3s
    retry_max_param: int = 1          # 参数修正重试上限
    retry_max_preflight: int = 1      # 前置补齐重试上限
    # 同类错误累计 ≥N 次 → 停止重试，查共同成因
    common_cause_threshold: int = 3
    # 换通道界限：同一动作失败 ≥N 次 → 换命令/目录/依赖/库/路径
    switch_channel_threshold: int = 2

    # ── 自主决策层（AI 自行决定是否需要触发规则）───────────────
    autonomy_enabled: bool = True
    # auto: L0 低置信才问 LLM；always: 总是问；never: 禁用 LLM（纯确定性）
    autonomy_mode: str = "auto"
    # 确定性置信 < 阈值 → 交给 LLM 自主判断
    autonomy_confidence_threshold: float = 0.75
    autonomy_max_tokens: int = 160          # 单次 LLM 决策输出预算（含 reason 字段）
    autonomy_budget_per_rule: int = 3       # 每会话每规则 LLM 调用预算（成本约束）

    # ── R7 记忆保存 ────────────────────────────────────────
    memory_events_enabled: bool = True
    memory_max_chars: int = 50        # 单条记忆 ≤50 字
    memory_event_types: tuple[str, ...] = (
        "preference",     # 稳定偏好浮现
        "correction",     # 用户纠正 / 明确"记住"
        "decision",       # 关键决策完成（长期约束/口径）
        "conflict",       # 与已存偏好冲突 → update 而非新增
    )

    # ── R8 Plan 合规门禁（代码 Hook 层）─────────────────────
    plan_guard_enabled: bool = True
    # off: 完全关闭；observe: 只审计+提示；enforce: 硬阻断
    plan_guard_mode: str = "enforce"
    # 创建 todo 时要求每步提供 expected / done_when（plan_file 豁免）
    plan_guard_require_expected: bool = True
    # 结构化计划完成步骤时要求 actual= / verdict= 自检证据
    plan_guard_require_evidence: bool = True
    # in_progress 步骤停滞多久后提醒（秒）
    plan_guard_stale_seconds: int = 900

    @classmethod
    def from_settings(cls, settings: object) -> "ProcessRulesConfig":
        """从 openkitsune.config.settings 读取覆盖项；字段缺失时用默认值。

        settings 通过 ``process_rules_<field>`` 属性暴露；为避免在核心
        config.py 大动，这里用 getattr 容错读取。
        """
        cfg = cls()

        def _get(name: str, default):
            try:
                return getattr(settings, f"process_rules_{name}", default)
            except Exception:
                return default

        cfg.enabled = bool(_get("enabled", cfg.enabled))
        enabled_rules = _get("enabled_rules", None)
        if isinstance(enabled_rules, (list, tuple, set)) and enabled_rules:
            cfg.enabled_rules = {str(r) for r in enabled_rules}
        cfg.fail_open = bool(_get("fail_open", cfg.fail_open))
        cfg.audit_dir = str(_get("audit_dir", cfg.audit_dir) or "")

        cfg.todo_min_steps = int(_get("todo_min_steps", cfg.todo_min_steps))
        cfg.todo_max_steps = int(_get("todo_max_steps", cfg.todo_max_steps))
        signals = _get("plan_risk_signals", None)
        if isinstance(signals, (list, tuple)) and signals:
            cfg.plan_risk_signals = tuple(str(s) for s in signals)

        cfg.checkpoint_enabled = bool(_get("checkpoint_enabled", cfg.checkpoint_enabled))
        cfg.selfcheck_max_seconds = int(_get("selfcheck_max_seconds", cfg.selfcheck_max_seconds))
        cfg.checkpoint_merge_after = int(_get("checkpoint_merge_after", cfg.checkpoint_merge_after))

        cfg.preflight_enabled = bool(_get("preflight_enabled", cfg.preflight_enabled))
        cfg.preflight_fast_check_threshold = int(
            _get("preflight_fast_check_threshold", cfg.preflight_fast_check_threshold)
        )
        cfg.preflight_detail_checks = int(_get("preflight_detail_checks", cfg.preflight_detail_checks))

        cfg.arbiter_enabled = bool(_get("arbiter_enabled", cfg.arbiter_enabled))
        cfg.arbiter_dispute_threshold = int(
            _get("arbiter_dispute_threshold", cfg.arbiter_dispute_threshold)
        )

        cfg.exception_tree_enabled = bool(_get("exception_tree_enabled", cfg.exception_tree_enabled))
        cfg.retry_max_transient = int(_get("retry_max_transient", cfg.retry_max_transient))
        backoff = _get("retry_backoff_seconds", None)
        if isinstance(backoff, (list, tuple)) and len(backoff) == 2:
            cfg.retry_backoff_seconds = (float(backoff[0]), float(backoff[1]))
        cfg.retry_max_param = int(_get("retry_max_param", cfg.retry_max_param))
        cfg.retry_max_preflight = int(_get("retry_max_preflight", cfg.retry_max_preflight))
        cfg.common_cause_threshold = int(_get("common_cause_threshold", cfg.common_cause_threshold))
        cfg.switch_channel_threshold = int(
            _get("switch_channel_threshold", cfg.switch_channel_threshold)
        )

        cfg.memory_events_enabled = bool(_get("memory_events_enabled", cfg.memory_events_enabled))
        cfg.memory_max_chars = int(_get("memory_max_chars", cfg.memory_max_chars))
        types = _get("memory_event_types", None)
        if isinstance(types, (list, tuple)) and types:
            cfg.memory_event_types = tuple(str(t) for t in types)

        cfg.autonomy_enabled = bool(_get("autonomy_enabled", cfg.autonomy_enabled))
        mode = _get("autonomy_mode", cfg.autonomy_mode)
        if str(mode) in ("auto", "always", "never"):
            cfg.autonomy_mode = str(mode)
        cfg.autonomy_confidence_threshold = float(
            _get("autonomy_confidence_threshold", cfg.autonomy_confidence_threshold)
        )
        cfg.autonomy_max_tokens = int(_get("autonomy_max_tokens", cfg.autonomy_max_tokens))
        cfg.autonomy_budget_per_rule = int(
            _get("autonomy_budget_per_rule", cfg.autonomy_budget_per_rule)
        )

        cfg.plan_guard_enabled = bool(_get("plan_guard_enabled", cfg.plan_guard_enabled))
        guard_mode = _get("plan_guard_mode", cfg.plan_guard_mode)
        if str(guard_mode) in ("off", "observe", "enforce"):
            cfg.plan_guard_mode = str(guard_mode)
        cfg.plan_guard_require_expected = bool(
            _get("plan_guard_require_expected", cfg.plan_guard_require_expected)
        )
        cfg.plan_guard_require_evidence = bool(
            _get("plan_guard_require_evidence", cfg.plan_guard_require_evidence)
        )
        cfg.plan_guard_stale_seconds = int(
            _get("plan_guard_stale_seconds", cfg.plan_guard_stale_seconds)
        )

        return cfg

    def rule_enabled(self, rule: str) -> bool:
        return self.enabled and rule in self.enabled_rules


_CONFIG_CACHE: ProcessRulesConfig | None = None


def get_process_rules_config(settings: object | None = None) -> ProcessRulesConfig:
    """全局配置单例。首次调用时从 settings 合并；后续复用。

    允许测试注入 settings 对象（显式传参时不缓存）；
    None 时尝试从 openkitsune.config.settings 读，但**只在首次**读取并缓存，
    之后一律返回缓存实例——保证调用方对 cfg 的运行时修改生效。
    """
    global _CONFIG_CACHE
    if settings is not None:
        # 显式注入：测试或外部覆盖，不污染全局缓存
        return ProcessRulesConfig.from_settings(settings)
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    try:
        from openkitsune.config import settings as _s

        _CONFIG_CACHE = ProcessRulesConfig.from_settings(_s)
    except Exception:
        _CONFIG_CACHE = ProcessRulesConfig()
    return _CONFIG_CACHE


def reset_config_cache() -> None:
    """测试用：清空配置缓存。"""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None
