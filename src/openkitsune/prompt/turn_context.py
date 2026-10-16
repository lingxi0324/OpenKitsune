"""Versioned transport for context candidates, consumed before message admission."""

from __future__ import annotations

import json

from openkitsune.llm.cache import SYSTEM_PROMPT_CONTEXT_BOUNDARY, SYSTEM_PROMPT_CONTEXT_END

CONTEXT_FORMAT = "openkitsune.context.v1"


def encode_context(sections: dict[str, str | None], sampled_time: str) -> str:
    return json.dumps(
        {"format": CONTEXT_FORMAT, "time": sampled_time, "sections": sections},
        ensure_ascii=False,
    )


def extract_context(prompt: str) -> tuple[str, dict[str, str | None], str]:
    """Leave unmarked prompts and appended policies intact; never parse prose headings."""
    if SYSTEM_PROMPT_CONTEXT_BOUNDARY not in prompt:
        return prompt, {}, ""
    prefix, remainder = prompt.split(SYSTEM_PROMPT_CONTEXT_BOUNDARY, 1)
    body, end, suffix = remainder.rpartition(SYSTEM_PROMPT_CONTEXT_END)
    if not end:
        return prompt, {}, ""
    # Builder separators surround the envelope, but are not part of its JSON.
    body = body.strip().removeprefix("---").removesuffix("---").strip()
    try:
        value = json.loads(body)
    except (ValueError, TypeError):
        value = None
    if isinstance(value, dict) and value.get("format") == CONTEXT_FORMAT:
        sections = value.get("sections")
        if not isinstance(sections, dict) or not all(
            isinstance(k, str) and (isinstance(v, str) or v is None) for k, v in sections.items()
        ):
            raise ValueError("Invalid context candidates")
        return prefix.rstrip() + suffix, sections, str(value.get("time") or "")
    # Migration for callers still supplying the former marked text format.
    return prefix.rstrip() + suffix, {"legacy_context": body}, ""
