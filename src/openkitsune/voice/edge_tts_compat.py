# -*- coding: utf-8 -*-
"""Edge TTS 端点兼容层（迁移自 hermes-agent ``tools/edge_tts_compat.py``，2026-10-12 补丁）。

背景：微软自 2026 年起对经典端点 speech.platform.bing.com 开始大面积返回
HTTP 403（edge-tts GitHub issue #490，影响所有基于 edge-tts 的应用，
暂无上游修复），导致语音合成持续失败（TTS chunk N failed (edge):
403, message='Invalid response status'）。

本补丁将 edge-tts 的 WebSocket 端点切换到微软新服务器
api.msedgeservices.com（同一批语音、同一 TrustedClientToken，
仅参数名与路径不同），实测 1 秒返回音频、音色不变。

用法（由 :func:`openkitsune.voice.tts_providers.generate_edge_tts` 调用）：

    from .edge_tts_compat import patch_edge_tts
    patch_edge_tts(edge_tts_module)

回滚：删除本文件并还原 ``generate_edge_tts`` 中的补丁调用即可。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 新端点（edge-tts-go 已迁移目标）：同一 TrustedClientToken，但作为
# Ocp-Apim-Subscription-Key 传参；无需 Sec-MS-GEC（实测可带）。
EDGE_TTS_NEW_BASE_URL = "api.msedgeservices.com/tts/cognitiveservices"
EDGE_TTS_NEW_WSS_URL = (
    "wss://api.msedgeservices.com/tts/cognitiveservices/websocket/v1"
    "?Ocp-Apim-Subscription-Key=6A5AA1D4EAFF4E9FB37E23D68491D6F4"
)


def patch_edge_tts(edge_tts: Any) -> None:
    """把 edge_tts 模块的 WebSocket 端点切到新服务器（幂等）。

    edge_tts.communicate 以 ``from .constants import WSS_URL`` 方式模块级绑定，
    因此必须同时改写 communicate 模块属性与 constants 模块属性，缺一不可。
    任何一步失败都只记 warning，不阻断原有合成流程。
    """
    try:
        import edge_tts.communicate as comm  # type: ignore[attr-defined]
        import edge_tts.constants as const  # type: ignore[attr-defined]
    except Exception as exc:  # pragma: no cover - 防御性
        logger.warning("edge-tts 端点补丁跳过（无法加载子模块）: %s", exc)
        return

    changed = 0
    for module in (const, comm):
        for attr, value in (
            ("BASE_URL", EDGE_TTS_NEW_BASE_URL),
            ("WSS_URL", EDGE_TTS_NEW_WSS_URL),
        ):
            try:
                if getattr(module, attr, None) != value:
                    setattr(module, attr, value)
                    changed += 1
            except Exception as exc:  # pragma: no cover - 防御性
                logger.debug("edge-tts 端点补丁 %s.%s 设置失败: %s", module.__name__, attr, exc)
    if changed:
        logger.info("edge-tts 端点已切换至新服务器（%s）", EDGE_TTS_NEW_BASE_URL)
