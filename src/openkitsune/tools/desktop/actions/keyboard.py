"""
Windows 桌面自动化 - 键盘操作模块

基于 PyAutoGUI 封装键盘操作
"""

import ctypes
import logging
import sys
import time
from contextlib import contextmanager, suppress
from ctypes import wintypes

from ..config import get_config
from ..types import ActionResult

# 平台检查
if sys.platform != "win32":
    raise ImportError(
        f"Desktop automation module is Windows-only. Current platform: {sys.platform}"
    )

try:
    import pyautogui
except ImportError:
    from openkitsune.tools._import_helper import import_or_hint

    raise ImportError(import_or_hint("pyautogui"))

logger = logging.getLogger(__name__)

_WM_CHAR = 0x0102
_TEXT_CONTROL_CLASS_HINTS = ("edit", "richedit", "textbox", "text field")

# SendInput 扫描码注入（部分游戏/全屏程序只认扫描码，不认 VK）
_INPUT_KEYBOARD = 1
_KEYEVENTF_EXTENDEDKEY = 0x0001
_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_SCANCODE = 0x0008
_EXTENDED_KEYS = {
    "up",
    "down",
    "left",
    "right",
    "insert",
    "delete",
    "home",
    "end",
    "pageup",
    "pagedown",
    "numlock",
    "printscreen",
    "prtsc",
    "win",
}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUTUNION)]


def _vk_for(key: str) -> int:
    """把按键名映射为 Windows 虚拟键码（复用 pyautogui 的映射表）。"""
    try:
        from pyautogui import _pyautogui_win as _win

        mapping = getattr(_win, "keyboardMapping", {})
        return int(mapping.get(key) or mapping.get(key.upper()) or 0)
    except Exception:
        return 0


