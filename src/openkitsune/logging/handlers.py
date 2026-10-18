"""
自定义日志处理器

功能:
- ErrorOnlyHandler: 只记录 ERROR/CRITICAL 级别日志
- ColoredFormatter: 段级彩色格式化器（时间/级别/模块名/消息分别着色）
- ColoredConsoleHandler: 彩色控制台输出
- SessionLogHandler: 会话级日志缓存，供 AI 查询
"""

import copy
import logging
import os
import re
import sys
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import TextIO

from .session_buffer import get_session_log_buffer


class ErrorOnlyHandler(TimedRotatingFileHandler):
    """
    只记录 ERROR 和 CRITICAL 级别日志的处理器

    继承 TimedRotatingFileHandler，按天轮转
    """

    def emit(self, record: logging.LogRecord) -> None:
        """只处理 ERROR 及以上级别"""
        if record.levelno >= logging.ERROR:
            super().emit(record)


# ────────────────────────────────────────────────────────────────────────
# ANSI 样式常量（段级配色）
# 配色原则：时间戳/模块名用低饱和色作底，级别与消息用高对比色作焦点，
# 整体克制、对齐工整，长时运行的服务日志读起来不刺眼但层次分明。
# ────────────────────────────────────────────────────────────────────────

_RESET = "\033[0m"

# 时间戳：亮黑（暗灰）
_STYLE_TIMESTAMP = "\033[90m"
# 模块名：青色
_STYLE_NAME = "\033[36m"
# 消息开头的 [标签]（如 [State] / [ReAct-Stream]）：亮品红粗体
_STYLE_TAG = "\033[1;35m"
# 异常堆栈：暗红
_STYLE_EXC = "\033[91m"
# 堆栈信息（stack_info）：暗灰
_STYLE_STACK = "\033[90m"

# 级别标签配色（粗体高对比；CRITICAL 白字红底）
_LEVEL_STYLE = {
    logging.DEBUG: "\033[90m",
    logging.INFO: "\033[1;96m",  # 亮青
    logging.WARNING: "\033[1;93m",  # 亮黄
    logging.ERROR: "\033[1;91m",  # 亮红
    logging.CRITICAL: "\033[1;97;101m",  # 白字红底
}

# 消息配色（按级别）
_MESSAGE_STYLE = {
    logging.DEBUG: "\033[90m",
    logging.INFO: "\033[0m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[91m",
    logging.CRITICAL: "\033[1;91m",
}

# 行首 [标签] 识别（仅匹配消息开头的方括号标签，如 "[State] xxx"）
_TAG_RE = re.compile(r"^(\[[^\]]+\])(\s*)")

# 控制台布局宽度
_LEVEL_WIDTH = 8  # 级别标签定宽（INFO    / WARNING / CRITICAL）
_NAME_WIDTH = 44  # 模块名定宽（超长截断）


