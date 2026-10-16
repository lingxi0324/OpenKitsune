"""语音检测（VAD）与录音 —— 迁移自 hermes-agent ``tools/voice_mode.py``。

核心能力:
1. :class:`AudioRecorder` —— sounddevice 输入流录音器：
   - RMS 能量阈值检测（``silence_threshold``）
   - 语音确认（连续 ``min_speech_duration`` 超过阈值，容忍 ``max_dip_tolerance`` 微停顿）
   - 静音自动停止（说过话后连续 ``silence_duration`` 静音）与最长等待/录音上限
   - ``stop()`` 返回 WAV 路径，过短/过静录音自动丢弃
2. :func:`listen_for_speech` —— 阻塞式持续监听（抢话监视器）：
   - 滚动噪声底（90 分位）+ 8x 触发倍率，过滤扬声器回放漏音
   - ``capture=True`` 时预卷录音（pre_roll buffer），静音后返回完整话语 WAV
3. :class:`_BargeDetector` / :func:`full_duplex_listen` —— 全双工监听：
   - 整轮 agent turn 监听，静音房间校准底噪；播放阶段钳制触发下限
   - 抢话判定（>=80% 的窗口块超过触发线）+ 播放起始宽限窗
4. 播放控制：:func:`play_audio_file` / :func:`stop_playback` / :func:`mark_audio_output_active`

依赖：``sounddevice``（PortAudio）+ ``numpy``（均为可选，缺失时优雅降级）。
"""

from __future__ import annotations

import contextlib
import logging
import os
import subprocess
import sys
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from typing import Any

from .config import (
    CHANNELS,
    DTYPE,
    SAMPLE_RATE,
    SILENCE_DURATION_SECONDS,
    SILENCE_RMS_THRESHOLD,
    get_vad_config,
)

logger = logging.getLogger(__name__)

_TEMP_DIR: str = ""


def _import_audio():
    """惰性导入 sounddevice + numpy；缺失时抛 ImportError。"""
    import numpy  # noqa: F401
    import sounddevice as sd
    return sd, numpy


def _rms(np, data) -> float:
    """int16 块的 RMS 电平（0-32767 量级）。"""
    return float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))


def _default_input_samplerate(sd) -> int:
    """默认输入采样率：默认值 16000（多数 STT 友好）；可尝试查询设备。"""
    try:
        device = sd.default.device[0] if isinstance(sd.default.device, tuple) else sd.default.device
        info = sd.query_devices(device)
        rate = int(info.get("default_samplerate") or SAMPLE_RATE)
        return rate if rate > 0 else SAMPLE_RATE
    except Exception:
        return SAMPLE_RATE


def _write_wav_frames(dest: str, frames: bytes, sample_rate: int) -> None:
    """将 PCM 字节写入 WAV 文件（16-bit mono）。"""
    with wave.open(dest, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)


def _unlink_quietly(path: str | None) -> None:
    """尽力删除（缺失/占用忽略）。"""
    if path:
        try:
            os.remove(path)
        except OSError:
            pass


def _new_recording_path(ext: str) -> str:
    """时间戳录音路径 ``recording_*.<ext>``（输出目录按需创建）。"""
    from .config import ensure_output_dir
    return str(ensure_output_dir() / f"recording_{time.strftime('%Y%m%d_%H%M%S')}.{ext}")