def _send_scancode_key(key: str, up: bool = False) -> bool:
    """用 SendInput 发送扫描码按键（游戏/全屏程序兼容性更好）。"""
    vk = _vk_for(key)
    if not vk:
        return False
    try:
        scan = int(ctypes.windll.user32.MapVirtualKeyW(vk, 0))
        if not scan:
            return False
        flags = _KEYEVENTF_SCANCODE | (_KEYEVENTF_KEYUP if up else 0)
        if key in _EXTENDED_KEYS:
            flags |= _KEYEVENTF_EXTENDEDKEY
        event = _INPUT(
            type=_INPUT_KEYBOARD,
            union=_INPUTUNION(ki=_KEYBDINPUT(0, scan, flags, 0, None)),
        )
        return ctypes.windll.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(_INPUT)) == 1
    except Exception:
        return False


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def _focused_control() -> tuple[int, str]:
    """返回前台窗口中拥有焦点的控件 hwnd 与其窗口类名。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow() or 0)
        if not hwnd:
            return 0, ""
        thread_id = int(user32.GetWindowThreadProcessId(hwnd, None) or 0)
        info = _GUITHREADINFO(cbSize=ctypes.sizeof(_GUITHREADINFO))
        if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return 0, ""
        focus = int(info.hwndFocus or hwnd)
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(focus, buf, 256)
        return focus, buf.value
    except Exception:
        return 0, ""


def _is_text_control(class_name: str) -> bool:
    lowered = (class_name or "").lower()
    return any(hint in lowered for hint in _TEXT_CONTROL_CLASS_HINTS)


def _post_space_to_focus() -> bool:
    """直接向焦点控件投递 WM_CHAR 空格字符。

    中文输入法会吞掉 VK_SPACE（当作候选词上屏键），但 WM_CHAR 绕过输入法，
    在 Edit/RichEdit 等文本控件中稳定插入半角空格。
    """
    focus, class_name = _focused_control()
    if not focus or not _is_text_control(class_name):
        return False
    try:
        return bool(ctypes.windll.user32.PostMessageW(focus, _WM_CHAR, 0x20, 0x00000001))
    except Exception:
        return False


def _select_all_in_focus() -> bool:
    """用 EM_SETSEL 选中焦点文本控件的全部内容（绕过输入法对 Ctrl+A 的干扰）。"""
    focus, class_name = _focused_control()
    if not focus or not _is_text_control(class_name):
        return False
    try:
        EM_SETSEL = 0x00B1
        ctypes.windll.user32.SendMessageW(focus, EM_SETSEL, 0, -1)
        return True
    except Exception:
        return False


def _post_text_to_focus(text: str) -> bool:
    """向焦点文本控件逐字符投递 WM_CHAR（绕过输入法，支持 Unicode）。

    中文输入法会把合成按键改写成候选汉字或吞掉空格；WM_CHAR 直接给控件
    送字符码，不经过输入法，对 Win32 / WinForms / WPF 的文本控件稳定。
    """
    focus, class_name = _focused_control()
    if not focus or not _is_text_control(class_name):
        return False

    user32 = ctypes.windll.user32
    try:
        for ch in text:
            if ch == "\n":
                ch = "\r"
            # 非 BMP 字符按 UTF-16 代理对逐个投递
            units = ch.encode("utf-16-le")
            for i in range(0, len(units), 2):
                code_unit = int.from_bytes(units[i:i + 2], "little")
                if not user32.PostMessageW(focus, _WM_CHAR, code_unit, 0x00000001):
                    return False
            time.sleep(0.002)
        return True
    except Exception:
        return False


@contextmanager
def ime_closed():
    """临时关闭前台窗口的输入法（IME），避免合成按键被输入法拦截。

    中文输入法激活时，空格可能被当作候选词上屏键，字母会被替换成候选汉字
    （例如 typewrite("a b") 变成「啊吧」）。在发送真实按键前关闭 IME，
    发送后恢复原状态，可显著提升自动化输入的确定性。
    """
    hwnd = 0
    himc = 0
    opened = False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        imm32 = ctypes.windll.imm32
        hwnd = int(user32.GetForegroundWindow() or 0)
        if hwnd:
            himc = int(imm32.ImmGetContext(hwnd) or 0)
            if himc:
                opened = bool(imm32.ImmGetOpenStatus(himc))
                if opened:
                    imm32.ImmSetOpenStatus(himc, False)
    except Exception as e:  # pragma: no cover - 非关键路径
        logger.debug(f"IME detach failed: {e}")

    try:
        yield
    finally:
        try:
            if himc:
                if opened:
                    ctypes.windll.imm32.ImmSetOpenStatus(himc, True)
                ctypes.windll.imm32.ImmReleaseContext(hwnd, himc)
        except Exception:
            pass


# 常用按键别名映射
KEY_ALIASES = {
    # 功能键
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "escape": "escape",
    "esc": "escape",
    "space": "space",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "insert": "insert",
    "ins": "insert",
    # 修饰键
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "win": "win",
    "windows": "win",
    "cmd": "win",
    "command": "win",
    # 方向键
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "pgup": "pageup",
    "pgdn": "pagedown",
    "home": "home",
    "end": "end",
    # 功能键 F1-F12
    **{f"f{i}": f"f{i}" for i in range(1, 13)},
    # 其他
    "printscreen": "printscreen",
    "prtsc": "printscreen",
    "scrolllock": "scrolllock",
    "pause": "pause",
    "capslock": "capslock",
    "numlock": "numlock",
}


class KeyboardController:
    """
    键盘控制器

    封装 PyAutoGUI 的键盘操作，提供更友好的接口
    """

    def __init__(self):
        self._configure_pyautogui()
        self._held_keys: list[str] = []  # 当前按住的键

    def _configure_pyautogui(self) -> None:
        """配置 PyAutoGUI"""
        config = get_config().actions
        pyautogui.FAILSAFE = config.failsafe
        pyautogui.PAUSE = config.pause_between_actions

    def _normalize_key(self, key: str) -> str:
        """
        标准化按键名称

        Args:
            key: 按键名称

        Returns:
            标准化后的按键名称
        """
        key_lower = key.lower().strip()
        return KEY_ALIASES.get(key_lower, key_lower)

    def type_text(
        self,
        text: str,
        interval: float | None = None,
        method: str = "auto",
    ) -> ActionResult:
        """
        输入文本

        默认走剪贴板粘贴（method="auto"）：在中文输入法（IME）激活时，
        pyautogui.typewrite 发送的按键会被输入法拦截/转换成候选词，
        导致 ASCII 文本被改写、空格被吞掉。剪贴板粘贴不经过 IME，可靠且支持中文。

        Args:
            text: 要输入的文本
            interval: 字符间隔，None 使用配置（仅 method="type" 时生效）
            method: auto / paste / type
                - auto: 优先剪贴板，失败时退回按键输入
                - paste: 只用剪贴板
                - type: 只用按键输入（不经过剪贴板）

        Returns:
            ActionResult
        """
        config = get_config().actions
        int_val = interval if interval is not None else config.type_interval
        mode = (method or "auto").lower()

        start_time = time.time()
        try:
            # 文本控件：直接投递 WM_CHAR，绕过输入法（最可靠）
            if mode == "auto" and text and _post_text_to_focus(text):
                return ActionResult(
                    success=True,
                    action="type",
                    target=text,
                    message=f"Typed {len(text)} characters (WM_CHAR, IME-safe)",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            if mode == "type":
                with ime_closed():
                    pyautogui.typewrite(text, interval=int_val)
                return ActionResult(
                    success=True,
                    action="type",
                    target=text,
                    message=f"Typed {len(text)} characters",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            result = self._type_via_clipboard(text)
            if result.success or mode == "paste":
                return result

            # auto 模式下剪贴板失败 → 退回按键输入
            logger.warning("Clipboard paste failed, falling back to keystrokes: %s", result.error)
            with ime_closed():
                pyautogui.typewrite(text, interval=int_val)
            return ActionResult(
                success=True,
                action="type",
                target=text,
                message=f"Typed {len(text)} characters (keystroke fallback)",
                duration_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            logger.error(f"Failed to type text: {e}")
            return ActionResult(
                success=False,
                action="type",
                target=text,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _type_via_clipboard(self, text: str) -> ActionResult:
        """
        通过剪贴板输入文本（支持中文）

        Args:
            text: 要输入的文本

        Returns:
            ActionResult
        """
        import pyperclip

        start_time = time.time()
        try:
            # 保存原有剪贴板内容
            original_clipboard = ""
            with suppress(Exception):
                original_clipboard = pyperclip.paste()

            # 复制文本到剪贴板
            pyperclip.copy(text)

            # 粘贴
            with ime_closed():
                pyautogui.hotkey("ctrl", "v")

            # 等待目标应用真正处理完粘贴，再恢复剪贴板；
            # 过早恢复会让目标读到旧剪贴板内容（表现为“粘贴没生效”）。
            time.sleep(0.4)
            with suppress(Exception):
                if pyperclip.paste() == text:
                    pyperclip.copy(original_clipboard)

            return ActionResult(
                success=True,
                action="type",
                target=text,
                message=f"Typed {len(text)} characters via clipboard",
                duration_ms=(time.time() - start_time) * 1000,
            )

        except ImportError:
            # 如果没有 pyperclip，尝试使用 Windows 原生方式
            logger.warning("pyperclip not available, trying native Windows clipboard")
            return self._type_via_win_clipboard(text)
        except Exception as e:
            logger.error(f"Failed to type via clipboard: {e}")
            return ActionResult(
                success=False,
                action="type",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def _type_via_win_clipboard(self, text: str) -> ActionResult:
        """
        使用 Windows 原生剪贴板输入文本

        Args:
            text: 要输入的文本

        Returns:
            ActionResult
        """
        import ctypes

        start_time = time.time()
        try:
            # Windows API 常量
            CF_UNICODETEXT = 13
            GHND = 0x0042

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # 打开剪贴板
            if not user32.OpenClipboard(None):
                raise Exception("Failed to open clipboard")

            try:
                # 清空剪贴板
                user32.EmptyClipboard()

                # 准备文本数据
                text_bytes = text.encode("utf-16-le") + b"\x00\x00"

                # 分配全局内存
                h_mem = kernel32.GlobalAlloc(GHND, len(text_bytes))
                if not h_mem:
                    raise Exception("Failed to allocate memory")

                # 锁定内存并复制数据
                p_mem = kernel32.GlobalLock(h_mem)
                if not p_mem:
                    kernel32.GlobalFree(h_mem)
                    raise Exception("Failed to lock memory")

                ctypes.memmove(p_mem, text_bytes, len(text_bytes))
                kernel32.GlobalUnlock(h_mem)

                # 设置剪贴板数据
                user32.SetClipboardData(CF_UNICODETEXT, h_mem)

            finally:
                # 关闭剪贴板
                user32.CloseClipboard()

            # 粘贴
            with ime_closed():
                pyautogui.hotkey("ctrl", "v")

            return ActionResult(
                success=True,
                action="type",
                target=text,
                message=f"Typed {len(text)} characters via Windows clipboard",
                duration_ms=(time.time() - start_time) * 1000,
            )

        except Exception as e:
            logger.error(f"Failed to type via Windows clipboard: {e}")
            return ActionResult(
                success=False,
                action="type",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def press(self, key: str) -> ActionResult:
        """
        按下并释放按键

        Args:
            key: 按键名称

        Returns:
            ActionResult
        """
        key = self._normalize_key(key)

        start_time = time.time()
        try:
            # 空格：中文输入法会吞掉 VK_SPACE，文本控件改用 WM_CHAR 直投
            if key == "space" and _post_space_to_focus():
                return ActionResult(
                    success=True,
                    action="press",
                    target=key,
                    message="Pressed space (WM_CHAR, IME-safe)",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            with ime_closed():
                if not (_send_scancode_key(key, False) and _send_scancode_key(key, True)):
                    pyautogui.press(key)
            return ActionResult(
                success=True,
                action="press",
                target=key,
                message=f"Pressed {key}",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"Failed to press {key}: {e}")
            return ActionResult(
                success=False,
                action="press",
                target=key,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def press_multiple(
        self,
        key: str,
        presses: int = 1,
        interval: float = 0.1,
    ) -> ActionResult:
        """
        多次按下按键

        Args:
            key: 按键名称
            presses: 按下次数
            interval: 按键间隔

        Returns:
            ActionResult
        """
        key = self._normalize_key(key)

        if key == "space" or presses > 1:
            last = ActionResult(
                success=True, action="press", target=key, message=f"Pressed {key} 0 times"
            )
            for _ in range(max(1, int(presses))):
                last = self.press(key)
                if not last.success:
                    break
                time.sleep(interval)
            return last

        start_time = time.time()
        try:
            with ime_closed():
                if not (_send_scancode_key(key, False) and _send_scancode_key(key, True)):
                    pyautogui.press(key, presses=presses, interval=interval)
            return ActionResult(
                success=True,
                action="press",
                target=key,
                message=f"Pressed {key} {presses} times",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"Failed to press {key}: {e}")
            return ActionResult(
                success=False,
                action="press",
                target=key,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def hotkey(self, *keys: str) -> ActionResult:
        """
        执行快捷键组合

        Args:
            *keys: 按键名称列表，如 hotkey("ctrl", "c")

        Returns:
            ActionResult
        """
        normalized_keys = [self._normalize_key(k) for k in keys]
        key_combo = "+".join(normalized_keys)

        start_time = time.time()
        try:
            with ime_closed():
                sent = all(_send_scancode_key(k, False) for k in normalized_keys)
                for k in reversed(normalized_keys):
                    _send_scancode_key(k, True)
                if not sent:
                    pyautogui.hotkey(*normalized_keys)
            return ActionResult(
                success=True,
                action="hotkey",
                target=key_combo,
                message=f"Pressed hotkey {key_combo}",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"Failed to press hotkey {key_combo}: {e}")
            return ActionResult(
                success=False,
                action="hotkey",
                target=key_combo,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def key_down(self, key: str) -> ActionResult:
        """
        按下按键（不释放）

        Args:
            key: 按键名称

        Returns:
            ActionResult
        """
        key = self._normalize_key(key)

        start_time = time.time()
        try:
            if not _send_scancode_key(key, False):
                pyautogui.keyDown(key)
            self._held_keys.append(key)
            return ActionResult(
                success=True,
                action="key_down",
                target=key,
                message=f"Key {key} down",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"Failed to press down {key}: {e}")
            return ActionResult(
                success=False,
                action="key_down",
                target=key,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    def key_up(self, key: str) -> ActionResult:
        """
        释放按键

        Args:
            key: 按键名称

        Returns:
            ActionResult
        """
        key = self._normalize_key(key)

        start_time = time.time()
        try:
            if not _send_scancode_key(key, True):
                pyautogui.keyUp(key)
            if key in self._held_keys:
                self._held_keys.remove(key)
            return ActionResult(
                success=True,
                action="key_up",
                target=key,
                message=f"Key {key} up",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"Failed to release {key}: {e}")
            return ActionResult(
                success=False,
                action="key_up",
                target=key,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    @contextmanager
    def hold(self, *keys: str):
        """
        按住按键的上下文管理器

        用法:
            with keyboard.hold("ctrl", "shift"):
                keyboard.press("n")

        Args:
            *keys: 要按住的按键
        """
        normalized_keys = [self._normalize_key(k) for k in keys]

        try:
            # 按下所有键
            for key in normalized_keys:
                self.key_down(key)
            yield
        finally:
            # 释放所有键（逆序）
            for key in reversed(normalized_keys):
                self.key_up(key)

    def release_all(self) -> ActionResult:
        """
        释放所有按住的按键

        Returns:
            ActionResult
        """
        start_time = time.time()
        released = []

        try:
            for key in self._held_keys[:]:  # 使用副本遍历
                self.key_up(key)
                released.append(key)

            return ActionResult(
                success=True,
                action="release_all",
                message=f"Released keys: {released}" if released else "No keys to release",
                duration_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.error(f"Failed to release keys: {e}")
            return ActionResult(
                success=False,
                action="release_all",
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000,
            )

    # 便捷方法
    def copy(self) -> ActionResult:
        """Ctrl+C 复制"""
        return self.hotkey("ctrl", "c")

    def paste(self) -> ActionResult:
        """Ctrl+V 粘贴"""
        return self.hotkey("ctrl", "v")

    def cut(self) -> ActionResult:
        """Ctrl+X 剪切"""
        return self.hotkey("ctrl", "x")

    def undo(self) -> ActionResult:
        """Ctrl+Z 撤销"""
        return self.hotkey("ctrl", "z")

    def redo(self) -> ActionResult:
        """Ctrl+Y 重做"""
        return self.hotkey("ctrl", "y")

    def select_all(self) -> ActionResult:
        """Ctrl+A 全选（文本控件优先用 EM_SETSEL，避免输入法拦截）"""
        if _select_all_in_focus():
            return ActionResult(
                success=True,
                action="hotkey",
                target="ctrl+a",
                message="Selected all (EM_SETSEL)",
            )
        return self.hotkey("ctrl", "a")

    def save(self) -> ActionResult:
        """Ctrl+S 保存"""
        return self.hotkey("ctrl", "s")

    def find(self) -> ActionResult:
        """Ctrl+F 查找"""
        return self.hotkey("ctrl", "f")

    def new(self) -> ActionResult:
        """Ctrl+N 新建"""
        return self.hotkey("ctrl", "n")

    def close_window(self) -> ActionResult:
        """Alt+F4 关闭窗口"""
        return self.hotkey("alt", "f4")

    def switch_window(self) -> ActionResult:
        """Alt+Tab 切换窗口"""
        return self.hotkey("alt", "tab")

    def minimize_all(self) -> ActionResult:
        """Win+D 显示桌面"""
        return self.hotkey("win", "d")

    def open_run(self) -> ActionResult:
        """Win+R 打开运行"""
        return self.hotkey("win", "r")

    def open_explorer(self) -> ActionResult:
        """Win+E 打开资源管理器"""
        return self.hotkey("win", "e")

    def screenshot_to_clipboard(self) -> ActionResult:
        """Win+Shift+S 截图到剪贴板"""
        return self.hotkey("win", "shift", "s")


# 全局实例
_keyboard: KeyboardController | None = None


def get_keyboard() -> KeyboardController:
    """获取全局键盘控制器"""
    global _keyboard
    if _keyboard is None:
        _keyboard = KeyboardController()
    return _keyboard
