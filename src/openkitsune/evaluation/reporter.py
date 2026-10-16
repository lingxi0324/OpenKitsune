"""
评估报告生成器

将评估结果格式化为多种格式:
- JSON: 机器可读的完整报告
- 文本: 人类可读的摘要报告
- Markdown: 用于 selfcheck 命令展示
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from .metrics import EvalMetrics, EvalResult

logger = logging.getLogger(__name__)


class Reporter:
    """评估报告生成器。"""

    def __init__(self, output_dir: str = "data/evaluation") -> None:
        self._output_dir = output_dir

    async def save(
        self,
        metrics: EvalMetrics,
        results: list[EvalResult],
        *,
        report_name: str | None = None,
    ) -> str:
        """
        保存评估报告。

        Args:
            metrics: 聚合指标
            results: 各 trace 评估结果
            report_name: 自定义报告名称

        Returns:
            报告文件路径
        """
        os.makedirs(self._output_dir, exist_ok=True)

        if report_name is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            report_name = f"eval_{timestamp}"

        # 保存 JSON 报告
        json_path = os.path.join(self._output_dir, f"{report_name}.json")
        report_data = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "metrics": metrics.to_dict(),
            "results": [
                {
                    "trace_id": r.trace_id,
                    "judge_score": r.judge_score,
                    "judge_reasoning": r.judge_reasoning,
                    "judge_suggestions": r.judge_suggestions,
                    "tags": r.tags,
                    "task_completed": r.metrics.task_completed,
                    "iterations": r.metrics.total_iterations,
                    "tool_calls": r.metrics.total_tool_calls,
                    "tool_errors": r.metrics.tool_errors,
                    "duration_ms": r.metrics.total_duration_ms,
                    "total_tokens": r.metrics.total_input_tokens + r.metrics.total_output_tokens,
                }
                for r in results
            ],
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)

        # 保存 Markdown 报告
        md_path = os.path.join(self._output_dir, f"{report_name}.md")
        md_content = self._generate_markdown(metrics, results)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        logger.info(f"[Reporter] Saved evaluation report: {json_path}")
        return json_path

    def _generate_markdown(
        self,
        metrics: EvalMetrics,
        results: list[EvalResult],
    ) -> str:
        """生成 Markdown 格式报告。"""
        lines = [
            "# Agent 评估报告",
            "",
            f"**生成时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**评估 Trace 数**: {metrics.total_traces}",
            "",
            "## 核心指标",
            "",
            "| 指标 | 值 |",
            "|------|------|",
            f"| 任务完成率 | {metrics.task_completion_rate:.1%} |",
            f"| 工具无错率 | {metrics.tool_selection_accuracy:.1%} |",
            f"| Judge 平均分 | {metrics.avg_judge_score:.2f}/1.0 |",
            f"| 平均迭代次数 | {metrics.avg_iterations:.1f} |",
            f"| 平均 Token | {metrics.avg_token_usage:,} |",
            f"| 平均延迟 | {metrics.avg_latency_ms:.0f}ms |",
            "",
            "## 异常指标",
            "",
            "| 指标 | 值 |",
            "|------|------|",
            f"| 循环检测率 | {metrics.loop_detection_rate:.1%} |",
            f"| 错误恢复率 | {metrics.error_recovery_rate:.1%} |",
            f"| 回滚触发率 | {metrics.rollback_rate:.1%} |",
            "",
        ]

        # 失败案例分析
        failed = [r for r in results if not r.is_good()]
        if failed:
            lines.append(f"## 需要关注的案例 ({len(failed)} 个)")
            lines.append("")
            for r in failed[:10]:
                tags_str = ", ".join(r.tags) if r.tags else "无标签"
                lines.append(f"### Trace: {r.trace_id}")
                lines.append(f"- **标签**: {tags_str}")
                lines.append(f"- **Judge 评分**: {r.judge_score:.2f}")
                lines.append(f"- **原因**: {r.judge_reasoning[:200]}")
                if r.judge_suggestions:
                    lines.append("- **建议**:")
                    for s in r.judge_suggestions[:3]:
                        lines.append(f"  - {s}")
                lines.append("")

        # 改进建议汇总
        all_suggestions: list[str] = []
        for r in results:
            all_suggestions.extend(r.judge_suggestions)

        if all_suggestions:
            # 简单去重
            unique = list(dict.fromkeys(all_suggestions))
            lines.append("## 改进建议汇总")
            lines.append("")
            for i, s in enumerate(unique[:10], 1):
                lines.append(f"{i}. {s}")
            lines.append("")

        return "\n".join(lines)

    async def load_latest(self) -> dict[str, Any] | None:
        """加载最新的评估报告。"""
        output_path = Path(self._output_dir)
        if not output_path.exists():
            return None

        json_files = sorted(output_path.glob("eval_*.json"), reverse=True)
        if not json_files:
            return None

        try:
            with open(json_files[0], encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"[Reporter] Failed to load report: {e}")
            return None
