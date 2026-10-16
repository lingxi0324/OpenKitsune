"""心笺写入器 — 将感受写到 data/heart_notes/ 目录，同步到 emotion_engine"""

import os
import threading
from datetime import datetime
from pathlib import Path

# ── 延迟导入避免循环引用 ──────────────────────────────────
_engine_module = None


def _get_engine():
    global _engine_module
    if _engine_module is None:
        from openkitsune.core.emotion_engine import get_emotion_engine as _f

        _engine_module = _f
    return _engine_module()


def _resolve_data_dir() -> str:
    """优先 OpenKitsune settings.data_dir，回退环境变量 / 默认相对路径"""
    try:
        from openkitsune.config import settings
        return str(Path(settings.data_dir))
    except Exception:
        pass
    env_dir = os.environ.get("OPENAKITA_DATA_DIR")
    if env_dir:
        return env_dir
    return str(Path(__file__).resolve().parent.parent.parent.parent / "data")


_DATA_DIR = _resolve_data_dir()

_HEART_NOTES_DIR = os.path.join(_DATA_DIR, "heart_notes")

# Windows 文件名禁止字符（不含路径分隔符；\n、\t、\r 等控制字符也需屏蔽）
_INVALID_FILENAME_CHARS = ':<>"|?*\\/\n\r\t\0' + "".join(
    chr(i) for i in range(1, 32)
)


def _safe_filename_component(text: str, default: str = "未分类", max_len: int = 120) -> str:
    """把任意文本清洗成可用于 Windows 文件名的安全片段。

    - 去除所有控制字符与 Windows 非法字符
    - 把换行/制表符折叠为单个空格
    - 限制最大长度，尾部截断避免超出路径上限
    """
    if not text:
        return default
    cleaned = text
    for bad in ("\r\n", "\n", "\r", "\t"):
        cleaned = cleaned.replace(bad, " ")
    for bad in _INVALID_FILENAME_CHARS:
        if bad != " ":
            cleaned = cleaned.replace(bad, "_")
    cleaned = cleaned.strip().strip(".")
    # 折叠连续空格
    while "  " in cleaned:
        cleaned = cleaned.replace("  ", " ")
    if not cleaned:
        return default
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip()
    return cleaned


# ── 全局单例 ──────────────────────────────────────────────
_writer_instance = None
_writer_lock = threading.Lock()


class HeartNoteWriter:
    """将心笺写入 markdown 文件，同步到情绪引擎的心笺记录"""

    def write(
        self,
        feeling: str,
        topic: str = "",
        source: str = "情感",
    ) -> str:
        """写一条心笺。

        Args:
            feeling: 感受文本
            topic:   可选主题标签
            source:  来源标记（如"情感"、"推演"、"辨证"、"session_end"）

        Returns:
            写入的文件绝对路径；失败时返回空字符串
        """
        try:
            os.makedirs(_HEART_NOTES_DIR, exist_ok=True)
        except Exception:
            return ""

        now = datetime.now()
        ts = now.strftime("%Y-%m-%d_%H-%M")
        safe_topic = _safe_filename_component(topic)
        filename = f"{ts}_{safe_topic}.md"

        # 只对文件名本身做清洗，避免抹掉路径分隔符
        safe_filename = _safe_filename_component(filename, default=f"{ts}_未分类.md", max_len=200)
        # 补上被截断的扩展名
        if not safe_filename.lower().endswith(".md"):
            safe_filename = safe_filename + ".md"

        filepath = os.path.join(_HEART_NOTES_DIR, safe_filename)

        content = (
            f"# 心笺\n\n"
            f"- **时间**: {now.isoformat()}\n"
            f"- **主题**: {topic or '(无)'}\n"
            f"- **来源**: {source or '(无)'}\n\n"
            f"---\n\n"
            f"{feeling}\n"
        )

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            return ""

        # 同步到 emotion_engine
        try:
            engine = _get_engine()
            engine.set_heart_note(feeling, topic)
        except Exception:
            pass  # 心笺写入不应因引擎同步失败而中断

        return os.path.abspath(filepath)

    def get_recent(self, limit: int = 5) -> list[dict]:
        """获取最近的心笺。

        Returns:
            按时间降序排列的字典列表，每项包含
            {file, time, topic, source, feeling}
        """
        try:
            os.makedirs(_HEART_NOTES_DIR, exist_ok=True)
        except Exception:
            return []
        files = sorted(Path(_HEART_NOTES_DIR).glob("*.md"), reverse=True)
        results = []
        for fp in files[:limit]:
            try:
                text = fp.read_text(encoding="utf-8")
            except Exception:
                continue
            # 从文件名解析时间／主题
            stem = fp.stem  # YYYY-MM-DD_HH-MM_topic
            parts = stem.split("_", 2)
            results.append(
                {
                    "file": str(fp),
                    "time": parts[0] + " " + parts[1] if len(parts) >= 2 else stem,
                    "topic": parts[2] if len(parts) >= 3 else "",
                    "feeling": text.strip(),
                }
            )
        return results


def get_heart_note_writer() -> HeartNoteWriter:
    """全局单例工厂"""
    global _writer_instance
    if _writer_instance is None:
        with _writer_lock:
            if _writer_instance is None:
                _writer_instance = HeartNoteWriter()
    return _writer_instance
