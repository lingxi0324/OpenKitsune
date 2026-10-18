"""Last-mile checks on the actual provider body, after conversion and option merging."""

import hashlib
import json
import logging
from collections import OrderedDict

from openkitsune.core.context_utils import estimate_tokens

logger = logging.getLogger(__name__)
_prefixes: OrderedDict[tuple, list[bytes]] = OrderedDict()


def _estimated_body_tokens(value):
    if isinstance(value, dict):
        kind = value.get("type")
        # Tool schemas can contain a property named "type" or a union type list.
        if isinstance(kind, str):
            if kind in {"image", "image_url", "input_image"}:
                return 1600
            if kind in {"video", "video_url"}:
                return 4800
        return (
            sum(estimate_tokens(str(k)) + _estimated_body_tokens(v) for k, v in value.items()) + 4
        )
    if isinstance(value, list):
        return sum(_estimated_body_tokens(v) for v in value) + 2
    return estimate_tokens(str(value))


def validate_request_body(body: dict, config) -> None:
    from openkitsune.config import settings

    payload = json.dumps(body, ensure_ascii=False, default=str)
    if len(payload.encode()) > 1_800_000:
        raise ValueError("Final provider request exceeds payload byte budget")
    window = config.context_window
    if settings.context_max_window > 0:
        window = min(window, settings.context_max_window) if window else settings.context_max_window
    reserve = (
        body.get("max_output_tokens")
        or body.get("max_completion_tokens")
        or body.get("max_tokens")
        or config.max_tokens
        or 4096
    )
    # [整改 2026-10-10] 输出预留不得超过窗口的合理比例：chat 请求携带的
    # max_tokens（如 16384）打到小窗口端点（如 embedding 8192）时，旧逻辑
    # 会误报 "Final provider request exceeds context window"，直接中断任务。
    # 钳制后由端点本身决定能否生成，校验只负责真实的超限拦截。
    if window:
        reserve = min(reserve, max(window // 4, 1))
    # This is deliberately an estimate. Endpoint usage remains the calibration source.
    estimate = _estimated_body_tokens(body)
    logger.debug(
        "Request budget endpoint=%s estimated_input=%s reserve=%s window=%s bytes=%s",
        config.name,
        estimate,
        reserve,
        window,
        len(payload.encode()),
    )
    if window and estimate + reserve > window:
        raise ValueError("Final provider request exceeds context window including output reserve")
    from openkitsune.core.token_tracking import get_tracking_context

    tracking = get_tracking_context()
    if tracking and tracking.session_id:
        # Hash blocks of the final prompt projection, never log or retain raw content.
        projection = {
            key: body[key]
            for key in ("system", "instructions", "tools", "messages", "input")
            if key in body
        }
        wire = json.dumps(projection, ensure_ascii=False, separators=(",", ":")).encode()
        blocks = [
            hashlib.sha256(wire[i : i + 1024]).digest()
            for i in range(0, len(wire) // 1024 * 1024, 1024)
        ]
        key = (tracking.session_id, tracking.agent_profile_id, config.name, tracking.operation_type)
        previous = _prefixes.get(key, [])
        equal = 0
        for before, after in zip(previous, blocks, strict=False):
            if before != after:
                break
            equal += 1
        logger.debug(
            "Prompt prefix endpoint=%s session=%s matching_full_kib=%s prompt_bytes=%s",
            config.name,
            tracking.session_id,
            equal,
            len(wire),
        )
        _prefixes[key] = blocks
        _prefixes.move_to_end(key)
        while len(_prefixes) > 128:
            _prefixes.popitem(last=False)
