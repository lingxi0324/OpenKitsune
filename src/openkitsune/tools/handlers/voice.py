"""
语音处理器

处理语音相关的工具调用:
- text_to_speech:   文本合成语音
- transcribe_audio: 音频转写文本
- voice_record:     麦克风录音（VAD）
- voice_listen:     持续监听说话（Barge-in）

# ApprovalClass checklist (新增 / 修改工具时必读)
# 1. 在本文件 Handler 类的 TOOLS 列表加新工具名
# 2. 在同 Handler 类的 TOOL_CLASSES 字典加 ApprovalClass 显式声明
#    （或在 agent.py:_init_handlers 的 register() 调用里加 tool_classes={...}）
# 3. 行为依赖参数 → 在 policy_v2/classifier.py:_refine_with_params 加分支
# 4. 跑 pytest tests/unit/test_classifier_completeness.py 验证
# 详见 docs/policy_v2_research.md §4.21
"""

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ...core.policy_v2 import ApprovalClass

if TYPE_CHECKING:
    from ...agent.core import Agent

logger = logging.getLogger(__name__)


class VoiceHandler:
    """语音处理器：TTS 合成 / STT 转写 / VAD 录音与监听"""

    TOOLS = ["text_to_speech", "transcribe_audio", "voice_record", "voice_listen"]
    TOOL_CLASSES = {
        "text_to_speech": ApprovalClass.INTERACTIVE,
        "transcribe_audio": ApprovalClass.INTERACTIVE,
        "voice_record": ApprovalClass.INTERACTIVE,
        "voice_listen": ApprovalClass.INTERACTIVE,
    }

    def __init__(self, agent: "Agent"):
        self.agent = agent

    async def handle(self, tool_name: str, params: dict[str, Any]) -> str:
        """处理工具调用"""
        if tool_name == "text_to_speech":
            return await self._text_to_speech(params)
        elif tool_name == "transcribe_audio":
            return await self._transcribe_audio(params)
        elif tool_name == "voice_record":
            return await self._voice_record(params)
        elif tool_name == "voice_listen":
            return await self._voice_listen(params)
        return f"❌ Unknown voice tool: {tool_name}"

    # ── text_to_speech ──
    async def _text_to_speech(self, params: dict) -> str:
        """文本合成语音（同步引擎在线程池执行）。"""
        from ...voice import synthesize_text

        text = params.get("text", "")
        if not text or not text.strip():
            return "❌ 缺少待朗读文本 (text)"

        provider = params.get("provider")
        output_path = params.get("output_path")
        voice_compatible = bool(params.get("voice_compatible"))
        fmt = params.get("format")

        try:
            import asyncio

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: synthesize_text(
                    text,
                    provider=provider,
                    output_path=output_path,
                    voice_compatible=voice_compatible,
                    format=fmt,
                ),
            )
        except Exception as e:
            logger.warning(f"[Voice] TTS failed: {e}", exc_info=True)
            return f"❌ 语音合成失败: {e}"

        paths = result["paths"]
        if not paths:
            return "❌ 语音合成未产生输出文件"

        # 单文件直接交付
        if len(paths) == 1:
            return self._build_audio_receipt(str(paths[0]), result["provider"])

        # 多文件（长文本分块）逐个交付
        receipts = []
        for path in paths:
            receipts.append(json.loads(self._build_audio_receipt(path, result["provider"])))
        return json.dumps({"ok": True, "channel": "desktop", "receipts": receipts}, ensure_ascii=False)

    @staticmethod
    def _build_audio_receipt(path: str, provider: str) -> str:
        """构造与 deliver_artifacts desktop 回执相同格式的 JSON（audio 类型）。"""
        import urllib.parse

        resolved = Path(path).resolve()
        abs_path = str(resolved)
        file_url = f"/api/files?path={urllib.parse.quote(abs_path, safe='')}"

        return json.dumps(
            {
                "ok": True,
                "channel": "desktop",
                "receipts": [
                    {
                        "index": 0,
                        "status": "delivered",
                        "type": "audio",
                        "path": abs_path,
                        "file_url": file_url,
                        "caption": "",
                        "name": f"tts_{provider}",
                        "size": resolved.stat().st_size if resolved.exists() else 0,
                        "channel": "desktop",
                    }
                ],
            },
            ensure_ascii=False,
        )

    # ── transcribe_audio ──
    async def _transcribe_audio(self, params: dict) -> str:
        """音频转写文本（STT 在线程池执行）。"""
        from ...voice import transcribe_audio

        audio_path = params.get("audio_path", "")
        if not audio_path or not os.path.isfile(audio_path):
            return f"❌ 音频文件不存在: {audio_path}"

        language = params.get("language")

        try:
            import asyncio

            text = await asyncio.get_event_loop().run_in_executor(
                None, lambda: transcribe_audio(audio_path, language=language)
            )
        except Exception as e:
            logger.warning(f"[Voice] STT failed: {e}", exc_info=True)
            return f"❌ 语音识别失败: {e}"

        if not text:
            return "❌ 语音识别失败：未获得转写文本（检查 stt 配置或音频内容）"

        return text

    # ── voice_record ──
    async def _voice_record(self, params: dict) -> str:
        """麦克风录音 + VAD（静音自动停止）。"""
        from ...voice import AudioRecorder, create_audio_recorder

        output_path = params.get("output_path")

        recorder = create_audio_recorder()
        stop_event = __import__("threading").Event()

        def _on_silence():
            stop_event.set()

        try:
            recorder.start(on_silence_stop=_on_silence)
        except Exception as e:
            return f"❌ 无法启动录音（检查麦克风与 sounddevice 依赖）: {e}"

        # 等待静音自动停止或超时（30s 兜底）
        stop_event.wait(timeout=30.0)
        try:
            wav_path = recorder.stop()
        finally:
            recorder.shutdown()

        if not wav_path:
            return "❌ 未录到有效语音（录音过短或过安静）"

        # 用户指定输出路径则移动
        if output_path:
            dest = Path(output_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(wav_path, str(dest))
                wav_path = str(dest)
            except OSError as e:
                logger.warning(f"[Voice] Could not move recording: {e}")

        return self._build_audio_receipt(wav_path, "record")

    # ── voice_listen ──
    async def _voice_listen(self, params: dict) -> str:
        """持续监听说话（Barge-in 抢话检测）。"""
        from ...voice import listen_for_speech

        capture = bool(params.get("capture"))
        timeout = float(params.get("timeout") or 15.0)
        output_path = params.get("output_path")

        stop_event = __import__("threading").Event()
        deadline = __import__("time").monotonic() + timeout

        def _should_stop():
            return __import__("time").monotonic() >= deadline or stop_event.is_set()

        import asyncio

        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: listen_for_speech(_should_stop, capture=capture),
        )

        if not capture:
            return "✅ 检测到语音（抢话触发）" if result else "⏱️ 超时未检测到语音"

        if not result:
            return "⏱️ 超时未检测到语音"

        if output_path:
            dest = Path(output_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(result, str(dest))
                result = str(dest)
            except OSError as e:
                logger.warning(f"[Voice] Could not move capture: {e}")

        return self._build_audio_receipt(result, "capture")


def create_handler(agent: "Agent"):
    """创建语音处理器"""
    handler = VoiceHandler(agent)
    return handler.handle
