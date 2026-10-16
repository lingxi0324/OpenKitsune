"""
追踪导出器

将 Trace 数据导出到不同的后端:
- FileExporter: JSON 文件存储 (默认)
- ConsoleExporter: 控制台输出 (开发调试)
- OpenTelemetry: OTEL 兼容导出 (可选扩展)
"""

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from .tracer import SpanStatus, Trace

logger = logging.getLogger(__name__)


class TraceExporter(ABC):
    """追踪导出器基类"""

    @abstractmethod
    def export(self, trace: Trace) -> None:
        """导出一个 Trace"""
        ...

    def shutdown(self) -> None:
        """关闭导出器（释放资源）- 子类可重写"""
        # 默认实现不做任何事情，子类可以重写此方法释放资源
        return None


class FileExporter(TraceExporter):
    """
    JSON 文件导出器。

    按日期分目录存储:
      data/traces/
        2026-02-10/
          trace-abc123.json
          trace-def456.json
        2026-02-11/
          ...

    同时维护一个 daily_summary.json 用于聚合统计。
    """

    def __init__(self, base_dir: str | Path = "data/traces") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def export(self, trace: Trace) -> None:
        """导出 Trace 到 JSON 文件"""
        try:
            # 按日期分目录
            date_str = datetime.fromtimestamp(trace.start_time).strftime("%Y-%m-%d")
            day_dir = self._base_dir / date_str
            day_dir.mkdir(parents=True, exist_ok=True)

            # 写入 trace 文件
            trace_file = day_dir / f"trace-{trace.trace_id[:12]}.json"
            trace_dict = trace.to_dict()

            with open(trace_file, "w", encoding="utf-8") as f:
                json.dump(trace_dict, f, ensure_ascii=False, indent=2, default=str)

            # 更新每日摘要
            self._update_daily_summary(day_dir, trace)

            logger.debug(f"[Tracing] Exported trace {trace.trace_id[:8]} to {trace_file}")

        except Exception as e:
            logger.warning(f"[Tracing] Failed to export trace to file: {e}")

    def _update_daily_summary(self, day_dir: Path, trace: Trace) -> None:
        """更新每日摘要文件"""
        summary_file = day_dir / "daily_summary.json"

        # 加载现有摘要
        summary: dict[str, Any] = {}
        if summary_file.exists():
            try:
                with open(summary_file, encoding="utf-8") as f:
                    summary = json.load(f)
            except Exception:
                summary = {}

        # 更新统计
        trace_summary = trace.get_summary()
        traces = summary.get("traces", [])
        traces.append(
            {
                "trace_id": trace.trace_id,
                "session_id": trace.session_id,
                "duration_ms": trace_summary.get("duration_ms"),
                "llm_calls": trace_summary.get("llm_calls", 0),
                "tool_calls": trace_summary.get("tool_calls", 0),
                "tool_errors": trace_summary.get("tool_errors", 0),
                "total_input_tokens": trace_summary.get("total_input_tokens", 0),
                "total_output_tokens": trace_summary.get("total_output_tokens", 0),
            }
        )

        # 聚合统计
        total_llm_calls = sum(t.get("llm_calls", 0) for t in traces)
        total_tool_calls = sum(t.get("tool_calls", 0) for t in traces)
        total_tool_errors = sum(t.get("tool_errors", 0) for t in traces)
        total_input_tokens = sum(t.get("total_input_tokens", 0) for t in traces)
        total_output_tokens = sum(t.get("total_output_tokens", 0) for t in traces)

        durations = [t.get("duration_ms", 0) for t in traces if t.get("duration_ms")]
        avg_duration = sum(durations) / len(durations) if durations else 0

        summary = {
            "date": day_dir.name,
            "total_traces": len(traces),
            "total_llm_calls": total_llm_calls,
            "total_tool_calls": total_tool_calls,
            "total_tool_errors": total_tool_errors,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "avg_duration_ms": round(avg_duration, 2),
            "tool_error_rate": round(total_tool_errors / max(total_tool_calls, 1), 4),
            "traces": traces,
        }

        try:
            with open(summary_file, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
        except Exception as e:
            logger.warning(f"[Tracing] Failed to update daily summary: {e}")

    def load_traces_by_date(self, date_str: str) -> list[dict]:
        """加载指定日期的所有 Trace"""
        day_dir = self._base_dir / date_str
        if not day_dir.exists():
            return []

        traces = []
        for trace_file in sorted(day_dir.glob("trace-*.json")):
            try:
                with open(trace_file, encoding="utf-8") as f:
                    traces.append(json.load(f))
            except Exception as e:
                logger.warning(f"[Tracing] Failed to load trace {trace_file}: {e}")

        return traces

    def load_daily_summary(self, date_str: str) -> dict | None:
        """加载指定日期的摘要"""
        summary_file = self._base_dir / date_str / "daily_summary.json"
        if not summary_file.exists():
            return None
        try:
            with open(summary_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


class ConsoleExporter(TraceExporter):
    """
    控制台导出器。

    以可读格式打印 Trace 信息，用于开发调试。
    """

    def __init__(self, verbose: bool = False) -> None:
        self._verbose = verbose

    def export(self, trace: Trace) -> None:
        """打印 Trace 到控制台"""
        summary = trace.get_summary()
        duration = summary.get("duration_ms")
        duration_str = f"{duration:.0f}ms" if duration else "N/A"

        header = (
            f"[Trace] {trace.trace_id[:8]} | "
            f"session={trace.session_id[:12] if trace.session_id else 'N/A'} | "
            f"duration={duration_str} | "
            f"spans={summary['total_spans']} | "
            f"llm={summary['llm_calls']} | "
            f"tools={summary['tool_calls']} "
            f"(errors={summary['tool_errors']}) | "
            f"tokens_in={summary['total_input_tokens']} "
            f"tokens_out={summary['total_output_tokens']}"
        )
        logger.info(header)

        if self._verbose:
            for span in trace.spans:
                status_icon = "OK" if span.status == SpanStatus.OK else "ERR"
                duration_ms = f"{span.duration_ms:.0f}ms" if span.duration_ms else "..."
                indent = "  "
                if span.parent_id:
                    indent = "    "
                logger.info(
                    f"{indent}[{status_icon}] {span.name} "
                    f"({span.span_type.value}) {duration_ms} "
                    f"{span.attributes}"
                )