class ColoredFormatter(logging.Formatter):
    """
    段级彩色格式化器。

    日志行按 时间戳 / 级别 / 模块名 / 消息 分段着色：

    - 时间戳：暗灰色，带毫秒
    - 级别：按级别着色 + 粗体（CRITICAL 为白字红底），固定 8 字符宽度
    - 模块名：青色，固定 44 字符宽度，超长截断
    - 消息：DEBUG 灰 / INFO 默认 / WARNING 黄 / ERROR 红 / CRITICAL 红加粗；
      消息开头的 [标签] 用亮品红高亮；多行消息每行续色
    - 异常堆栈：暗红色追加在行尾

    兼容性：
    - use_colors=False 时走原生 logging.Formatter（与文件日志完全一致，无 ANSI）
    - 当 log_format 不含四个核心字段（asctime/name/levelname/message）时，
      退化为整行按级别着色，保证自定义格式下功能不降级。
    """

    # 与默认 log_format 同源的控制台布局
    DEFAULT_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    def __init__(
        self,
        fmt: str = DEFAULT_FMT,
        datefmt: str | None = None,
        use_colors: bool = True,
    ) -> None:
        super().__init__(fmt, datefmt)
        self.use_colors = use_colors
        # 是否启用分段着色：四个核心字段齐全时才可安全拆分
        fmt_text = fmt or ""
        self._segmented = all(
            token in fmt_text
            for token in ("%(asctime)s", "%(levelname)s", "%(name)s", "%(message)s")
        )

    @staticmethod
    def _level_style(levelno: int) -> str:
        return _LEVEL_STYLE.get(levelno, _RESET)

    @staticmethod
    def _message_style(levelno: int) -> str:
        return _MESSAGE_STYLE.get(levelno, _RESET)

    def format(self, record: logging.LogRecord) -> str:
        if not self.use_colors:
            return super().format(record)
        if not self._segmented:
            # 自定义格式：整行按级别着色（保留旧行为）
            message = super().format(record)
            return f"{self._message_style(record.levelno)}{message}{_RESET}"
        return self._format_segmented(record)

    def _format_segmented(self, record: logging.LogRecord) -> str:
        # copy 一份，避免污染共享 record（asctime/exc_text 等字段会被缓存复用）
        record = copy.copy(record)
        record.asctime = self.formatTime(record, self.datefmt)  # None → 带毫秒,xxx

        name = record.name or ""
        level = record.levelname or "?"
        message = record.getMessage()

        ts = f"{_STYLE_TIMESTAMP}{record.asctime}{_RESET}"
        lvl = f"{self._level_style(record.levelno)}{level:<{_LEVEL_WIDTH}}{_RESET}"
        nm = f"{_STYLE_NAME}{name:<{_NAME_WIDTH}.{_NAME_WIDTH}}{_RESET}"

        msg_style = self._message_style(record.levelno)
        # 行首 [标签] 高亮；多行消息每行续色
        m = _TAG_RE.match(message)
        if m:
            body = message[m.end() :]
            msg = f"{_STYLE_TAG}{m.group(1)}{msg_style}{m.group(2)}{body}"
        else:
            msg = message
        msg = msg.replace("\n", f"\n{msg_style}")
        msg = f"{msg_style}{msg}{_RESET}"

        line = f"{ts} {lvl} {nm} {msg}"

        # 异常信息（formatException 会产生多行，逐行补色）
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            exc = record.exc_text.replace("\n", f"\n{_STYLE_EXC}")
            line = f"{line}\n{_STYLE_EXC}{exc}{_RESET}"
        # 显式堆栈信息（stack_info）
        if record.stack_info:
            stack = record.stack_info.replace("\n", f"\n{_STYLE_STACK}")
            line = f"{line}\n{_STYLE_STACK}{stack}{_RESET}"

        return line


