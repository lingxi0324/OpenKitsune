"""
Desktop Handler - 桌面自动化工具处理器

处理 Windows 桌面自动化相关的工具调用：
- desktop_screenshot: 截图
- desktop_find_element: 查找元素
- desktop_click: 点击
- desktop_type: 输入文本
- desktop_hotkey: 快捷键
- desktop_scroll: 滚动
- desktop_window: 窗口管理
- desktop_wait: 等待元素/窗口
- desktop_inspect: 检查元素树

# ApprovalClass checklist (新增 / 修改工具时必读)
# 1. 在本文件 Handler 类的 TOOLS 列表加新工具名
# 2. 在同 Handler 类的 TOOL_CLASSES 字典加 ApprovalClass 显式声明
#    （或在 agent.py:_init_handlers 的 register() 调用里加 tool_classes={...}）
# 3. 行为依赖参数 → 在 policy_v2/classifier.py:_refine_with_params 加分支
# 4. 跑 pytest tests/unit/test_classifier_completeness.py 验证
# 详见 docs/policy_v2_research.md §4.21
"""

import logging
import sys
from typing import Any

from ...core.policy_v2 import ApprovalClass

logger = logging.getLogger(__name__)

# 桌面工具列表
DESKTOP_TOOLS = [
    "desktop_screenshot",
    "desktop_find_element",
    "desktop_click",
    "desktop_mouse",
    "desktop_type",
    "desktop_press",
    "desktop_key",
    "desktop_hotkey",
    "desktop_scroll",
    "desktop_window",
    "desktop_wait",
    "desktop_inspect",
    "desktop_batch",
    "desktop_macro",
]