class _RecorderBase:
    """锁、录音标记、开始时间与实时 RMS 的公共底座。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recording, self._start_time, self._current_rms = False, 0.0, 0

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time if self._recording else 0.0

    @property
    def current_rms(self) -> int:
        """当前输入 RMS（0-32767），随音频块更新。"""
        return self._current_rms


class AudioRecorder(_RecorderBase):
    """线程安全 sounddevice.InputStream 录音器。

    ``start(on_silence_stop=cb)`` 开始录音；``stop()`` 返回 WAV 路径或 None；
    ``cancel()`` 丢弃。传入回调时，说过话后静音 ``silence_duration`` 秒自动停止。
    """

    supports_silence_autostop = True

    def __init__(self) -> None:
        super().__init__()
        vad_cfg = get_vad_config()
        self._stream: Any = None
        self._frames: list[Any] = []
        self._sample_rate: int = int(vad_cfg.get("sample_rate", SAMPLE_RATE))
        self._on_silence_stop = None
        self._silence_threshold: int = int(vad_cfg.get("silence_threshold", SILENCE_RMS_THRESHOLD))
        self._silence_duration: float = float(vad_cfg.get("silence_duration", SILENCE_DURATION_SECONDS))
        self._min_speech_duration: float = float(vad_cfg.get("min_speech_duration", 0.3))
        self._max_dip_tolerance: float = float(vad_cfg.get("max_dip_tolerance", 0.3))
        self._max_wait: float = float(vad_cfg.get("max_wait", 15.0))
        self._max_recording_seconds: float = float(vad_cfg.get("max_recording_seconds", 0.0))
        self._peak_rms: int = 0
        self._reset_detection_state()

    def _reset_detection_state(self) -> None:
        self._has_spoken = False
        self._speech_start = self._dip_start = self._silence_start = 0.0
        self._resume_start = self._resume_dip_start = 0.0

    def _max_duration_reached(self, elapsed: float) -> bool:
        cap = self._max_recording_seconds
        return bool(cap and cap > 0 and elapsed >= cap)

    def _track_speech(self, rms: int, now: float) -> None:
        """推进一个块的语音/停顿跟踪。连续 ``min_speech_duration`` 超阈值确认语音，
        容忍 ``max_dip_tolerance`` 微停顿；此后只有持续恢复的语音才重置静音计时。"""
        if rms > self._silence_threshold:
            self._dip_start = 0.0
            if self._speech_start == 0.0:
                self._speech_start = now
            elif not self._has_spoken and now - self._speech_start >= self._min_speech_duration:
                self._has_spoken = True
                logger.debug("Speech confirmed (%.2fs above threshold)", now - self._speech_start)
            if not self._has_spoken:
                self._silence_start = 0.0
            else:
                self._resume_dip_start = 0.0
                if self._resume_start == 0.0:
                    self._resume_start = now
                elif now - self._resume_start >= self._min_speech_duration:
                    self._silence_start = 0.0
                    self._resume_start = 0.0
        elif self._has_spoken:
            if self._resume_start > 0:
                if self._resume_dip_start == 0.0:
                    self._resume_dip_start = now
                elif now - self._resume_dip_start >= self._max_dip_tolerance:
                    self._resume_start = 0.0
                    self._resume_dip_start = 0.0
        elif self._speech_start > 0:
            if self._dip_start == 0.0:
                self._dip_start = now
            elif now - self._dip_start >= self._max_dip_tolerance:
                logger.debug("Speech attempt reset (dip lasted %.2fs)", now - self._dip_start)
                self._speech_start = 0.0
                self._dip_start = 0.0

    def _should_auto_stop(self, rms: int, now: float) -> bool:
        """说过话后静音 ``silence_duration``；始终无语音超 ``max_wait``；或硬上限已到。"""
        elapsed = now - self._start_time
        if self._has_spoken and rms <= self._silence_threshold:
            if self._silence_start == 0.0:
                self._silence_start = now
            elif now - self._silence_start >= self._silence_duration:
                logger.info("Silence detected (%.1fs), auto-stopping", self._silence_duration)
                return True
        elif not self._has_spoken and elapsed >= self._max_wait:
            logger.info("No speech within %.0fs, auto-stopping", self._max_wait)
            return True
        if self._max_duration_reached(elapsed):
            logger.info("Max recording length reached (%.0fs), auto-stopping", self._max_recording_seconds)
            return True
        return False

    def _fire_silence_callback(self) -> None:
        """仅触发一次 ``on_silence_stop``（守护线程）。"""
        with self._lock:
            cb, self._on_silence_stop = self._on_silence_stop, None
        if not cb:
            return

        def _safe_cb():
            try:
                cb()
            except Exception as e:
                logger.error("Silence callback failed: %s", e, exc_info=True)

        threading.Thread(target=_safe_cb, daemon=True).start()

    def _on_audio_block(self, np, indata) -> None:
        self._frames.append(indata.copy())
        rms = int(_rms(np, indata))
        self._current_rms = rms
        self._peak_rms = max(self._peak_rms, rms)
        if self._on_silence_stop is None:
            return
        now = time.monotonic()
        self._track_speech(rms, now)
        if self._should_auto_stop(rms, now):
            self._fire_silence_callback()

    def _ensure_stream(self) -> None:
        """创建并复用 InputStream（录音间回调丢弃块；避免反复打开导致挂起）。"""
        if self._stream is not None:
            return
        sd, np = _import_audio()

        def _callback(indata, frames, time_info, status):
            if status:
                logger.debug("sounddevice status: %s", status)
            if self._recording:
                self._on_audio_block(np, indata)

        stream = None
        for attempt in range(2):
            try:
                stream = sd.InputStream(samplerate=self._sample_rate, channels=CHANNELS, dtype=DTYPE,
                                        callback=_callback)
                stream.start()
                break
            except Exception as e:
                with contextlib.suppress(Exception):
                    if stream:
                        stream.close()
                stream = None
                if attempt or "timed out" not in str(e).lower():
                    raise RuntimeError(
                        f"Failed to open audio input stream: {e}. "
                        "Check that a microphone is connected and accessible.") from e
                logger.info("Audio input stream start timed out; retrying once")
        self._stream = stream

    def start(self, on_silence_stop=None) -> None:
        """开始录音；*on_silence_stop* 在静音跟随语音时触发（守护线程，无参）。"""
        try:
            sd, _ = _import_audio()
        except ImportError as e:
            raise RuntimeError(
                "Voice mode requires sounddevice and numpy.\n"
                f"Install with: {sys.executable} -m pip install sounddevice numpy") from e
        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._start_time = time.monotonic()
            self._reset_detection_state()
            self._peak_rms = 0
            self._current_rms = 0
            self._on_silence_stop = on_silence_stop
        self._sample_rate = _default_input_samplerate(sd)
        self._ensure_stream()
        with self._lock:
            self._recording = True
        logger.info("Voice recording started (rate=%d, channels=%d)", self._sample_rate, CHANNELS)

    def _close_stream_with_timeout(self, timeout: float = 3.0) -> None:
        """带超时关闭流（防 CoreAudio 挂起）。"""
        if self._stream is None:
            return
        stream, self._stream = self._stream, None

        def _do_close():
            with contextlib.suppress(Exception):
                stream.stop()
                stream.close()

        t = threading.Thread(target=_do_close, daemon=True)
        t.start()
        deadline = time.monotonic() + timeout
        while t.is_alive() and time.monotonic() < deadline:
            t.join(timeout=0.1)
        if t.is_alive():
            logger.warning("Audio stream close timed out after %.1fs — forcing ahead", timeout)

    def stop(self) -> str | None:
        """停止录音（流保持存活），返回 WAV 路径；不可用时返回 None。"""
        with self._lock:
            if not self._recording:
                return None
            self._recording, self._current_rms = False, 0
            if not self._frames:
                return None
            _, np = _import_audio()
            audio_data = np.concatenate(self._frames, axis=0)
            self._frames = []
            logger.info("Voice recording stopped (%.1fs, %d samples)",
                        time.monotonic() - self._start_time, len(audio_data))
            if len(audio_data) < int(self._sample_rate * 0.3):
                logger.debug("Recording too short (%d samples), discarding", len(audio_data))
                return None
            if self._peak_rms < SILENCE_RMS_THRESHOLD:
                logger.info("Recording too quiet (peak RMS=%d < %d), discarding",
                            self._peak_rms, SILENCE_RMS_THRESHOLD)
                return None
            return self._write_wav(audio_data, sample_rate=self._sample_rate)

    def _discard(self) -> None:
        with self._lock:
            self._recording, self._frames, self._on_silence_stop, self._current_rms = False, [], None, 0

    def cancel(self) -> None:
        """停止并丢弃全部录音（流保持存活）。"""
        self._discard()
        logger.info("Voice recording cancelled")

    def shutdown(self) -> None:
        """释放音频流（语音模式关闭时调用）。"""
        self._discard()
        self._close_stream_with_timeout()
        logger.info("AudioRecorder shut down")

    @staticmethod
    def _write_wav(audio_data, *, sample_rate: int = SAMPLE_RATE) -> str:
        """将 numpy int16 音频写入 WAV 文件；返回路径。"""
        wav_path = _new_recording_path("wav")
        _write_wav_frames(wav_path, audio_data.tobytes(), sample_rate)
        logger.info("WAV written: %s (%d bytes)", wav_path, os.path.getsize(wav_path))
        return wav_path


def create_audio_recorder() -> AudioRecorder:
    """返回当前环境可用的录音器后端。"""
    return AudioRecorder()


# ── 播放控制 ──
_active_playback_proc: Any = None
_playback_lock = threading.Lock()
_audio_output_active = False
_audio_output_active_lock = threading.Lock()


def mark_audio_output_active(active: bool) -> None:
    """标记是否有音频输出进行中（供 BargeDetector 判断阶段）。"""
    global _audio_output_active
    with _audio_output_active_lock:
        _audio_output_active = bool(active)


def is_audio_output_active() -> bool:
    with _audio_output_active_lock:
        return _audio_output_active


def _set_active_playback(proc) -> None:
    global _active_playback_proc
    with _playback_lock:
        _active_playback_proc = proc


def stop_playback() -> None:
    """停止当前播放（抢话时调用）。"""
    global _active_playback_proc
    with _playback_lock:
        proc, _active_playback_proc = _active_playback_proc, None
    if proc is not None:
        with contextlib.suppress(Exception):
            proc.terminate()
        with contextlib.suppress(Exception):
            proc.kill()


def play_audio_file(file_path: str) -> bool:
    """播放本地音频文件（多后端降级）。返回是否成功开始播放。"""
    if not file_path or not os.path.isfile(file_path):
        return False
    try:
        sd, _ = _import_audio()
    except ImportError:
        sd = None
    if sd is not None:
        try:
            import soundfile as sf

            data, rate = sf.read(file_path, dtype="int16")
            if _play_int16_via_sounddevice(data, rate):
                return True
        except Exception as e:
            logger.debug("sounddevice playback unavailable: %s", e)
    return _play_via_system_player(file_path)


def _play_int16_via_sounddevice(data, sample_rate: int) -> bool:
    """通过 sounddevice 播放 int16 numpy 数组（阻塞播放线程）。"""
    try:
        import numpy as np

        sd, _ = _import_audio()
        event = threading.Event()

        def _play():
            try:
                sd.play(np.asarray(data), sample_rate)
                sd.wait()
            finally:
                event.set()

        t = threading.Thread(target=_play, daemon=True)
        t.start()
        # 等待启动确认（很短），避免播放器立即被判定失败
        event.wait(timeout=0.5)
        return True
    except Exception as e:
        logger.debug("sounddevice playback failed: %s", e)
        return False


def _system_player_candidates(file_path: str) -> list[list[str]]:
    """平台系统播放器候选命令。"""
    if sys.platform == "win32":
        return [["powershell", "-NoProfile", "-Command",
                 f"Start-Process -FilePath '{file_path}' -WindowStyle Hidden"]]
    if sys.platform == "darwin":
        return [["afplay", file_path]]
    return [["aplay", "-q", file_path], ["paplay", file_path], ["ffplay", "-nodisp", "-autoexit", file_path]]


def _play_via_system_player(file_path: str) -> bool:
    """用系统播放器播放（Windows 下隐藏窗口）。"""
    for cmd in _system_player_candidates(file_path):
        try:
            extra: dict = {}
            if os.name == "nt":
                extra["creationflags"] = subprocess.CREATE_NO_WINDOW
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)
            _set_active_playback(proc)
            return True
        except Exception as e:
            logger.debug("System player failed for %s: %s", cmd, e)
    return False


# ── 持续监听（抢话监视器）──
def listen_for_speech(
    should_stop: Callable[[], bool],
    threshold: int | None = None,
    sustained_ms: int = 300,
    calibration_ms: int = 400,
    capture: bool = False,
    on_trigger: Callable[[], None] | None = None,
    pre_roll_ms: int = 1200,
    endpoint_silence_ms: int = 1250,
    max_utterance_ms: int = 30_000,
):
    """阻塞直到麦克风出现持续语音，或 *should_stop*。

    Barge-in 监视器：TTS 播放期间在旁线程运行。无 *capture* 时用户开始说话返回 True
    （切断播放）；``capture=True`` 时同时录制打断话语——滚动 *pre_roll_ms* 缓冲保证
    从第一个音节开始保留——并持续滚动至用户静音 *endpoint_silence_ms*，随后返回 WAV
    路径（或 None 若从未触发）。*on_trigger* 在检测瞬间触发。

    噪声底从最初 *calibration_ms* 输入校准（此时播放已可闻，扬声器漏音被计入底噪），
    只比播放更响的语音能触发。连续 *sustained_ms* 超阈值过滤咳嗽/键盘/播放瞬态。
    """
    try:
        sd, np = _import_audio()
    except (ImportError, OSError):
        return None if capture else False

    block = int(SAMPLE_RATE * 0.03)  # 30ms 块
    calib_blocks = max(1, calibration_ms // 30)
    trip_blocks = max(1, sustained_ms // 30)
    endpoint_blocks = max(1, endpoint_silence_ms // 30)
    max_blocks = max(1, max_utterance_ms // 30)

    # 滚动底噪窗口（约 3 秒），持续跟踪 TTS 扬声器漏音音量 —— 防止一次性校准
    # 冻结在开篇 TTS 段落后，后续更响段落超过陈旧底噪造成误触发。
    floor_window: deque = deque(maxlen=max(calib_blocks, 100))
    pre_roll: deque = deque(maxlen=max(1, pre_roll_ms // 30))
    consecutive = 0
    min_floor = 0.0
    block_idx = 0

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=block) as stream:
            while not should_stop():
                data, _ = stream.read(block)
                rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
                if capture:
                    pre_roll.append(data.copy())
                block_idx += 1

                if len(floor_window) < calib_blocks:
                    floor_window.append(rms)
                    continue

                if min_floor == 0.0 and len(floor_window) >= calib_blocks:
                    _pct90 = float(np.percentile(list(floor_window), 90))
                    min_floor = max(_pct90, SILENCE_RMS_THRESHOLD * 2)
                else:
                    _pct90 = float(np.percentile(list(floor_window), 90))

                _floor = max(_pct90, min_floor)
                trigger = max(float(threshold or SILENCE_RMS_THRESHOLD * 2), _floor * 8.0)
                trigger = min(trigger, 4000.0)

                if rms < trigger:
                    floor_window.append(rms)

                consecutive = consecutive + 1 if rms >= trigger else 0
                if consecutive > 0:
                    logger.debug(
                        "VAD above-trigger: block=%d rms=%.0f floor=%.0f trigger=%.0f "
                        "consec=%d/%d min_floor=%.0f window_len=%d",
                        block_idx, rms, _floor, trigger, consecutive,
                        trip_blocks, min_floor, len(floor_window),
                    )
                if consecutive < trip_blocks:
                    continue

                logger.info(
                    "VAD TRIPPED: block=%d rms=%.0f floor=%.0f trigger=%.0f "
                    "consec=%d min_floor=%.0f — cutting TTS playback",
                    block_idx, rms, _floor, trigger, consecutive, min_floor,
                )
                if on_trigger:
                    try:
                        on_trigger()
                    except Exception as e:
                        logger.debug("Barge-in trigger callback failed: %s", e)
                if not capture:
                    return True

                # 滚动到用户安静。播放已停止，普通静音端点即可。
                frames: list[Any] = list(pre_roll)
                quiet = 0
                for _ in range(max_blocks):
                    data, _ = stream.read(block)
                    frames.append(data.copy())
                    rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
                    quiet = quiet + 1 if rms < SILENCE_RMS_THRESHOLD else 0
                    if quiet >= endpoint_blocks:
                        break
                return AudioRecorder._write_wav(np.concatenate(frames, axis=0))
    except Exception as e:
        logger.debug("Barge-in listener failed: %s", e)
    return None if capture else False


# ── 全双工监听（整轮 agent turn）──
PLAYBACK_MIN_TRIGGER = 1500.0  # TTS 播放期间最小触发线：漏音本身绝不触发
TRIGGER_CEILING = 4000.0       # 吵闹房间绝不把触发线推过正常语音
DEFAULT_BARGE_MULTIPLIER = 3.0 # 静音底噪倍数：300*3=900 vs 3000+ 语音


def _vad_log(msg: str) -> None:
    """VAD 诊断：logger.debug；OPENKITSUNE_VOICE_DEBUG=1 时同时输出到 stderr。"""
    logger.debug(msg)
    if os.environ.get("OPENKITSUNE_VOICE_DEBUG", "").strip() == "1":
        with contextlib.suppress(Exception):
            print(f"[voice-vad] {msg}", file=sys.stderr, flush=True)


def _capture_until_quiet(stream, np, block: int, pre_roll, *, endpoint_blocks: int, max_blocks: int) -> str:
    """触发后读取至 *endpoint_blocks* 静音（或 *max_blocks*），写预卷+录音为 WAV。"""
    frames: list[Any] = list(pre_roll)
    quiet = 0
    for _ in range(max_blocks):
        data, _ = stream.read(block)
        frames.append(data.copy())
        quiet = quiet + 1 if _rms(np, data) < SILENCE_RMS_THRESHOLD else 0
        if quiet >= endpoint_blocks:
            break
    return AudioRecorder._write_wav(np.concatenate(frames, axis=0))


class _BargeDetector:
    """``full_duplex_listen`` 背后的逐块抢话状态机。"""

    def __init__(self, np, *, mult: float, calib_blocks: int, trip_blocks: int, grace_blocks: int) -> None:
        self._np, self.mult, self.calib_blocks, self.grace_blocks = np, mult, calib_blocks, grace_blocks
        self.trip_needed = max(1, int(round(trip_blocks * 0.8)))
        self.ambient: deque = deque(maxlen=100)  # ~3s 静音阶段 RMS
        self.recent_above: deque = deque(maxlen=trip_blocks)
        self.quiet_floor = float(SILENCE_RMS_THRESHOLD)
        self.floor_locked = self.playing_prev = self.playback_seen = False
        self.grace_remaining = self.block_idx = 0
        self.blocks_since_playback = 10_000

    def _floor(self) -> tuple:
        """(pct90, floor)：静音窗口 90 分位；floor 不低于静音阈值。"""
        pct90 = float(self._np.percentile(list(self.ambient), 90)) if self.ambient else float(SILENCE_RMS_THRESHOLD)
        return pct90, max(pct90, float(SILENCE_RMS_THRESHOLD))

    def _calibrate(self, rms: float, playing: bool) -> bool:
        """从前 calib_blocks 锁定底噪：监听在 utterance 提交时武装（TTS 尚未存在），
        采样的是安静房间而非漏音。"""
        if not playing:
            self.ambient.append(rms)
        if len(self.ambient) >= self.calib_blocks or playing:
            pct90, self.quiet_floor = self._floor()
            self.floor_locked = True
            _vad_log(f"calibrated quiet floor={self.quiet_floor:.0f} "
                     f"(pct90={pct90:.0f}, {len(self.ambient)} blocks, mult={self.mult:g})")
        return self.floor_locked

    def _track_playback(self, playing: bool) -> None:
        """仅当播放经过真实间隔（>=1s）后才宽限，防止句间抖动连锁吞掉插话。"""
        if playing and not self.playing_prev:
            if not self.playback_seen or self.blocks_since_playback > 33:
                self.grace_remaining = self.grace_blocks
                _vad_log(f"playback started (block={self.block_idx}) — grace {self.grace_blocks * 30}ms")
            self.playback_seen = True
        self.playing_prev = playing
        self.blocks_since_playback = 0 if playing else self.blocks_since_playback + 1

    def feed(self, rms: float, playing: bool) -> str | None:
        """消费一个 30ms 块；语音触发时返回阶段名，否则 None。"""
        self.block_idx += 1
        if not self.floor_locked and not self._calibrate(rms, playing):
            return None
        self._track_playback(playing)
        trigger = max(self.quiet_floor * self.mult,
                      PLAYBACK_MIN_TRIGGER if playing else float(SILENCE_RMS_THRESHOLD) * 2)
        trigger = min(trigger, TRIGGER_CEILING)
        # 仅在无播放且非语音时跟踪环境漂移（绝不吸收漏音）。
        if not playing and rms < trigger:
            self.ambient.append(rms)
            _, self.quiet_floor = self._floor()
        above = rms >= trigger
        if above and self.grace_remaining > 0:
            _vad_log(f"grace suppression: block={self.block_idx} rms={rms:.0f} "
                     f"trigger={trigger:.0f} ({self.grace_remaining} blocks left)")
            above = False
        if self.grace_remaining > 0:
            self.grace_remaining -= 1
        self.recent_above.append(above)
        phase = "playback" if playing else "generation"
        if rms >= trigger * 0.5:
            _vad_log(f"block={self.block_idx} rms={rms:.0f} floor={self.quiet_floor:.0f} "
                     f"trigger={trigger:.0f} above={above} "
                     f"window={sum(self.recent_above)}/{self.trip_needed} phase={phase}")
        if not (above and sum(self.recent_above) >= self.trip_needed):
            return None
        _vad_log(f"TRIPPED ({phase}): block={self.block_idx} rms={rms:.0f} floor={self.quiet_floor:.0f} "
                 f"trigger={trigger:.0f} window={sum(self.recent_above)}/{len(self.recent_above)}")
        return phase


def full_duplex_listen(
    should_stop: Callable[[], bool], is_playing: Callable[[], bool] | None = None,
    on_trigger: Callable[[str], None] | None = None, multiplier: float | None = None,
    sustained_ms: int = 300, calibration_ms: int = 450, grace_ms: int = 500, pre_roll_ms: int = 1200,
    endpoint_silence_ms: int = 1250, max_utterance_ms: int = 30_000,
) -> str | None:
    """跨整轮 agent turn 监听；返回捕获的打断 WAV 路径。

    阶段（依据 *is_playing*，通常为 ``is_audio_output_active``）：
    ``generation`` —— 最初 *calibration_ms* 的安静房间设定底噪，触发 = 底噪 x 倍数；
    ``playback`` —— 底噪保持，触发钳制到 ``PLAYBACK_MIN_TRIGGER``，播放起始 *grace_ms*
    抑制瞬态。触发 = 最近 *sustained_ms* 块中 >=80% 超阈值（插话可在生成期间发生，
    不只是 TTS 播放）。捕获则预卷缓冲 + 静音端点，返回 WAV。
    """
    try:
        sd, np = _import_audio()
    except (ImportError, OSError):
        return None

    block = int(SAMPLE_RATE * 0.03)
    calib_blocks = max(1, calibration_ms // 30)
    trip_blocks = max(1, sustained_ms // 30)
    grace_blocks = max(1, grace_ms // 30)
    endpoint_blocks = max(1, endpoint_silence_ms // 30)
    max_blocks = max(1, max_utterance_ms // 30)
    mult = multiplier if isinstance(multiplier, (int, float)) and multiplier > 0 else DEFAULT_BARGE_MULTIPLIER

    is_playing = is_playing or (lambda: False)
    detector = _BargeDetector(np, mult=mult, calib_blocks=calib_blocks, trip_blocks=trip_blocks,
                              grace_blocks=grace_blocks)
    pre_roll: deque = deque(maxlen=max(1, pre_roll_ms // 30))
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=block) as stream:
            while not should_stop():
                data, _ = stream.read(block)
                pre_roll.append(data.copy())
                phase = detector.feed(_rms(np, data), bool(is_playing()))
                if phase is None:
                    continue
                _vad_log(f"full_duplex TRIPPED in {phase} phase — capturing interruption")
                if on_trigger:
                    try:
                        on_trigger(phase)
                    except Exception as e:
                        logger.debug("Full-duplex trigger callback failed: %s", e)
                return _capture_until_quiet(
                    stream, np, block, pre_roll, endpoint_blocks=endpoint_blocks, max_blocks=max_blocks)
    except Exception as e:
        logger.debug("Full-duplex listener failed: %s", e)
    return None


def cleanup_temp_recordings(max_age_seconds: int = 3600) -> int:
    """清理超过 *max_age_seconds* 的旧录音（输出目录内 recording_*）。返回删除数。"""
    from .config import get_output_dir
    removed = 0
    root = get_output_dir()
    try:
        for name in os.listdir(root):
            if not name.startswith("recording_"):
                continue
            full = os.path.join(root, name)
            try:
                if time.time() - os.path.getmtime(full) > max_age_seconds:
                    _unlink_quietly(full)
                    removed += 1
            except OSError:
                continue
    except OSError:
        return 0
    return removed
