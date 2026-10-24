"""音频工具与容器处理 —— 迁移自 hermes-agent ``tools/tts_tool_delivery.py`` / ``tools/audio_container.py``。

提供:
- WAV 包装（raw PCM -> RIFF）
- ffmpeg 转码（WAV/MP3 -> Ogg/Opus 语音气泡编码）
- 容器嗅探/修复（TTS 后端常忽略请求格式，写错扩展名）
- 长文本分块（按 provider 请求上限）
- 交付打包（按平台上传上限分组/合并）
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _windows_hide_flags():
    """Windows 隐藏控制台窗口（subprocess.CREATE_NO_WINDOW）；其他平台 0。"""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _section(tts_config: Any, key: str) -> dict[str, Any]:
    """``tts.<key>`` 作为 dict（null/非 dict 读作空）。"""
    section = tts_config.get(key) if isinstance(tts_config, dict) else None
    return section if isinstance(section, dict) else {}


def _positive_int(value: Any) -> int | None:
    """*value* 为正非布尔 int 时返回，否则 None。"""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _remove_quietly(path: str | None) -> None:
    """尽力删除（缺失/占用忽略）。"""
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


# ---- PCM/WAV ----
GEMINI_TTS_SAMPLE_RATE, GEMINI_TTS_CHANNELS, GEMINI_TTS_SAMPLE_WIDTH = 24000, 1, 2


def wrap_pcm_as_wav(
    pcm_bytes: bytes, sample_rate: int = GEMINI_TTS_SAMPLE_RATE,
    channels: int = GEMINI_TTS_CHANNELS, sample_width: int = GEMINI_TTS_SAMPLE_WIDTH) -> bytes:
    """将 raw 小端 PCM 包装为最小 WAV RIFF 头。"""
    block_align = channels * sample_width
    fmt_chunk = struct.pack("<4sIHHIIHH", b"fmt ", 16, 1, channels, sample_rate,
                            sample_rate * block_align, block_align, sample_width * 8)
    data_chunk_header = struct.pack("<4sI", b"data", len(pcm_bytes))
    riff_size = 4 + len(fmt_chunk) + len(data_chunk_header) + len(pcm_bytes)
    riff_header = struct.pack("<4sI4s", b"RIFF", riff_size, b"WAVE")
    return riff_header + fmt_chunk + data_chunk_header + pcm_bytes


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _ffmpeg_run(ffmpeg: str, args: list[str], *, timeout: int = 30, check: bool = False,
                capture: bool = True) -> subprocess.CompletedProcess:
    """运行 ``ffmpeg <args>``（无 stdin，Windows 隐藏窗口）。"""
    return subprocess.run([ffmpeg, *args], capture_output=capture, check=check, timeout=timeout,
                          stdin=subprocess.DEVNULL, creationflags=_windows_hide_flags())


# ffmpeg 生成 Telegram 等语音气泡所需的 Ogg/Opus 参数
OPUS_VOICE_ARGS = [
    "-acodec", "libopus", "-ac", "1", "-b:a", "48k", "-vbr", "on",
    "-application", "voip", "-compression_level", "10"]


def write_wav_bytes_as(wav_bytes: bytes, output_path: str) -> str:
    """将内存 WAV 写入 *output_path*，ffmpeg 转码为目标容器。``.ogg`` 强制 Opus
    （ffmpeg .ogg 默认 Vorbis，语音气泡会拒收）。转码失败抛 RuntimeError；无 ffmpeg
    时按请求名写原始 WAV（扩展名误导但可播放）。"""
    if output_path.lower().endswith(".wav"):
        with open(output_path, "wb") as f:
            f.write(wav_bytes)
        return output_path
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        wav_path = tmp.name
    try:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            opus = OPUS_VOICE_ARGS if output_path.lower().endswith(".ogg") else []
            result = _ffmpeg_run(ffmpeg, ["-i", wav_path, *opus, "-y", "-loglevel", "error", output_path])
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="ignore")[:300]
                raise RuntimeError(f"ffmpeg conversion failed: {stderr}")
        else:
            logger.warning("ffmpeg not found; writing raw WAV to %s (extension may be misleading)", output_path)
            shutil.copyfile(wav_path, output_path)
    finally:
        _remove_quietly(wav_path)
    return output_path


def transcode_to_ogg_opus(input_path: str, *, bitrate: str = "48k", timeout: int = 30,
                          output_path: str | None = None) -> str | None:
    """将任意 ffmpeg 可读音频转码为 Ogg/Opus；失败返回 None。"""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    out = output_path or (input_path.rsplit(".", 1)[0] + ".ogg")
    try:
        result = _ffmpeg_run(
            ffmpeg, ["-i", input_path, "-acodec", "libopus", "-ac", "1", "-b:a", bitrate,
                     "-vbr", "on", "-application", "voip", "-compression_level", "10",
                     "-y", "-loglevel", "error", out], timeout=timeout)
        if result.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            return out
        logger.warning("ffmpeg Ogg/Opus transcode failed: %s",
                       result.stderr.decode("utf-8", errors="ignore")[:300])
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffmpeg Ogg/Opus transcode failed: %s", exc)
    return None


# ---- 容器嗅探/修复 ----
CONTAINER_TO_EXT = {c: f".{c}" for c in ("m4a", "mp4", "ogg", "flac", "wav", "mp3", "aac", "webm")}
_MP4_AUDIO_BRANDS = (b"m4a ", b"m4b ")
_PREFIX_CONTAINERS = ((b"OggS", "ogg"), (b"fLaC", "flac"), (b"ID3", "mp3"))


def sniff_container(data: bytes) -> str | None:
    """从魔数返回容器 id（CONTAINER_TO_EXT 键）或 None。"""
    if len(data) >= 8 and data[4:8] == b"ftyp":
        if len(data) >= 12 and data[8:12].lower() in _MP4_AUDIO_BRANDS:
            return "m4a"
        return "mp4"
    for prefix, container in _PREFIX_CONTAINERS:
        if data.startswith(prefix):
            return container
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "aac" if (data[1] & 0xF6) == 0xF0 else "mp3"
    if data.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    return None


def sniff_audio_ext(data: bytes, fallback_ext: str = ".ogg") -> str:
    """返回容器匹配的扩展名；未知时返回 fallback。"""
    fallback = fallback_ext if fallback_ext.startswith(".") else f".{fallback_ext}"
    container = sniff_container(data)
    if container is None:
        return fallback
    return ".m4a" if container == "mp4" else CONTAINER_TO_EXT[container]


def sniff_audio_container(path: str) -> str:
    """返回文件真实容器 id 或 'unknown'。"""
    try:
        with open(path, "rb") as fh:
            return sniff_container(fh.read(12)) or "unknown"
    except OSError:
        return "unknown"


def repair_ogg_container(file_str: str) -> str:
    """确保 ``.ogg`` 路径真为 Ogg：就地转码，否则改名真实扩展名。"""
    container = sniff_audio_container(file_str) if file_str.endswith(".ogg") else "ogg"
    if container in ("ogg", "unknown"):
        return file_str
    logger.info("TTS wrote %s bytes into a .ogg path (%s) — transcoding to real Ogg/Opus", container, file_str)
    repaired = transcode_to_ogg_opus(file_str, bitrate="48k", timeout=30, output_path=file_str)
    if repaired:
        return repaired
    honest = f"{file_str[:-4]}.{container}"
    try:
        os.replace(file_str, honest)
    except OSError:
        return file_str
    logger.warning("Could not transcode %s to Ogg/Opus — renamed to %s",
                   file_str, honest)
    return honest


# ---- 长文本分块 ----
def pack_under_cap(pieces: list[str], max_chars: int, *, slice_oversized: bool = False) -> list[str]:
    """贪心以单空格连接 *pieces*，超过 *max_chars* 另起块；``slice_oversized`` 时
    超长 piece 硬切为独立块。"""
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if slice_oversized and len(piece) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(piece[i:i + max_chars] for i in range(0, len(piece), max_chars))
            continue
        candidate = f"{current} {piece}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


# 句末标点：中文。！？；… 与英文 !?;（英文 . 单独处理，避开小数/版本号）
_SENT_END_CHARS = frozenset("。！？!?；;…")
# 句末标点后可能紧跟的闭合引号/括号（归入当前句，避免下一段以 " 开头）
_CLOSE_CHARS = frozenset("\"'”’』」）】》〉")
# 分句标点：超长句优先在此处切开（逗号/冒号/顿号）
_CLAUSE_CHARS = frozenset("，、,：:；;")


def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF   # CJK 统一汉字
        or 0x3000 <= code <= 0x303F  # CJK 标点
        or 0xFF00 <= code <= 0xFFEF  # 全角字符
        or 0x2E80 <= code <= 0x2EFF  # CJK 部首
        or 0x3400 <= code <= 0x4DBF
    )


def _is_english_sentence_end(text: str, index: int) -> bool:
    """英文句号视为句末的条件：前一字符非数字（避开 3.14 / v2.1），
    后随空白、闭合引号或文本结尾。"""
    if text[index] != ".":
        return False
    prev = text[index - 1] if index > 0 else ""
    nxt = text[index + 1] if index + 1 < len(text) else " "
    return not prev.isdigit() and (nxt.isspace() or nxt in _CLOSE_CHARS)


def _split_sentences(text: str) -> list[str]:
    """按句末标点拆句；句末标点后紧随的闭合引号吸收进当前句。"""
    out: list[str] = []
    buf: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        buf.append(ch)
        is_end = ch in _SENT_END_CHARS or _is_english_sentence_end(text, i)
        if is_end:
            j = i + 1
            while j < n and text[j] in _CLOSE_CHARS:
                buf.append(text[j])
                j += 1
            i = j
            segment = "".join(buf).strip()
            if segment:
                out.append(segment)
            buf = []
            continue
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def _split_clauses(sentence: str) -> list[str]:
    """超长句按分句标点切；无分句标点时逐词切。"""
    parts = re.split(r"(?<=[，、,：:；;])\s*", sentence)
    if len(parts) <= 1:
        parts = re.split(r"(?<=\s)", sentence)
    return [p for p in parts if p]


def _pack_pieces_cjk(pieces: list[str], max_chunk: int) -> list[str]:
    """贪心打包：相邻中文字段不插空格（CJK 朗读更自然），超长 piece 硬切。"""
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        if len(piece) > max_chunk:
            if current:
                chunks.append(current)
                current = ""
            for idx in range(0, len(piece), max_chunk):
                chunks.append(piece[idx:idx + max_chunk])
            continue
        if not current:
            current = piece
            continue
        joiner = "" if _is_cjk_char(current[-1]) and _is_cjk_char(piece[0]) else " "
        candidate = current + joiner + piece
        if len(candidate) > max_chunk:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _truncate_keeping_sentences(text: str, max_total: int) -> str:
    """截断到 *max_total* 内最后一个句末标点（保留完整句子）。"""
    head = text[:max_total]
    for idx in range(len(head) - 1, -1, -1):
        if head[idx] in _SENT_END_CHARS:
            return head[:idx + 1].strip()
    return head.rstrip()


def segment_text_for_tts(text: str, max_chunk: int = 300, max_total: int | None = None) -> list[str]:
    """把朗读文本切分为自然的 TTS 分段。

    - 段界优先落在句末标点（中文。！？…；; 与英文 .!?;），句子不跨段
    - 单句超长时先按分句标点（，、,：:）切，仍超长再逐词/硬切
    - 每段长度 <= *max_chunk*；*max_total* 为总字数上限（截断时保留完整句子）
    - 相邻中文字段之间不插空格
    """
    if not max_chunk or max_chunk <= 0:
        max_chunk = 300
    normalized = " ".join((text or "").split())
    if not normalized:
        return []
    if max_total and len(normalized) > max_total:
        normalized = _truncate_keeping_sentences(normalized, max_total)
        if not normalized:
            return []
    sentences = _split_sentences(normalized)
    pieces: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chunk:
            pieces.append(sentence)
        else:
            pieces.extend(_split_clauses(sentence))
    return _pack_pieces_cjk(pieces, max_chunk)


def split_text_for_tts(text: str, max_chars: int) -> list[str]:
    """在 provider 上限下拆分长文本：句界优先（中英文），超长句按分句标点再切。"""
    if max_chars <= 0:
        max_chars = 4000
    return segment_text_for_tts(text, max_chunk=max_chars)


# ---- 交付打包 ----
@dataclass(frozen=True)
class AudioDeliveryProfile:
    """目标平台上传约束。"""

    platform: str
    max_file_bytes: int
    safety_ratio: float = 0.85

    @property
    def target_file_bytes(self) -> int:
        return max(1, int(self.max_file_bytes * self.safety_ratio))


_PLATFORM_AUDIO_DEFAULTS: dict[str, dict[str, Any]] = {
    "discord": {"max_file_bytes": 10 * 1024 * 1024, "safety_ratio": 0.85},
    "telegram": {"max_file_bytes": 50 * 1024 * 1024, "safety_ratio": 0.85},
    "feishu": {"max_file_bytes": 100 * 1024 * 1024, "safety_ratio": 0.85},
    "default": {"max_file_bytes": 10 * 1024 * 1024, "safety_ratio": 0.85}}


def resolve_audio_delivery_profile(platform: str | None,
                                   tts_config: dict[str, Any] | None = None) -> AudioDeliveryProfile:
    """按平台解析上传约束（含 ``tts.delivery_profiles`` 覆盖）。"""
    key = (platform or "default").lower().strip() or "default"
    defaults = dict(_PLATFORM_AUDIO_DEFAULTS.get(key) or _PLATFORM_AUDIO_DEFAULTS["default"])
    overrides = _section(_section(tts_config, "delivery_profiles"), key)
    defaults.update({k: v for k, v in overrides.items() if v is not None})
    max_file_bytes = (_positive_int(defaults.get("max_file_bytes"))
                      or _PLATFORM_AUDIO_DEFAULTS["default"]["max_file_bytes"])
    safety_ratio = defaults.get("safety_ratio", 0.85)
    if (isinstance(safety_ratio, bool) or not isinstance(safety_ratio, (int, float))
            or not 0 < safety_ratio <= 1):
        safety_ratio = 0.85
    return AudioDeliveryProfile(platform=key, max_file_bytes=max_file_bytes, safety_ratio=float(safety_ratio))


def concat_audio_files(audio_paths: list[str], output_path: str, *, voice_compatible: bool = False,
                       gap_ms: int = 0) -> str | None:
    """ffmpeg 合并独立编码的分块（绝不字节拼接）。Ogg/Opus 总是重编码；同后缀 MP3 保留帧
    （``-c:a copy``）。``gap_ms`` > 0 时改走 filter_complex，在每个分块末尾垫入静音
    （段间自然停顿，避免长回复断句生硬）。ffmpeg 缺失/失败返回 None，调用方保留有效分块。"""
    if not audio_paths:
        raise ValueError("No audio chunks to combine")
    if len(audio_paths) == 1:
        if os.path.abspath(audio_paths[0]) != os.path.abspath(output_path):
            shutil.copyfile(audio_paths[0], output_path)
        return output_path
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if gap_ms and gap_ms > 0:
        return _concat_audio_with_gap(ffmpeg, audio_paths, destination, voice_compatible, gap_ms)
    concat_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.concat.txt")
    temp_output = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.combining{destination.suffix}")
    try:
        entries = "".join(f"file {shlex.quote(os.path.abspath(p))}\n" for p in audio_paths)
        concat_path.write_text(entries, encoding="utf-8")
        args = ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(concat_path), "-vn"]
        suffix = destination.suffix.lower()
        if voice_compatible or suffix in {".ogg", ".opus"}:
            args += ["-c:a", "libopus", "-ac", "1", "-b:a", "64k", "-vbr", "off"]
        elif suffix == ".mp3" and all(Path(path).suffix.lower() == ".mp3" for path in audio_paths):
            args += ["-c:a", "copy"]
        result = _ffmpeg_run(ffmpeg, [*args, str(temp_output)], timeout=120)
        if result.returncode == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
            os.replace(temp_output, destination)
            return str(destination)
        logger.warning("ffmpeg audio combine failed: %s",
                       result.stderr.decode("utf-8", errors="ignore")[:500])
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffmpeg audio combine failed: %s", exc)
    finally:
        for path in (concat_path, temp_output):
            _remove_quietly(path)
    return None


def _concat_audio_with_gap(ffmpeg: str, audio_paths: list[str], destination: Path,
                           voice_compatible: bool, gap_ms: int) -> str | None:
    """ffmpeg filter_complex 合并，并在每个分块末尾 ``apad`` 垫入静音。"""
    temp_output = destination.with_name(f".{destination.stem}.{uuid.uuid4().hex}.gap{destination.suffix}")
    try:
        gap = max(0.0, float(gap_ms) / 1000.0)
        n = len(audio_paths)
        inputs: list[str] = []
        for p in audio_paths:
            inputs += ["-i", p]
        chain: list[str] = []
        labels: list[str] = []
        # 除最后一段外均垫入静音；最后一段原样拼接（避免回复末尾多余停顿）
        for i in range(n - 1):
            label = f"[p{i}]"
            chain.append(f"[{i}:a]apad=pad_dur={gap:.3f}{label}")
            labels.append(label)
        if n > 0:
            labels.append(f"[{n - 1}:a]")
        chain.append("".join(labels) + f"concat=n={n}:v=0:a=1[out]")
        suffix = destination.suffix.lower()
        if voice_compatible or suffix in {".ogg", ".opus"}:
            out_args = ["-c:a", "libopus", "-ac", "1", "-b:a", "64k", "-vbr", "off"]
        elif suffix == ".wav":
            out_args = ["-c:a", "pcm_s16le", "-ac", "1", "-ar", "44100"]
        else:
            out_args = ["-c:a", "libmp3lame", "-ac", "1", "-b:a", "48k"]
        result = _ffmpeg_run(ffmpeg, ["-y", "-loglevel", "error", *inputs,
                                      "-filter_complex", ";".join(chain),
                                      "-map", "[out]", *out_args, str(temp_output)], timeout=120)
        if result.returncode == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
            os.replace(temp_output, destination)
            return str(destination)
        logger.warning("ffmpeg gap-merge failed: %s",
                       result.stderr.decode("utf-8", errors="ignore")[:500])
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ffmpeg gap-merge failed: %s", exc)
    finally:
        _remove_quietly(temp_output)
    return None


def build_audio_delivery_files(
    audio_paths: list[str], output_path: str, profile: AudioDeliveryProfile, *, voice_compatible: bool = False,
) -> tuple[list[str], bool]:
    """按上传硬上限打包最终编码块 -> ``(final_paths, combined_any)``。

    分组按保守目标体积；合并产物按真实大小复查，超限组对半拆分重试；合并失败返回
    各组成文件；单块超硬上限直接失败。
    """
    if not audio_paths:
        raise ValueError("No final-encoded TTS audio chunks")
    for path in audio_paths:
        size = Path(path).stat().st_size
        if size > profile.max_file_bytes:
            raise ValueError(
                f"Final-encoded TTS chunk exceeds {profile.platform} delivery "
                f"limit ({size} > {profile.max_file_bytes} bytes): {path}")
    base = Path(output_path)
    scratch_outputs: list[str] = []
    combined_any, combine_index = False, 0

    def emit(group: list[str]) -> list[str]:
        nonlocal combined_any, combine_index
        if len(group) == 1:
            return list(group)
        combine_index += 1
        scratch = base.with_name(f".{base.stem}.delivery{combine_index:03d}.{uuid.uuid4().hex}{base.suffix}")
        combined = concat_audio_files(group, str(scratch), voice_compatible=voice_compatible)
        if not combined:
            return list(group)
        scratch_outputs.append(combined)
        if Path(combined).stat().st_size <= profile.max_file_bytes:
            combined_any = True
            return [combined]
        _remove_quietly(combined)
        midpoint = max(1, len(group) // 2)
        return emit(group[:midpoint]) + emit(group[midpoint:])

    groups: list[list[str]] = []
    current: list[str] = []
    current_size, current_suffix = 0, ""
    for path in audio_paths:
        size, suffix = Path(path).stat().st_size, Path(path).suffix.lower()
        if current and (current_size + size > profile.target_file_bytes or suffix != current_suffix):
            groups.append(current)
            current, current_size = [], 0
        current.append(path)
        current_size, current_suffix = current_size + size, suffix
    groups += [current] if current else []
    packed = [path for group in groups for path in emit(group)]
    final_paths: list[str] = []
    for index, source in enumerate(packed, start=1):
        destination = base
        if len(packed) > 1:
            destination = base.with_name(f"{base.stem}.part{index:02d}{Path(source).suffix or base.suffix}")
        if os.path.abspath(source) != os.path.abspath(destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
        if destination.stat().st_size > profile.max_file_bytes:
            raise ValueError(f"Final TTS deliverable exceeds {profile.platform} delivery limit: {destination}")
        final_paths.append(str(destination))
    try:
        return final_paths, combined_any
    finally:
        for scratch in scratch_outputs:
            if scratch not in final_paths:
                _remove_quietly(scratch)
