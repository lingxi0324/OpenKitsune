"""Transactional compression: validate candidates before adopting a new projection."""

import asyncio
import copy
import logging
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps

from openkitsune.runtime.context.continuity import content_digest

logger = logging.getLogger(__name__)


class CompressionError(RuntimeError):
    """Compression cannot safely produce a usable projection."""


@dataclass
class CompressionAttempt:
    conversation_id: str | None
    source_digest: str
    calls: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.monotonic)
    endpoint: str = "unknown"
    quality: str = "validated"
    span: object | None = None


compression_attempt: ContextVar[CompressionAttempt | None] = ContextVar(
    "compression_attempt", default=None
)


async def gather_summaries(coroutines):
    """One failed/cancelled child cancels siblings before any projection is committed."""
    tasks = [asyncio.create_task(coro) for coro in coroutines]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def transactional_compression(method):
    @wraps(method)
    async def wrapped(self, messages, **kwargs):
        source = copy.deepcopy(messages)
        attempt = CompressionAttempt(kwargs.get("conversation_id"), content_digest(source))
        token = compression_attempt.set(attempt)
        status = "failed"
        tokens_before = self.estimate_messages_tokens(source)
        tokens_after = tokens_before
        summary_key = kwargs.get("conversation_id") or "__default__"
        old_summary = self._previous_summaries.get(summary_key)
        adopted = False
        try:
            from openkitsune.sessions.model_transcript import active_transcript

            transcript = active_transcript.get()
            if transcript is not None:
                # The journal owns model projections; legacy checkpoints are import-only.
                kwargs["persist_checkpoint"] = False
            candidate = await method(self, copy.deepcopy(source), **kwargs)
            if transcript is not None:
                candidate = transcript.retain_context(candidate)
            self.validate_projection(candidate, **kwargs)
            tokens_after = self.estimate_messages_tokens(candidate)
            if candidate != source and tokens_after >= tokens_before:
                raise CompressionError("Compression did not reduce the complete projection")
            status = attempt.quality if candidate != source else "unchanged"
            if transcript is not None and candidate != source:
                transcript.pending_compaction = {
                    "source_digest": attempt.source_digest,
                    "quality": status,
                    "summary_endpoint": attempt.endpoint,
                    "calls": attempt.calls,
                    "estimated_summary_tokens": attempt.tokens,
                    "tokens_before": tokens_before,
                    "tokens_after": tokens_after,
                }
            adopted = True
            return candidate
        except CompressionError:
            # Optional compression may fail without destroying a still-usable source.
            # 整改（2026-10-07）：若源上下文本身也超预算，旧逻辑在此二次抛错导致
            # 整轮 500；现在改为截断降级后保留，确保对话不因压缩失败中断。
            try:
                self.validate_projection(source, **kwargs)
            except CompressionError:
                logger.warning(
                    "[Compress] Source also exceeds budget after failed compression; "
                    "degrading projection instead of failing the turn"
                )
                source = self.degrade_projection(source, **kwargs)
            status = "retained_after_failure"
            return source
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError) or type(exc).__name__ == "_CancelledError":
                status = "cancelled"
            raise
        finally:
            if attempt.span is not None:
                from openkitsune.tracing.tracer import get_tracer

                attempt.span.set_attribute("outcome", status)
                get_tracer().end_span(attempt.span)
            if not adopted:
                if old_summary is None:
                    self._previous_summaries.pop(summary_key, None)
                else:
                    self._previous_summaries[summary_key] = old_summary
            logger.info(
                "Compression outcome session=%s source=%s status=%s calls=%s "
                "estimated_tokens=%s endpoint=%s elapsed_ms=%.1f before=%s after=%s",
                attempt.conversation_id,
                attempt.source_digest,
                status,
                attempt.calls,
                attempt.tokens,
                attempt.endpoint,
                (time.monotonic() - attempt.started) * 1000,
                tokens_before,
                tokens_after,
            )
            compression_attempt.reset(token)

    return wrapped


def validated_summary(response, *, structured=False):
    from openkitsune.prompt.compact import format_compact_summary

    if getattr(response, "stop_reason", None) in {"max_tokens", "length"}:
        raise CompressionError("Summary output was truncated")
    text = "".join(b.text for b in response.content if b.type == "text")
    if structured and ("<summary>" not in text or "</summary>" not in text):
        raise CompressionError("Summary is missing its complete body")
    if "<summary>" in text and "</summary>" not in text:
        raise CompressionError("Summary body is incomplete")
    result = format_compact_summary(text)
    if "<analysis>" in result or "</analysis>" in result:
        raise CompressionError("Summary contains an incomplete analysis block")
    if "<summary>" in text:
        cleaned = re.sub(r"<analysis>[\s\S]*?</analysis>", "", text)
        bodies = re.findall(r"<summary>([\s\S]*?)</summary>", cleaned)
        if len(bodies) != 1 or not bodies[0].strip():
            raise CompressionError("Summary must contain exactly one nonempty body")
        result = "摘要:\n" + bodies[0].strip()
    if not result.strip() or result.strip() == "摘要:":
        raise CompressionError("Summary has no usable body")
    return result
