"""将 Markdown / 富文本转成适合朗读的语音脚本（确定性清理，非重写）。

迁移自 hermes-agent ``tools/tts_text_normalize.py``，供 TTS 工具与自动语音输出共用。
"""

from __future__ import annotations

import html
import re

# 标题行尾哨兵：使 smooth_whitespace_for_tts 把标题折叠进其后句子
_HEAD = "\x00"

_MD_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((?:[^()]|\([^)]*\))*\)")
_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\((?:[^()]|\([^)]*\))*\)")
_MD_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", flags=re.DOTALL)
_MD_UNDERSCORE_BOLD_RE = re.compile(r"__(.+?)__", flags=re.DOTALL)
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", flags=re.DOTALL)
_MD_UNDERSCORE_ITALIC_RE = re.compile(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", flags=re.DOTALL)
_MD_STRIKE_RE = re.compile(r"~~(.+?)~~", flags=re.DOTALL)
_MD_HEADING_LINE_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", flags=re.MULTILINE)
_MD_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?", flags=re.MULTILINE)
_MD_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", flags=re.MULTILINE)
_MD_HR_RE = re.compile(r"^\s*[-*_]{3,}\s*$", flags=re.MULTILINE)
_MD_TABLE_PIPE_RE = re.compile(r"\s*\|\s*")
_URL_RE = re.compile(r"https?://\S+")

_DEGREE_UNITS = (("C", "Celsius"), ("F", "Fahrenheit"))
_UNIT_WORDS = (
    (r"km\s*/\s*h", "kilometres per hour"), (r"km/h", "kilometres per hour"),
    (r"mm", "millimetres"), (r"cm", "centimetres"), (r"m", "metres"))
_CURRENCY_WORDS = (
    (r"NZ\$", "New Zealand dollars", re.IGNORECASE), (r"A\$", "Australian dollars", re.IGNORECASE),
    (r"US\$", "US dollars", re.IGNORECASE), ("€", "euros", 0), ("£", "pounds", 0), (r"\$", "dollars", 0),
)

_EMOJI_RE = re.compile(
    "[\U0001F1E6-\U0001F1FF\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF☀-➿]+",
    flags=re.UNICODE)
_VARIATION_SELECTOR_RE = re.compile("[\ufe0e\ufe0f]")


def strip_markdown_for_tts(text: str) -> str:
    """去除 Markdown/Telegram 格式，保留可读词汇。"""
    if not text:
        return ""
    text = html.unescape(str(text))
    text = _MD_CODE_BLOCK_RE.sub(" ", text)
    text = _MD_IMAGE_RE.sub(lambda m: f" {m.group(1)} " if m.group(1) else " ", text)
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _URL_RE.sub("", text)
    text = _MD_INLINE_CODE_RE.sub(r"\1", text)
    text = _MD_BOLD_RE.sub(r"\1", text)
    text = _MD_UNDERSCORE_BOLD_RE.sub(r"\1", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    text = _MD_UNDERSCORE_ITALIC_RE.sub(r"\1", text)
    text = _MD_STRIKE_RE.sub(r"\1", text)
    text = _MD_HEADING_LINE_RE.sub(lambda m: m.group(1).rstrip() + _HEAD, text)
    text = _MD_BLOCKQUOTE_RE.sub("", text)
    text = _MD_LIST_ITEM_RE.sub("", text)
    text = _MD_HR_RE.sub("", text)
    return _MD_TABLE_PIPE_RE.sub("; ", text)


def _normalize_temperature_ranges(text: str) -> str:
    """``11-17°C`` -> ``11 to 17 degrees Celsius``。"""
    number = r"([-+\u2212]?\d+(?:\.\d+)?)"
    for unit, word in _DEGREE_UNITS:
        text = re.sub(
            r"(?<!\w)" + number + r"\s*[\u2013\u2014-]\s*" + number + r"\s*°\s*" + unit + r"\b",
            lambda m, w=word: (
                f"{m.group(1).replace(chr(0x2212), '-')} to {m.group(2).replace(chr(0x2212), '-')} degrees {w}"
            ),
            text, flags=re.IGNORECASE)
    return text


def normalize_symbols_for_tts(text: str) -> str:
    """展开常见符号/缩写为 TTS 引擎读得顺的词语。"""
    if not text:
        return ""
    text = re.sub("[\u00a0\u2007\u202f]", " ", str(text))
    text = text.replace("\u2212", "-").replace("…", "...")
    text = _normalize_temperature_ranges(text)
    for unit, word in _DEGREE_UNITS:
        text = re.sub(
            r"(?<!\w)([-+]?\d+(?:\.\d+)?)\s*°\s*" + unit + r"\b", r"\1 degrees " + word, text, flags=re.IGNORECASE,
        )
    for unit, word in _DEGREE_UNITS:
        text = re.sub(r"°\s*" + unit + r"\b", "degrees " + word, text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\w)([-+]?\d+(?:\.\d+)?)\s*°", r"\1 degrees", text).replace("°", " degrees")
    for pattern, word in _UNIT_WORDS:
        text = re.sub(r"(?<=\d)\s*" + pattern + r"\b", " " + word, text, flags=re.IGNORECASE)
    text = re.sub(r"(?<=\d)\s*/\s*(?=[A-Za-z])", " per ", text)
    for symbol, word, flags in _CURRENCY_WORDS:
        text = re.sub(symbol + r"\s*([\d,]*\d(?:\.\d+)?)", r"\1 " + word, text, flags=flags)
    text = re.sub(r"(?<=\d)\s*%", " percent", text)
    text = re.sub("[•◦▪▫]", " ", text.replace("&", " and "))
    for symbol, word in (("→", " to "), ("⇒", " to "), ("≈", " about "), ("~", " about ")):
        text = text.replace(symbol, word)
    return _EMOJI_RE.sub("", _VARIATION_SELECTOR_RE.sub("", text))


def smooth_whitespace_for_tts(text: str) -> str:
    """把视觉排版压缩成从容的口语句段（标题折叠为引语）。"""
    if not text:
        return ""
    raw_lines = text.splitlines()
    add_sentence_pauses = sum(1 for raw_line in raw_lines if raw_line.replace(_HEAD, "").strip()) > 1
    lines: list[str] = []
    pending_heading: str | None = None

    def flush_pending() -> None:
        nonlocal pending_heading
        if pending_heading is not None:
            lines.append(pending_heading.rstrip(".:;,") + ".")
            pending_heading = None

    for raw_line in raw_lines:
        is_heading = raw_line.rstrip().endswith(_HEAD)
        line = raw_line.replace(_HEAD, "").strip()
        if not line:
            if pending_heading is None and lines and lines[-1] != "":
                lines.append("")
            continue
        if is_heading:
            flush_pending()
            pending_heading = line.rstrip(".:;,")
            continue
        if pending_heading is not None:
            line = f"{pending_heading.rstrip('.:;,')}, {line}"
            pending_heading = None
        if add_sentence_pauses and line[-1] not in ".!?;:":
            line += "."
        lines.append(line)
    flush_pending()
    text = "\n".join(lines)
    for pattern, repl in ((r"\n{3,}", "\n\n"), (r"[ \t]{2,}", " "), (r"\s+([,.;:!?])", r"\1"),
                          (r"([,.;:!?])([A-Za-z])", r"\1 \2"), (r"\.{4,}", "...")):
        text = re.sub(pattern, repl, text)
    return text.strip()


_THINK_BLOCK_RE = re.compile(r"<think[\s>].*?</think>", flags=re.DOTALL | re.IGNORECASE)
_THINK_BLOCK_OPEN_RE = re.compile(r"<think[\s>].*\Z", flags=re.DOTALL | re.IGNORECASE)
_VERIFIER_FOOTER_RE = re.compile(r"^\s*⚠️?\s*File-mutation verifier:.*(?:\n[ \t]+•.*)*", flags=re.MULTILINE)


def strip_nonspoken_blocks(text: str) -> str:
    """移除 ``<think>`` 推理块与文件校验器页脚。"""
    if not text:
        return ""
    for pattern in (_THINK_BLOCK_RE, _THINK_BLOCK_OPEN_RE, _VERIFIER_FOOTER_RE):
        text = pattern.sub(" ", text)
    return text


def flatten_newlines_for_payload(text: str) -> str:
    """把换行折叠为句断，适配对换行敏感的 TTS 后端。"""
    if not text:
        return ""
    for pattern, repl in ((r"\n{2,}", ". "), (r"(?<=[.!?;:,])\n", " "), (r"\n", ". "), (r"\.\s*\.", "."),
                          (r"[ \t]{2,}", " ")):
        text = re.sub(pattern, repl, text)
    return text.strip()


def prepare_spoken_text(text: str, max_chars: int | None = 4000) -> str:
    """返回适合朗读的语音脚本（确定性清理，非改写）。"""
    spoken = text
    for step in (strip_nonspoken_blocks, strip_markdown_for_tts, normalize_symbols_for_tts,
                 smooth_whitespace_for_tts, flatten_newlines_for_payload):
        spoken = step(spoken)
    if max_chars is not None and max_chars > 0 and len(spoken) > max_chars:
        spoken = spoken[:max_chars].rstrip()
    return spoken