class ColoredConsoleHandler(logging.StreamHandler):
    """
    彩色控制台日志处理器

    使用 ColoredFormatter 做段级着色：
    时间戳 / 级别 / 模块名 / 消息分别使用不同颜色，醒目且层次分明。

    颜色启用规则（优先级从高到低）:
    1. 环境变量 NO_COLOR 存在 → 强制禁用
    2. 环境变量 OPENKITSUNE_LOG_COLOR=1/on/true/yes → 强制启用（非 tty 也启用）
       OPENKITSUNE_LOG_COLOR=0/off/false/no → 强制禁用
    3. 默认按终端能力自动检测（Windows 下自动启用 ANSI 虚拟终端）

    Windows 特殊处理:
    - 强制使用 UTF-8 编码输出，避免 GBK 编码导致 emoji 等 Unicode 字符
      触发 UnicodeEncodeError，从而中断 SSE 流式输出引发前端白屏。
    """

    def __init__(self, stream: TextIO = None):
        output_stream = stream or sys.stdout
        if output_stream is None or getattr(output_stream, "closed", False):
            # Long-lived stream owned by logging.StreamHandler; a `with` block
            # would close the fd immediately, leaving the handler broken.
            output_stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        # 双保险：即使 _ensure_utf8 已全局 reconfigure stdout，这里仍对 handler 自身
        # 的 stream 做 UTF-8 包装，防止 logging 在 _ensure_utf8 导入之前初始化的极端场景。
        if sys.platform == "win32":
            try:
                if hasattr(output_stream, "reconfigure"):
                    output_stream.reconfigure(
                        encoding="utf-8", errors="replace", line_buffering=True
                    )
            except (OSError, ValueError):
                # pythonw.exe can run with sys.stdout attached to a closed file.
                # In that mode logs still go to file/session handlers; the console
                # handler should become a no-op instead of breaking requests.
                # Long-lived stream owned by logging.StreamHandler (see super().__init__).
                output_stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
        super().__init__(output_stream)
        # 检测是否支持颜色（Windows 需要特殊处理）
        self._supports_color = self._check_color_support()
        # 默认安装段级彩色格式化器；外部可再 setFormatter 覆盖
        self.setFormatter(ColoredFormatter(use_colors=self._supports_color))

    @property
    def supports_color(self) -> bool:
        """当前是否启用颜色（供 setup_logging 决定 formatter 配色）"""
        return self._supports_color

    def _check_color_support(self) -> bool:
        """检测终端是否支持颜色"""
        # 1. NO_COLOR 约定：存在即禁用
        if os.environ.get("NO_COLOR"):
            return False
        # 2. 显式开关：OPENKITSUNE_LOG_COLOR 覆盖自动检测（非 tty 也生效）
        force = os.environ.get("OPENKITSUNE_LOG_COLOR", "").strip().lower()
        if force in {"1", "on", "true", "yes", "y"}:
            return True
        if force in {"0", "off", "false", "no", "n"}:
            return False
        # 3. 自动检测
        if not (hasattr(self.stream, "isatty") and self.stream.isatty()):
            return False
        # 如果是 Windows，尝试启用 ANSI 支持
        if sys.platform == "win32":
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                # 启用虚拟终端处理
                kernel32.SetConsoleMode(
                    kernel32.GetStdHandle(-11),  # STD_OUTPUT_HANDLE
                    7,  # ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                )
                return True
            except Exception:
                return False

        # Unix/Linux/Mac 默认支持
        return hasattr(self.stream, "isatty") and self.stream.isatty()

    def emit(self, record: logging.LogRecord) -> None:
        """输出日志记录，确保 Unicode 字符不会导致异常"""
        try:
            super().emit(record)
        except UnicodeEncodeError:
            # 最后兜底：如果仍然出现编码错误，用 replace 策略重试
            try:
                msg = self.format(record)
                safe_msg = msg.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
                self.stream.write(safe_msg + self.terminator)
                self.stream.flush()
            except Exception:
                pass


class SessionLogHandler(logging.Handler):
    """
    会话日志处理器

    将日志记录到内存缓存中，按 session_id 分组，供 AI 查询当前会话的日志。

    使用方式:
    1. 在日志时通过 extra 传入 session_id:
       logger.info("message", extra={"session_id": "telegram_123_..."})

    2. 或者预先设置当前 session:
       get_session_log_buffer().set_current_session(session_id)
       logger.info("message")  # 自动关联到当前 session
    """

    def __init__(self, level: int = logging.DEBUG):
        """
        初始化会话日志处理器

        Args:
            level: 最低日志级别（默认 DEBUG，记录所有级别）
        """
        super().__init__(level)
        self._buffer = get_session_log_buffer()

    def emit(self, record: logging.LogRecord) -> None:
        """
        处理日志记录

        Args:
            record: 日志记录对象
        """
        try:
            # 尝试从 extra 获取 session_id
            session_id = getattr(record, "session_id", None)

            # 格式化消息
            message = self.format(record) if self.formatter else record.getMessage()

            # 添加到缓存
            self._buffer.add_log(
                level=record.levelname,
                module=record.name,
                message=message,
                session_id=session_id,
                timestamp=datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[
                    :-3
                ],
            )
        except Exception:
            # 日志处理器不应该抛出异常
            self.handleError(record)
