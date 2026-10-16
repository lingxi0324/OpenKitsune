# Context compression safety

Compression works on a private candidate projection. A nonempty string alone is
not a successful summary: text must survive formatting, structured chunk summaries
must contain one complete nonempty summary body, and truncated model output is
rejected. Thinking content is never substituted for the summary.

If compression fails, the previous projection remains usable only if it fits the
request budget. Otherwise the turn fails explicitly. Durable conversations do not
fall back to deleting old groups or blindly clipping tool evidence. This trades
some automatic continuation for preservation of constraints and completed actions.
Cancellation stops sibling summary calls and cannot create a completed projection.

## Ownership and recovery

The model transcript owns adopted projections after migration. Preparing a turn
with an existing transcript skips compression of the UI history. Legacy checkpoints
remain supported on first import; their early-return compression paths also save
the adopted projection, and checkpoint replay uses independent copies.

Normal and overflow compression use the same transaction. A journal baseline
records the source digest, quality status, endpoint and estimated compression cost.
The journal retains earlier events. State snapshots are restored into a candidate
before budget validation, rather than appended after a supposedly final token count.

Tool outputs moved to memory storage are owned by the active memory session,
including when its normalized ID differs from the visible conversation ID.
`read_file(path="memory://tool-output/<id>", offset=1, limit=8000)` reads bounded
character pages, with a maximum of 16,000 characters. These parameters count
characters for memory URIs and lines for ordinary files. Missing, expired or
inaccessible references return an explicit unavailable result; no unscoped lookup
is attempted. Blob lifetime follows the existing memory-store lifecycle.

## Evidence and task state

Microcompact does not infer equality from content prefixes or erase evidence by
age. Deduplication requires identical full content, tool arguments and error state,
and only replaces evidence when a durable read reference remains available.
Otherwise it keeps the original result. The normal durable loop does not run
microcompact on every request.

Recent tool groups and the latest human request are protected. Oversized tool
results may become deterministic previews only after saving their full content.
Historical tool arguments are not rewritten into invented summary arguments.
Summary and task-orientation messages have explicit sources and do not overwrite
state snapshots or become human input. Summaries distinguish unfinished authorized
work from completed operations, revoked goals and superseded decisions. External
tool content is evidence, never an additional user authorization. Sensitive values
should remain controlled references rather than be copied into summary templates.

## Limits and observation

Summary calls inherit the conversation route. Chunk sizing reserves prompt,
previous-summary, URL-list and output space; oversized individual messages are
split, and multiple chunks receive a final state consolidation. Two calls may run
concurrently. Per-attempt limits are configurable:

| Setting | Default |
| --- | --- |
| `context_summary_max_calls` | 12 |
| `context_summary_max_tokens` | 120,000 estimated input plus output reserve |
| `context_summary_timeout_seconds` | 60 seconds total |
| `context_summary_failure_threshold` | 2 consecutive failures |
| `context_summary_backoff_seconds` | 60 seconds |

Backoff is isolated by conversation, endpoint and source digest. Cancellation does
not count as an endpoint failure. Local limits supplement the existing client rate
limiter and bounded task recovery; they do not create another retry loop.

After orientation injection the complete projection is checked again. Anthropic,
OpenAI Chat Completions and Responses validate the final converted request body,
including tools, provider options, output reserve and payload bytes. Token counts
are estimates, with separate media estimates; provider errors and actual usage
remain relevant for calibration. An impossible budget produces an error rather
than a claim that truncation succeeded.

Compression logs contain outcome, source digest, before/after estimates, call
count, endpoint and duration. Provider logs report final estimated request size and
matching full 1-KiB blocks of the prompt projection; only hashes are retained for
this diagnostic. This is a local prefix measure, not a provider cache-hit rate.
Existing usage tracking remains the source for reported cache reads/writes. Real
cache savings and semantic fidelity require a fixed task-set evaluation with live
endpoints; local regressions do not establish those results.
