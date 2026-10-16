"""
Code Quality 处理器

读取 linter 诊断信息：
- read_lints: 调用项目配置的 linter 获取诊断

# ApprovalClass checklist (新增 / 修改工具时必读)
# 1. 在本文件 Handler 类的 TOOLS 列表加新工具名
# 2. 在同 Handler 类的 TOOL_CLASSES 字典加 ApprovalClass 显式声明
#    （或在 agent.py:_init_handlers 的 register() 调用里加 tool_classes={...}）
# 3. 行为依赖参数 → 在 policy_v2/classifier.py:_refine_with_params 加分支
# 4. 跑 pytest tests/unit/test_classifier_completeness.py 验证
# 详见 docs/policy_v2_research.md §4.21
"""

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.policy_v2 import ApprovalClass

if TYPE_CHECKING:
    from ...agent.core import Agent

logger = logging.getLogger(__name__)


class CodeQualityHandler:
    TOOLS = ["read_lints"]
    TOOL_CLASSES = {"read_lints": ApprovalClass.READONLY_GLOBAL}

    def __init__(self, agent: "Agent"):
        self.agent = agent

    async def handle(self, tool_name: str, params: dict[str, Any]) -> str:
        if tool_name == "read_lints":
            return await self._read_lints(params)
        return f"❌ Unknown code_quality tool: {tool_name}"

    async def _read_lints(self, params: dict) -> str:
        paths = params.get("paths") or []
        from ...core.working_directory import current_working_directory

        cwd = str(current_working_directory(require_available=True))

        diagnostics: list[str] = []
        notes: list[str] = []

        has_python = self._detect_python_project(cwd)
        has_js = self._detect_js_project(cwd)

        if has_python:
            ok, text = await self._run_ruff(paths, cwd)
            if not ok:
                notes.append(text or "ruff 未安装或运行失败：Python 代码未执行 lint 检查")
            elif text:
                diagnostics.append(text)

        if has_js:
            ok, text = await self._run_eslint(paths, cwd)
            if not ok:
                notes.append(text or "eslint/npx 未安装或运行失败：JS 代码未执行 lint 检查")
            elif text:
                diagnostics.append(text)

        if not has_python and not has_js:
            # 无项目指示文件：有可用 linter 则兜底扫描；
            # 若均不可用，如实说明"未执行检查"，不得谎报"无错误"
            checked_any = False
            for run in (self._run_ruff, self._run_eslint):
                ok, text = await run(paths, cwd)
                if ok:
                    checked_any = True
                    if text:
                        diagnostics.append(text)
            if not checked_any:
                notes.append("未检测到 Python/JS 项目指示文件，且 ruff/eslint 均不可用：未执行 lint 检查")

        parts = []
        if diagnostics:
            parts.append("\n\n".join(diagnostics))
        if notes:
            parts.append("⚠️ " + "；".join(notes))
        if not parts:
            scope = ", ".join(paths) if paths else "workspace"
            return f"No linter errors found in {scope}."
        return "\n\n".join(parts)

    def _detect_python_project(self, cwd: str) -> bool:
        indicators = ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", ".flake8"]
        return any((Path(cwd) / f).exists() for f in indicators)

    def _detect_js_project(self, cwd: str) -> bool:
        indicators = [
            "package.json",
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.json",
            ".eslintrc.yml",
        ]
        return any((Path(cwd) / f).exists() for f in indicators)

    async def _run_ruff(self, paths: list[str], cwd: str) -> tuple[bool, str | None]:
        """运行 ruff。返回 (检查是否真正执行, 诊断文本)。

        - (False, None)：ruff 未安装或运行异常 —— 调用方必须报告"未检查"
        - (False, "说明")：运行异常但带原因（如超时）
        - (True, None)：真实无 lint 错误
        - (True, "诊断")：存在 lint 问题
        """
        if not shutil.which("ruff"):
            return False, None

        target_paths = paths if paths else ["."]
        cmd = ["ruff", "check", "--output-format=json", "--no-fix"] + target_paths

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            output = stdout.decode("utf-8", errors="replace").strip()
            if not output:
                return True, None

            try:
                issues = json.loads(output)
            except json.JSONDecodeError:
                return True, f"[ruff] {output}" if output else None

            if not issues:
                return True, None

            lines = [f"[ruff] Found {len(issues)} issue(s):"]
            for issue in issues[:50]:
                loc = issue.get("location", {})
                lines.append(
                    f"  {issue.get('filename', '?')}:{loc.get('row', '?')}:{loc.get('column', '?')}: "
                    f"{issue.get('code', '?')} {issue.get('message', '')}"
                )
            if len(issues) > 50:
                lines.append(f"  ... and {len(issues) - 50} more")
            return True, "\n".join(lines)

        except TimeoutError:
            return False, "[ruff] Timed out after 30s"
        except Exception as e:
            logger.warning(f"ruff failed: {e}")
            return False, None

    async def _run_eslint(self, paths: list[str], cwd: str) -> tuple[bool, str | None]:
        """运行 eslint。返回语义同 _run_ruff。"""
        eslint_cmd = None
        npx = shutil.which("npx")
        if npx:
            eslint_cmd = ["npx", "eslint"]
        elif shutil.which("eslint"):
            eslint_cmd = ["eslint"]
        else:
            return False, None

        target_paths = paths if paths else ["."]
        cmd = eslint_cmd + ["--format=json", "--no-error-on-unmatched-pattern"] + target_paths

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

            output = stdout.decode("utf-8", errors="replace").strip()
            if not output:
                return True, None

            try:
                results = json.loads(output)
            except json.JSONDecodeError:
                return True, f"[eslint] {output[:500]}" if output else None

            lines = []
            total = 0
            for file_result in results:
                for msg in file_result.get("messages", []):
                    total += 1
                    if total <= 50:
                        severity = "error" if msg.get("severity", 0) == 2 else "warning"
                        lines.append(
                            f"  {file_result.get('filePath', '?')}:{msg.get('line', '?')}:"
                            f"{msg.get('column', '?')}: [{severity}] "
                            f"{msg.get('ruleId', '?')} {msg.get('message', '')}"
                        )

            if not total:
                return True, None

            header = f"[eslint] Found {total} issue(s):"
            if total > 50:
                lines.append(f"  ... and {total - 50} more")
            return True, header + "\n" + "\n".join(lines)

        except TimeoutError:
            return False, "[eslint] Timed out after 60s"
        except Exception as e:
            logger.warning(f"eslint failed: {e}")
            return False, None


def create_handler(agent: "Agent"):
    handler = CodeQualityHandler(agent)
    return handler.handle