class DesktopHandler:
    """桌面自动化工具处理器"""

    TOOLS = DESKTOP_TOOLS

    # C7 explicit ApprovalClass — desktop interactions are real-world side effects
    TOOL_CLASSES = {
        "desktop_screenshot": ApprovalClass.READONLY_GLOBAL,
        "desktop_find_element": ApprovalClass.READONLY_GLOBAL,
        "desktop_click": ApprovalClass.EXEC_CAPABLE,
        "desktop_mouse": ApprovalClass.EXEC_CAPABLE,
        "desktop_type": ApprovalClass.EXEC_CAPABLE,
        "desktop_press": ApprovalClass.EXEC_CAPABLE,
        "desktop_key": ApprovalClass.EXEC_CAPABLE,
        "desktop_hotkey": ApprovalClass.EXEC_CAPABLE,
        "desktop_scroll": ApprovalClass.EXEC_LOW_RISK,
        "desktop_window": ApprovalClass.EXEC_CAPABLE,
        "desktop_wait": ApprovalClass.EXEC_LOW_RISK,
        "desktop_inspect": ApprovalClass.READONLY_GLOBAL,
        "desktop_batch": ApprovalClass.EXEC_CAPABLE,
        "desktop_macro": ApprovalClass.EXEC_CAPABLE,
    }

    def __init__(self, agent):
        self.agent = agent
        self._desktop_handler = None
        self._available = sys.platform == "win32"

    @property
    def desktop_handler(self):
        """懒加载桌面工具处理器"""
        if self._desktop_handler is None and self._available:
            try:
                from ..desktop.tools import DesktopToolHandler

                self._desktop_handler = DesktopToolHandler()
            except ImportError as e:
                from openkitsune.tools._import_helper import import_or_hint

                hint = import_or_hint("pyautogui") or str(e)
                logger.warning(f"Desktop tools not available: {hint}")
                self._available = False
        return self._desktop_handler

    async def handle(self, tool_name: str, params: dict[str, Any]) -> str:
        """
        处理桌面工具调用

        Args:
            tool_name: 工具名称
            params: 工具参数

        Returns:
            执行结果字符串
        """
        if not self._available:
            from openkitsune.tools._import_helper import import_or_hint

            hint = import_or_hint("pyautogui")
            if hint:
                return f"桌面工具不可用: {hint}"
            return "桌面工具仅在 Windows 上可用"

        handler = self.desktop_handler
        if handler is None:
            return "桌面工具处理器未初始化"

        try:
            result = await handler.handle(tool_name, params)
            return self._format_result(tool_name, result)
        except Exception as e:
            logger.error(f"Desktop tool error: {e}", exc_info=True)
            return f"桌面工具错误: {str(e)}"

    def _format_result(self, tool_name: str, result: Any) -> str:
        """格式化工具执行结果

        注意：LLM 只能看到这里返回的文本。截图工具产出的 OCR 文本、画面理解、
        坐标空间必须在文本里显式呈现，否则模型等于「没看见」这张图。
        """
        if not isinstance(result, dict):
            return str(result)

        if not result.get("success"):
            return f"错误: {result.get('error', '操作失败')}"

        # 截图结果（含 OCR / 视觉理解 / 坐标空间）
        if result.get("file_path"):
            return self._format_screenshot(result)

        # 元素查找结果
        if result.get("found") is not None:
            if result.get("found"):
                elem = result.get("element") or {}
                source = elem.get("source", "unknown")
                return (
                    f"找到元素: {elem.get('name', 'unknown')} "
                    f"@{elem.get('center', 'unknown')} "
                    f"(bbox={elem.get('bbox')}, type={elem.get('control_type')}, "
                    f"source={source}, confidence={elem.get('confidence')})"
                )
            return f"未找到元素: {result.get('message', '')}"

        # 窗口列表
        if result.get("windows"):
            windows = result["windows"]
            output = f"找到 {len(windows)} 个窗口:\n"
            for i, w in enumerate(windows[:10], 1):
                output += f"  {i}. {w.get('title', 'unknown')}\n"
            if len(windows) > 10:
                output += f"  ... 还有 {len(windows) - 10} 个\n"
            return output

        # 元素树
        if result.get("tree"):
            return f"元素树:\n```\n{result.get('text', '')}\n```"

        # 批量执行
        if result.get("results") is not None and tool_name == "desktop_batch":
            lines = [f"批量执行: {result.get('steps_completed', 0)} 步, "
                     f"success={result.get('success')}"]
            for item in result.get("results", []):
                step = item.get("step")
                inner = item.get("result") or {}
                if item.get("error"):
                    lines.append(f"  [{step}] 错误: {item['error']}")
                else:
                    lines.append(f"  [{step}] {inner.get('message') or inner}")
            return "\n".join(lines)

        # 宏序列
        if tool_name == "desktop_macro" and result.get("results") is not None:
            lines = [
                f"宏执行: {result.get('steps_completed', 0)} 步, "
                f"rounds={result.get('rounds', 1)}, success={result.get('success')}"
            ]
            for item in result.get("results", [])[:30]:
                status = "ok" if item.get("success") else "fail"
                detail = item.get("message") or item.get("error") or ""
                lines.append(
                    f"  [r{item.get('round', 0)}/s{item.get('step', 0)}] "
                    f"{item.get('tool', '?')} {status}: {detail}"
                )
            return "\n".join(lines)

        # 通用成功
        return f"{result.get('message', '操作成功')}"

    def _format_screenshot(self, result: dict) -> str:
        """把截图结果渲染成模型可消费的文本（文字 + 画面 + 坐标空间）"""
        lines = [
            f"截图已保存: {result.get('file_path')} "
            f"({result.get('width')}x{result.get('height')})"
        ]

        screen_size = result.get("screen_size")
        if result.get("coordinate_space") == "window" and result.get("window_bbox"):
            origin = result.get("window_origin") or result["window_bbox"][:2]
            lines.append(
                f"坐标空间: 窗口截图（窗口 '{result.get('window_title')}'，"
                f"bbox={result.get('window_bbox')}，origin={origin}）"
                f"；屏幕绝对坐标 = 截图像素坐标 + origin"
            )
        else:
            lines.append("坐标空间: 全屏截图，截图像素坐标即屏幕绝对坐标")

        if screen_size:
            lines.append(f"屏幕尺寸: {screen_size[0]}x{screen_size[1]}")

        ocr_text = result.get("ocr_text")
        if ocr_text:
            indented = "\n".join(f"  {ln}" for ln in str(ocr_text).splitlines() if ln.strip())
            lines.append("识别文字(OCR):\n" + indented)
        elif result.get("extracted_text_success") is False:
            lines.append("识别文字(OCR): 未提取到文字（视觉模型不可用或无文本）")

        vision_analysis = result.get("vision_analysis")
        if vision_analysis:
            lines.append("画面理解:\n" + "\n".join(
                f"  {ln}" for ln in str(vision_analysis).splitlines() if ln.strip()
            ))

        analysis = result.get("analysis")
        if isinstance(analysis, dict) and analysis.get("answer"):
            lines.append("定向分析:\n" + "\n".join(
                f"  {ln}" for ln in str(analysis["answer"]).splitlines() if ln.strip()
            ))

        if ocr_text or vision_analysis:
            lines.append(
                "提示: OCR 文本可直接引用；需要点击时请用 desktop_find_element "
                "获取 UIA 精确屏幕坐标（vision 坐标仅作参考，可能不精确）"
            )

        return "\n".join(lines)


def create_handler(agent) -> callable:
    """
    创建桌面处理器的 handle 方法

    Args:
        agent: Agent 实例

    Returns:
        处理器的 handle 方法
    """
    handler = DesktopHandler(agent)
    return handler.handle
