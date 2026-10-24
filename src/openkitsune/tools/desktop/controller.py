"""
Windows 桌面自动化 - 主控制器

统一接口，智能选择 UIA 或 Vision 方案
"""

import asyncio
import logging
import sys
import time
from collections.abc import Callable

from PIL import Image

from .actions import KeyboardController, MouseController, get_keyboard, get_mouse
from .cache import ElementCache, get_cache
from .capture import ScreenCapture, get_capture
from .config import DesktopConfig, get_config
from .types import (
    ActionResult,
    BoundingBox,
    FindMethod,
    MouseButton,
    ScrollDirection,
    UIElement,
    WindowAction,
    WindowInfo,
)
from .uia import UIAClient, UIAElementWrapper, UIAInspector, get_uia_client
from .vision import VisionAnalyzer, get_vision_analyzer

# 平台检查
if sys.platform != "win32":
    raise ImportError(
        f"Desktop automation module is Windows-only. Current platform: {sys.platform}"
    )

logger = logging.getLogger(__name__)


class DesktopController:
    """
    Windows 桌面控制器

    统一接口，智能选择 UIA 或 Vision 方案：
    - 标准 Windows 应用 → UIAutomation（快速准确）
    - 非标准 UI → Vision（通用兜底）
    """

    def __init__(
        self,
        config: DesktopConfig | None = None,
    ):
        """
        Args:
            config: 配置对象，None 使用全局配置
        """
        self._config = config or get_config()

        # 延迟初始化组件
        self._capture: ScreenCapture | None = None
        self._mouse: MouseController | None = None
        self._keyboard: KeyboardController | None = None
        self._uia: UIAClient | None = None
        self._vision: VisionAnalyzer | None = None
        self._cache: ElementCache | None = None
        self._inspector: UIAInspector | None = None

    # ==================== 组件访问器 ====================

    @property
    def capture(self) -> ScreenCapture:
        """截图模块"""
        if self._capture is None:
            self._capture = get_capture()
        return self._capture

    @property
    def mouse(self) -> MouseController:
        """鼠标控制器"""
        if self._mouse is None:
            self._mouse = get_mouse()
        return self._mouse

    @property
    def keyboard(self) -> KeyboardController:
        """键盘控制器"""
        if self._keyboard is None:
            self._keyboard = get_keyboard()
        return self._keyboard

    @property
    def uia(self) -> UIAClient:
        """UIAutomation 客户端"""
        if self._uia is None:
            self._uia = get_uia_client()
        return self._uia

    @property
    def vision(self) -> VisionAnalyzer:
        """视觉分析器"""
        if self._vision is None:
            self._vision = get_vision_analyzer()
        return self._vision

    @property
    def cache(self) -> ElementCache:
        """元素缓存"""
        if self._cache is None:
            self._cache = get_cache()
        return self._cache

    @property
    def inspector(self) -> UIAInspector:
        """UIA 检查器"""
        if self._inspector is None:
            self._inspector = UIAInspector(self.uia)
        return self._inspector

    # ==================== 截图 ====================

    def screenshot(
        self,
        window_title: str | None = None,
        region: tuple[int, int, int, int] | None = None,
        monitor: int | None = None,
    ) -> Image.Image:
        """
        截取屏幕

        Args:
            window_title: 窗口标题，截取指定窗口
            region: 区域 (x, y, width, height)
            monitor: 显示器索引

        Returns:
            PIL Image 对象
        """
        if window_title:
            # 查找窗口并截取
            window = self.uia.find_window_fuzzy(window_title, timeout=2.0)
            if window and window.bbox:
                return self.capture.capture_window(window.bbox, window_title)
            logger.warning(f"Window not found: {window_title}, capturing full screen")

        return self.capture.capture(monitor=monitor, region=region)

    def screenshot_base64(
        self,
        window_title: str | None = None,
        region: tuple[int, int, int, int] | None = None,
        resize: bool = True,
    ) -> str:
        """截取屏幕并返回 base64"""
        img = self.screenshot(window_title=window_title, region=region)
        return self.capture.to_base64(img, resize_for_api=resize)

    # ==================== 元素查找 ====================

    async def find_element(
        self,
        target: str,
        window_title: str | None = None,
        method: str | FindMethod = FindMethod.AUTO,
        timeout: float | None = None,
    ) -> UIElement | None:
        """
        查找 UI 元素

        Args:
            target: 元素描述（如"保存按钮"、"name:保存"、"id:btn_save"）
            window_title: 限定在某个窗口内查找
            method: 查找方法 (auto, uia, vision)
            timeout: 超时时间

        Returns:
            找到的元素，未找到返回 None
        """
        method = FindMethod(method) if isinstance(method, str) else method
        config = self._config.uia
        search_timeout = timeout or config.timeout

        # 解析目标
        parsed = self._parse_target(target)

        # 获取搜索根
        root = None
        if window_title:
            root = self.uia.find_window_fuzzy(window_title, timeout=2.0)
            if not root:
                logger.warning(f"Window not found: {window_title}")

        # 根据方法选择策略
        if method == FindMethod.UIA:
            return await self._find_by_uia(parsed, root, search_timeout)
        elif method == FindMethod.VISION:
            return await self._find_by_vision(target, window_title)
        else:  # AUTO
            # 先尝试 UIA
            element = await self._find_by_uia(parsed, root, search_timeout / 2)
            if element:
                return element

            # 回退到 Vision
            if self._config.vision.enabled:
                logger.info(f"UIA not found, falling back to vision: {target}")
                return await self._find_by_vision(target, window_title)

            return None

    def _parse_target(self, target: str) -> dict:
        """
        解析目标字符串

        支持格式：
        - "name:保存" → 按名称查找
        - "id:btn_save" → 按自动化 ID 查找
        - "type:Button" → 按控件类型查找
        - "保存按钮" → 自然语言描述

        自然语言里的通用控件名词（"按钮"/"输入框"等）会被剥离：
        - "PING 按钮" → 按名称 "PING" 查按钮
        - "输入框" → 按类型 Edit 查第一个输入控件
        """
        result = {"description": target}

        if ":" in target:
            prefix, value = target.split(":", 1)
            prefix = prefix.lower().strip()
            value = value.strip()

            if prefix == "name":
                result["name"] = value
                return result
            elif prefix == "id":
                result["automation_id"] = value
                return result
            elif prefix == "type":
                result["control_type"] = value
                return result
            elif prefix == "class":
                result["class_name"] = value
                return result

        _CONTROL_NOUNS = (
            ("输入框", "Edit"),
            ("文本框", "Edit"),
            ("按钮", "Button"),
            ("图标", "Image"),
            ("菜单", "Menu"),
            ("链接", "Hyperlink"),
            ("下拉框", "ComboBox"),
            ("复选框", "CheckBox"),
        )
        stripped = target.strip()
        for noun, control_type in _CONTROL_NOUNS:
            if stripped.endswith(noun):
                rest = stripped[: -len(noun)].strip(" 　:：,，")
                if rest:
                    result["name"] = rest
                    result["description"] = rest
                else:
                    result["control_type"] = control_type
                    # 纯控件名词（"输入框"/"按钮"）：只按类型查，避免用名词当名字匹配
                    result["description"] = ""
                break

        return result

    async def _find_by_uia(
        self,
        criteria: dict,
        root: UIAElementWrapper | None,
        timeout: float,
    ) -> UIElement | None:
        """使用 UIAutomation 查找"""
        try:
            element = self.uia.find_element(
                root=root,
                name=criteria.get("name"),
                name_re=criteria.get("description") if not criteria.get("name") else None,
                control_type=criteria.get("control_type"),
                automation_id=criteria.get("automation_id"),
                class_name=criteria.get("class_name"),
                timeout=timeout,
            )

            if element:
                return element.to_ui_element()
        except Exception as e:
            logger.debug(f"UIA search failed: {e}")

        return None

    async def _find_by_vision(
        self,
        description: str,
        window_title: str | None = None,
    ) -> UIElement | None:
        """使用视觉识别查找

        注意：视觉模型返回的 bbox 是「截图内相对坐标」。
        - 全屏截图 → 相对坐标 == 屏幕绝对坐标
        - 窗口截图 → 必须加上窗口左上角偏移，否则点击会偏到窗口外
        """
        try:
            origin = (0, 0)
            if window_title:
                window = self.uia.find_window_fuzzy(window_title, timeout=2.0)
                if window and window.bbox:
                    origin = (window.bbox.left, window.bbox.top)

            # 截图
            img = self.screenshot(window_title=window_title)

            # 视觉查找
            location = await self.vision.find_element(description, img)

            if location:
                element = location.to_ui_element()
                if element.bbox and origin != (0, 0):
                    element.bbox = BoundingBox(
                        left=element.bbox.left + origin[0],
                        top=element.bbox.top + origin[1],
                        right=element.bbox.right + origin[0],
                        bottom=element.bbox.bottom + origin[1],
                    )
                return element
        except Exception as e:
            logger.error(f"Vision search failed: {e}")

        return None

    # ==================== 点击操作 ====================

    async def click(
        self,
        target: str | tuple[int, int] | UIElement,
        button: str | MouseButton = MouseButton.LEFT,
        double: bool = False,
        method: str | FindMethod = FindMethod.AUTO,
        window_title: str | None = None,
        modifiers: list[str] | tuple[str, ...] | None = None,
    ) -> ActionResult:
        """
        点击目标

        Args:
            target: 目标（元素描述、坐标元组或 UIElement）
            button: 鼠标按钮
            double: 是否双击
            method: 元素查找方法
            window_title: 限定在某个窗口内查找元素
            modifiers: 同时按住的修饰键（ctrl/shift/alt/win）

        Returns:
            ActionResult
        """
        start_time = time.time()

        try:
            # 解析目标坐标
            x, y = await self._resolve_click_target(target, method, window_title)

            if x is None or y is None:
                return ActionResult(
                    success=False,
                    action="click",
                    target=str(target),
                    error=f"Cannot find target: {target}",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            # 执行点击
            clicks = 2 if double else 1
            result = self.mouse.click(
                x, y, button=button, clicks=clicks, modifiers=modifiers
            )
            result.target = str(target)

            return result

        except Exception as e:
            logger.error(f"Click failed: {e}")
            return ActionResult(
                success=False,
                action="click",
                target=str(target),
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    async def _resolve_click_target(
        self,
        target: str | tuple[int, int] | UIElement,
        method: FindMethod,
        window_title: str | None = None,
    ) -> tuple[int | None, int | None]:
        """解析点击目标为坐标"""
        if isinstance(target, tuple) and len(target) == 2:
            return target

        if isinstance(target, UIElement):
            if target.center:
                return target.center
            return None, None

        if isinstance(target, str):
            # 尝试解析坐标字符串 "x,y"
            try:
                parts = target.split(",")
                if len(parts) == 2:
                    return int(parts[0].strip()), int(parts[1].strip())
            except (ValueError, IndexError):
                pass

            # 作为元素描述查找
            element = await self.find_element(target, window_title=window_title, method=method)
            if element and element.center:
                return element.center

        return None, None

    async def double_click(
        self,
        target: str | tuple[int, int] | UIElement,
        method: str | FindMethod = FindMethod.AUTO,
        window_title: str | None = None,
    ) -> ActionResult:
        """双击"""
        return await self.click(target, double=True, method=method, window_title=window_title)

    async def right_click(
        self,
        target: str | tuple[int, int] | UIElement,
        method: str | FindMethod = FindMethod.AUTO,
        window_title: str | None = None,
    ) -> ActionResult:
        """右键点击"""
        return await self.click(
            target, button=MouseButton.RIGHT, method=method, window_title=window_title
        )

    # ==================== 输入操作 ====================

    def type_text(
        self,
        text: str,
        clear_first: bool = False,
        method: str = "auto",
    ) -> ActionResult:
        """
        输入文本

        Args:
            text: 要输入的文本
            clear_first: 是否先清空（Ctrl+A）
            method: auto / paste / type（见 KeyboardController.type_text）

        Returns:
            ActionResult
        """
        start_time = time.time()

        try:
            if clear_first:
                self.keyboard.select_all()
                time.sleep(0.1)

            result = self.keyboard.type_text(text, method=method)
            return result

        except Exception as e:
            return ActionResult(
                success=False,
                action="type",
                target=text,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def hotkey(self, *keys: str) -> ActionResult:
        """执行快捷键"""
        return self.keyboard.hotkey(*keys)

    def press(self, key: str, times: int = 1) -> ActionResult:
        """按下按键（可重复），如 press("enter") / press("space")"""
        if times and times > 1:
            return self.keyboard.press_multiple(key, presses=int(times))
        return self.keyboard.press(key)

    def key_down(self, key: str) -> ActionResult:
        """按住按键不释放（游戏/组合操作）"""
        return self.keyboard.key_down(key)

    def key_up(self, key: str) -> ActionResult:
        """释放按键"""
        return self.keyboard.key_up(key)

    def release_all_keys(self) -> ActionResult:
        """释放所有仍被按住的按键（宏结束后兜底，防止按键卡住）"""
        return self.keyboard.release_all()

    # ==================== 拖拽 / 鼠标状态 ====================

    def drag(
        self,
        from_x: int,
        from_y: int,
        to_x: int,
        to_y: int,
        duration: float = 0.5,
        button: str | MouseButton = MouseButton.LEFT,
        modifiers: list[str] | tuple[str, ...] | None = None,
    ) -> ActionResult:
        """从起点拖拽到终点（文件拖放、框选、滑块、游戏视角）"""
        return self.mouse.drag(
            from_x,
            from_y,
            to_x,
            to_y,
            duration=duration,
            button=button,
            modifiers=modifiers,
        )

    def drag_to(
        self,
        to_x: int,
        to_y: int,
        duration: float = 0.5,
        button: str | MouseButton = MouseButton.LEFT,
        modifiers: list[str] | tuple[str, ...] | None = None,
    ) -> ActionResult:
        """从当前鼠标位置拖拽到目标位置"""
        return self.mouse.drag_to(
            to_x, to_y, duration=duration, button=button, modifiers=modifiers
        )

    def mouse_position(self) -> tuple[int, int]:
        """当前鼠标屏幕坐标"""
        return self.mouse.get_position()

    def mouse_down(
        self,
        button: str | MouseButton = MouseButton.LEFT,
        x: int | None = None,
        y: int | None = None,
    ) -> ActionResult:
        """按下鼠标按钮不释放（拖拽/游戏/长按）"""
        return self.mouse.mouse_down(x, y, button=button)

    def mouse_up(
        self,
        button: str | MouseButton = MouseButton.LEFT,
        x: int | None = None,
        y: int | None = None,
    ) -> ActionResult:
        """释放鼠标按钮"""
        return self.mouse.mouse_up(x, y, button=button)

    # ==================== 滚动操作 ====================

    def scroll(
        self,
        direction: str | ScrollDirection,
        amount: int = 3,
        x: int | None = None,
        y: int | None = None,
        modifiers: list[str] | tuple[str, ...] | None = None,
    ) -> ActionResult:
        """
        滚动

        Args:
            direction: 方向 (up, down, left, right)
            amount: 滚动量
            x, y: 滚动位置
            modifiers: 按住修饰键滚动（ctrl=缩放）

        Returns:
            ActionResult
        """
        direction = ScrollDirection(direction) if isinstance(direction, str) else direction

        if direction == ScrollDirection.UP:
            return self.mouse.scroll(abs(amount), x, y, modifiers=modifiers)
        elif direction == ScrollDirection.DOWN:
            return self.mouse.scroll(-abs(amount), x, y, modifiers=modifiers)
        elif direction in (ScrollDirection.LEFT, ScrollDirection.RIGHT):
            clicks = -amount if direction == ScrollDirection.LEFT else amount
            return self.mouse.hscroll(clicks, x, y)

        return ActionResult(success=False, action="scroll", error="Invalid direction")

    # ==================== 鼠标+键盘协同宏（核心组合执行引擎） ====================

    # 宏允许的步骤工具白名单（与 tools.py desktop_macro 的 input_schema 保持一致）
    _MACRO_ALLOWED_TOOLS = frozenset(
        {
            "desktop_mouse",
            "desktop_key",
            "desktop_click",
            "desktop_type",
            "desktop_press",
            "desktop_hotkey",
            "desktop_scroll",
            "desktop_wait",
        }
    )

    def macro(
        self,
        steps: list[dict],
        *,
        repeat: int = 1,
        interval_ms: int = 0,
        stop_on_error: bool = True,
        release_at_end: bool = True,
        focus_window: str | None = None,
        focus_delay_ms: int = 400,
        default_step_delay_ms: int = 120,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> dict:
        """鼠标+键盘协同宏：核心组合执行引擎（全工作区可用的底层方法）。

        按顺序执行一组桌面步骤（type / hotkey / press / click / mouse / key /
        scroll / wait），支持重复、步间延迟、出错策略与结束兜底释放，
        供 desktop_macro 工具、API、CLI 及任何调用方复用。

        Args:
            steps: 步骤列表，每项 {"tool", "params", "delay_ms"(可选)}，
                tool 白名单见 _MACRO_ALLOWED_TOOLS，params 与对应工具参数一致
            repeat: 重复轮数（1~20）
            interval_ms: 每轮之间的等待毫秒（0~5000）
            stop_on_error: 出错是否中止（默认 True）
            release_at_end: 结束时释放所有按键/鼠标键（默认 True，防卡键）
            focus_window: 执行前先激活的窗口标题（模糊匹配）；为空则直接执行，
                调用方应自行确保目标窗口已聚焦（未聚焦时 type 可能落空）
            focus_delay_ms: 激活窗口后的焦点沉降等待毫秒（默认 400；新启动的窗口
                初始化较慢，可调大）
            default_step_delay_ms: 未显式给 delay_ms 的步骤的默认步间延迟毫秒
                （默认 120；Windows 下紧随 SendInput 注入键后的 WM_CHAR 突发
                可能被窗口丢弃，小步间延迟可显著提高组合输入可靠性；显式
                delay_ms=0 表示立即执行）
            sleep_fn: 休眠函数（默认 time.sleep；测试可注入替身避免真实等待）

        Returns:
            {"success", "rounds", "steps_completed", "results"}
            results 每项 {"round", "step", "tool", "success", "message|error"}
        """
        if not isinstance(steps, list) or not steps:
            return {"error": "desktop_macro requires a non-empty 'steps' array."}
        if len(steps) > 50:
            return {"error": "desktop_macro supports at most 50 steps per call."}

        try:
            repeat = max(1, min(int(repeat or 1), 20))
        except (TypeError, ValueError):
            repeat = 1
        try:
            interval_ms = max(0, min(int(interval_ms or 0), 5000))
        except (TypeError, ValueError):
            interval_ms = 0
        try:
            focus_delay_ms = max(0, min(int(focus_delay_ms or 0), 5000))
        except (TypeError, ValueError):
            focus_delay_ms = 400

        results: list[dict] = []
        success = True
        aborted = False

        # 可选：先激活目标窗口，避免「组合开始时焦点未就绪导致 type 落空」
        if focus_window:
            activation = self.switch_to_window(focus_window)
            if not activation.success:
                return {
                    "success": False,
                    "rounds": repeat,
                    "steps_completed": 0,
                    "results": [
                        {
                            "round": 0,
                            "step": 0,
                            "tool": "desktop_focus",
                            "success": False,
                            "error": f"focus_window activation failed: {activation.error or 'window not found'}",
                        }
                    ],
                }
            results.append(
                {
                    "round": 0,
                    "step": 0,
                    "tool": "desktop_focus",
                    "success": True,
                    "message": f"Focused window '{focus_window}'",
                }
            )
            if focus_delay_ms:
                sleep_fn(focus_delay_ms / 1000)

            # 物理点击标题栏，确保真实前台：程序化激活（SetForegroundWindow 系列）
            # 可能只改变 Z 序而未转移键盘焦点，导致紧随其后的 SendInput 注入
            # （hotkey/press/click）被路由到错误窗口。标题栏单击强制真实前台。
            try:
                target = self.uia.find_window_fuzzy(focus_window, timeout=1.0)
                if target is not None:
                    rect = target.rectangle()
                    if rect is not None and rect.width() > 0 and rect.height() > 0:
                        title_x = rect.left + rect.width() // 2
                        title_y = rect.top + min(24, max(10, rect.height() // 12))
                        self.mouse.move_to(title_x, title_y)
                        sleep_fn(0.05)
                        self.mouse.click(title_x, title_y)
                        sleep_fn(0.08)
            except Exception:  # noqa: BLE001 - 激活加固失败不应中止宏
                logger.debug("Macro title-bar activation fallback failed", exc_info=True)

        try:
            for round_index in range(repeat):
                for step_index, step in enumerate(steps):
                    if not isinstance(step, dict):
                        results.append(
                            {"round": round_index, "step": step_index, "error": "step must be an object"}
                        )
                        success = False
                        if stop_on_error:
                            aborted = True
                            break
                        continue

                    tool = str(step.get("tool") or "").strip()
                    step_params = step.get("params") or {}
                    if tool not in self._MACRO_ALLOWED_TOOLS:
                        results.append(
                            {
                                "round": round_index,
                                "step": step_index,
                                "error": f"Tool '{tool}' not allowed in macro.",
                            }
                        )
                        success = False
                        if stop_on_error:
                            aborted = True
                            break
                        continue

                    try:
                        outcome = self._run_combo_step(tool, step_params, sleep_fn)
                        failed = isinstance(outcome, dict) and (
                            bool(outcome.get("error")) or outcome.get("success") is False
                        )
                        results.append(
                            {
                                "round": round_index,
                                "step": step_index,
                                "tool": tool,
                                "success": not failed,
                                "message": (
                                    outcome.get("error")
                                    if isinstance(outcome, dict) and outcome.get("error")
                                    else (outcome.get("message") if isinstance(outcome, dict) else str(outcome))
                                ),
                            }
                        )
                        if failed:
                            success = False
                            if stop_on_error:
                                aborted = True
                                break
                    except Exception as e:  # noqa: BLE001 - 单步失败不炸整个宏
                        results.append(
                            {
                                "round": round_index,
                                "step": step_index,
                                "tool": tool,
                                "error": str(e),
                            }
                        )
                        success = False
                        if stop_on_error:
                            aborted = True
                            break

                    try:
                        # 未显式指定 delay_ms 的步骤使用引擎默认步间延迟；
                        # 显式 delay_ms（含 0）尊重调用方意图
                        step_delay = step.get("delay_ms", default_step_delay_ms)
                        if step_delay is None:
                            step_delay = default_step_delay_ms
                        delay_ms = max(0, min(int(step_delay), 5000))
                    except (TypeError, ValueError):
                        delay_ms = default_step_delay_ms
                    if delay_ms:
                        sleep_fn(delay_ms / 1000)

                if aborted:
                    break
                if interval_ms and round_index < repeat - 1:
                    sleep_fn(interval_ms / 1000)
        finally:
            if release_at_end:
                # 异常/中止时也要释放，避免按键或鼠标键卡住
                try:
                    self.release_all_keys()
                except Exception:  # noqa: BLE001
                    pass
                for mouse_button in ("left", "right", "middle"):
                    try:
                        self.mouse_up(mouse_button)
                    except Exception:  # noqa: BLE001
                        pass

        return {
            "success": success,
            "rounds": repeat,
            "steps_completed": len(results),
            "results": results,
        }

    def _run_combo_step(
        self,
        tool: str,
        params: dict,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> dict:
        """执行宏中的单步（工具名 + 参数 → 控制器原语），与 tools.py 单工具处理器同语义。"""
        if tool == "desktop_mouse":
            return self._combo_mouse_action(params)
        if tool == "desktop_key":
            return self._combo_key_action(params)
        if tool == "desktop_click":
            x, y = params.get("x"), params.get("y")
            button = str(params.get("button") or "left")
            modifiers = params.get("modifiers") or None
            try:
                clicks = max(1, min(int(params.get("clicks", 1) or 1), 10))
            except (TypeError, ValueError):
                clicks = 1
            return self.mouse.click(
                int(x) if x is not None else None,
                int(y) if y is not None else None,
                button=button,
                clicks=clicks,
                modifiers=modifiers,
            ).to_dict()
        if tool == "desktop_type":
            text = str(params.get("text") or "")
            method = str(params.get("method") or "auto")
            clear_first = bool(params.get("clear_first", False))
            return self.type_text(text, clear_first=clear_first, method=method).to_dict()
        if tool == "desktop_press":
            key = str(params.get("key") or "")
            if not key:
                return {"error": "press requires key"}
            try:
                times = max(1, min(int(params.get("times", 1) or 1), 20))
            except (TypeError, ValueError):
                times = 1
            return self.press(key, times=times).to_dict()
        if tool == "desktop_hotkey":
            keys = params.get("keys") or []
            return self.hotkey(*[str(k) for k in keys]).to_dict()
        if tool == "desktop_scroll":
            return self.scroll(
                direction=params.get("direction", "down"),
                amount=int(params.get("amount", 3) or 3),
                x=int(params["x"]) if params.get("x") is not None else None,
                y=int(params["y"]) if params.get("y") is not None else None,
                modifiers=params.get("modifiers") or None,
            ).to_dict()
        if tool == "desktop_wait":
            try:
                ms = max(0, min(int(params.get("ms", 300) or 300), 5000))
            except (TypeError, ValueError):
                ms = 300
            sleep_fn(ms / 1000)
            return {"success": True, "message": f"Waited {ms} ms"}
        return {"error": f"Tool '{tool}' not allowed in macro."}

    def _combo_mouse_action(self, params: dict) -> dict:
        """宏内 desktop_mouse 分发（与 tools.py _handle_mouse 同语义，直连控制器原语）。"""
        action = str(params.get("action") or "").lower()
        button = str(params.get("button") or "left")
        modifiers = params.get("modifiers") or None
        x, y = params.get("x"), params.get("y")

        def _int(value) -> int:
            return int(value)

        try:
            if action == "position":
                pos = self.mouse_position()
                size = self.mouse.get_screen_size()
                return {
                    "success": True,
                    "action": "position",
                    "position": [int(pos[0]), int(pos[1])],
                    "screen_size": [int(size[0]), int(size[1])],
                    "message": f"Mouse at ({pos[0]}, {pos[1]}), screen {size[0]}x{size[1]}",
                }
            if action == "move":
                if x is None or y is None:
                    return {"error": "move requires x and y"}
                return self.mouse.move_to(
                    _int(x), _int(y), duration=params.get("duration")
                ).to_dict()
            if action == "move_relative":
                return self.mouse.move_relative(
                    _int(params.get("dx", 0)),
                    _int(params.get("dy", 0)),
                    duration=params.get("duration"),
                    raw=bool(params.get("raw", False)),
                ).to_dict()
            if action == "hover":
                if x is None or y is None:
                    return {"error": "hover requires x and y"}
                return self.mouse.hover(
                    _int(x), _int(y), pause=float(params.get("pause", 0.3))
                ).to_dict()
            if action == "drag":
                to_x, to_y = params.get("to_x"), params.get("to_y")
                if None in (x, y, to_x, to_y):
                    return {"error": "drag requires x, y, to_x, to_y"}
                return self.drag(
                    _int(x),
                    _int(y),
                    _int(to_x),
                    _int(to_y),
                    duration=float(params.get("duration", 0.5)),
                    button=button,
                    modifiers=modifiers,
                ).to_dict()
            if action in ("click", "double_click", "right_click", "middle_click"):
                pos: tuple[int, int] | None = None
                if x is not None and y is not None:
                    pos = (_int(x), _int(y))
                elif action in ("click", "double_click") and params.get("target"):
                    resolved = self.mouse._resolve_target(params["target"])
                    pos = (int(resolved[0]), int(resolved[1]))
                if action == "right_click":
                    button = "right"
                elif action == "middle_click":
                    button = "middle"
                clicks = 2 if action == "double_click" else 1
                return self.mouse.click(
                    pos[0] if pos else None,
                    pos[1] if pos else None,
                    button=button,
                    clicks=clicks,
                    modifiers=modifiers,
                ).to_dict()
            if action in ("down", "up"):
                if action == "down":
                    return self.mouse_down(
                        button=button,
                        x=_int(x) if x is not None else None,
                        y=_int(y) if y is not None else None,
                    ).to_dict()
                return self.mouse_up(
                    button=button,
                    x=_int(x) if x is not None else None,
                    y=_int(y) if y is not None else None,
                ).to_dict()
            if action == "scroll":
                return self.scroll(
                    direction=params.get("direction", "down"),
                    amount=int(params.get("amount", 3)),
                    x=_int(x) if x is not None else None,
                    y=_int(y) if y is not None else None,
                    modifiers=modifiers,
                ).to_dict()
            return {"error": f"Unknown mouse action: {action}"}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def _combo_key_action(self, params: dict) -> dict:
        """宏内 desktop_key 分发（与 tools.py _handle_key 同语义，直连控制器原语）。"""
        action = str(params.get("action") or "").lower()
        key = str(params.get("key") or "").strip()
        text = params.get("text", "")
        keys = params.get("keys") or []
        try:
            if action == "press":
                if not key:
                    return {"error": "press requires key"}
                return self.press(key).to_dict()
            if action == "down":
                if not key:
                    return {"error": "down requires key"}
                return self.key_down(key).to_dict()
            if action == "up":
                if not key:
                    return {"error": "up requires key"}
                return self.key_up(key).to_dict()
            if action == "release_all":
                return self.release_all_keys().to_dict()
            if action == "type":
                return self.type_text(
                    str(text), method=str(params.get("method") or "auto")
                ).to_dict()
            if action == "hotkey":
                return self.hotkey(*[str(k) for k in keys]).to_dict()
            return {"error": f"Unknown key action: {action}"}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    # ==================== 窗口管理 ====================

    def list_windows(
        self,
        visible_only: bool = True,
    ) -> list[WindowInfo]:
        """列出所有窗口"""
        return self.uia.list_windows(visible_only=visible_only)

    def get_active_window(self) -> WindowInfo | None:
        """获取当前活动窗口"""
        window = self.uia.get_active_window()
        if window:
            return window.to_window_info()
        return None

    def switch_to_window(self, title: str) -> ActionResult:
        """
        切换到指定窗口

        Args:
            title: 窗口标题（模糊匹配）

        Returns:
            ActionResult
        """
        start_time = time.time()

        window = self.uia.find_window_fuzzy(title, timeout=3.0)
        if not window:
            return ActionResult(
                success=False,
                action="switch_window",
                target=title,
                error=f"Window not found: {title}",
                duration_ms=(time.time() - start_time) * 1000,
            )

        success = self.uia.activate_window(window)
        return ActionResult(
            success=success,
            action="switch_window",
            target=title,
            message=f"Switched to window: {window.name}" if success else "",
            error="" if success else "Failed to activate window",
            duration_ms=(time.time() - start_time) * 1000,
        )

    def window_action(
        self,
        action: str | WindowAction,
        title: str | None = None,
        handle: int | None = None,
    ) -> ActionResult:
        """
        窗口操作

        Args:
            action: 操作类型
            title: 窗口标题（模糊匹配）
            handle: 窗口句柄（优先于 title，适合重名窗口）

        Returns:
            ActionResult
        """
        action = WindowAction(action) if isinstance(action, str) else action
        start_time = time.time()

        if action == WindowAction.LIST:
            windows = self.list_windows()
            return ActionResult(
                success=True,
                action="list_windows",
                message=f"Found {len(windows)} windows",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # 其他操作需要窗口标题或句柄
        if not title and not handle:
            return ActionResult(
                success=False,
                action=action.value,
                error="Window title or handle required",
            )

        target = title or f"handle:{handle}"
        if handle:
            window = self.uia.find_window(handle=int(handle), timeout=3.0)
        else:
            window = self.uia.find_window_fuzzy(title or "", timeout=3.0)
        if not window:
            return ActionResult(
                success=False,
                action=action.value,
                target=target,
                error=f"Window not found: {target}",
                duration_ms=(time.time() - start_time) * 1000,
            )

        success = False
        if action == WindowAction.SWITCH:
            success = self.uia.activate_window(window)
        elif action == WindowAction.MINIMIZE:
            success = self.uia.minimize_window(window)
        elif action == WindowAction.MAXIMIZE:
            success = self.uia.maximize_window(window)
        elif action == WindowAction.RESTORE:
            success = self.uia.restore_window(window)
        elif action == WindowAction.CLOSE:
            success = self.uia.close_window(window)

        return ActionResult(
            success=success,
            action=action.value,
            target=target,
            message=f"{action.value} window: {window.name}" if success else "",
            error="" if success else f"Failed to {action.value} window",
            duration_ms=(time.time() - start_time) * 1000,
        )

    # ==================== 等待功能 ====================

    async def wait_for_element(
        self,
        target: str,
        timeout: float = 10,
        interval: float = 0.5,
        method: str | FindMethod = FindMethod.AUTO,
    ) -> UIElement | None:
        """
        等待元素出现

        Args:
            target: 元素描述
            timeout: 超时时间
            interval: 检查间隔
            method: 查找方法

        Returns:
            找到的元素，超时返回 None
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            element = await self.find_element(target, method=method, timeout=interval)
            if element:
                return element
            await asyncio.sleep(interval)

        return None

    async def wait_for_window(
        self,
        title: str,
        timeout: float = 10,
        interval: float = 0.5,
    ) -> bool:
        """
        等待窗口出现

        Args:
            title: 窗口标题
            timeout: 超时时间
            interval: 检查间隔

        Returns:
            是否找到窗口
        """
        window = self.uia.wait_for_window(
            title_re=f".*{title}.*",
            timeout=timeout,
            interval=interval,
        )
        return window is not None

    # ==================== 检查功能 ====================

    def inspect(
        self,
        window_title: str | None = None,
        depth: int = 2,
    ) -> dict:
        """
        检查窗口的 UI 元素树

        Args:
            window_title: 窗口标题，None 使用活动窗口
            depth: 遍历深度

        Returns:
            元素树字典
        """
        root = None
        if window_title:
            root = self.uia.find_window_fuzzy(window_title, timeout=2.0)

        return self.inspector.get_element_tree(root, depth=depth)

    def inspect_text(
        self,
        window_title: str | None = None,
        depth: int = 2,
    ) -> str:
        """
        检查窗口的 UI 元素树（文本格式）

        Args:
            window_title: 窗口标题
            depth: 遍历深度

        Returns:
            格式化的树文本
        """
        root = None
        if window_title:
            root = self.uia.find_window_fuzzy(window_title, timeout=2.0)

        return self.inspector.print_element_tree(root, depth=depth)

    # ==================== 视觉分析 ====================

    async def screenshot_url(self, filepath: str) -> str | None:
        """Get a file URL for a saved file via the local API server.

        Returns the absolute file path as-is if the API server is not running.
        Falls back to the local API server's file serve endpoint.
        """
        try:
            from ...core.settings import settings

            base_url = getattr(settings, "serve_url", None)
            if not base_url:
                base_url = "http://127.0.0.1:18900"
            base_url = base_url.rstrip("/")
        except Exception:
            base_url = "http://127.0.0.1:18900"

        # Try to serve via the local API server
        try:

            # Resolve absolute path
            from pathlib import Path as _Path

            import httpx

            abs_path = str(_Path(filepath).resolve())
            # Use relative path under workspace
            try:
                from openkitsune.core.working_directory import (
                    session_working_directory,
                )

                ws = session_working_directory(session=None, require_available=False)
                str(_Path(abs_path).relative_to(_Path(ws).resolve()))
            except Exception:
                # If we can't resolve relative to workspace, use absolute
                pass

            url = f"{base_url}/api/files?path={abs_path.replace(chr(92), chr(92) + chr(92))}"
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    return url
        except Exception:
            pass

        return None

    async def analyze_screen(
        self,
        window_title: str | None = None,
        query: str | None = None,
    ) -> dict:
        """
        分析屏幕内容

        Args:
            window_title: 窗口标题
            query: 自定义查询，None 则进行通用分析

        Returns:
            分析结果
        """
        img = self.screenshot(window_title=window_title)
        analysis_img = self.capture.resize_for_analysis(img)

        if query:
            result = await self.vision.answer_question(query, analysis_img)
        else:
            result = await self.vision.analyze_page(analysis_img)

        return {
            "success": result.success,
            "answer": result.answer,
            "elements": [
                {
                    "description": e.description,
                    "center": e.center,
                    "bbox": e.bbox.to_tuple(),
                }
                for e in result.elements
            ],
            "error": result.error,
        }


# 全局实例
_controller: DesktopController | None = None


def get_controller() -> DesktopController:
    """获取全局控制器"""
    global _controller
    if _controller is None:
        _controller = DesktopController()
    return _controller
