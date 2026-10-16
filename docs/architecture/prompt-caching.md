# Prompt caching and usage accounting

OpenKitsune keeps common rules, safety instructions and the compiled identity at
the beginning of its generated system prompt. FULL-only behavior, persona and
mode instructions follow the shared prefix. Switching between FULL and MINIMAL
therefore preserves the common prefix, rather than inserting extra rules ahead
of the identity. Changes to the identity or model-specific base prompt can still
change that prefix.

`DYNAMIC_BOUNDARY` marks the end of the shared prefix for providers that support
explicit cache blocks. It does not itself enable caching on DeepSeek.

The builder transports versioned context candidates between
`TURN_CONTEXT_BOUNDARY` and `TURN_CONTEXT_END`. The session layer consumes this
envelope before reasoning. Runtime instructions, project policies, ask-user
continuation rules, contradiction guards and appended agent or plan policies
remain system instructions. Adapters perform protocol conversion only; they
never temporarily insert a context snapshot.

Chat Completions, Responses and Anthropic use the same admitted model history:

```text
system: shared instructions + current mode/runtime/tool policies
user/assistant/tool: committed previous history, including old context records
user: current request
user: [OpenKitsune time sample] sampled once for this turn
user: [OpenKitsune runtime context] changed sections only
assistant/tool: committed tool continuation, if any
```

`SessionManager.open_model_transcript` acquires a stream writer. Transactional
events in `data/model-transcripts.sqlite3` preserve model messages separately
from UI history. Normal replies, tool results, interrupted stream text, context
records and admission keys survive restarts. Same-process writers serialize;
an OS file lock rejects a competing process. SQLite also checks the expected
revision before appending. Blocking storage operations run in worker threads.

Session environment, working facts and user profile are session-scoped. Equal
values produce no record; changes increment the section version. An empty
value explicitly clears that section. A null candidate means unavailable, not
empty. Retrieved memory is turn-scoped: its old text remains historical evidence,
but a new turn needs an explicit activation even if the evidence is identical.
Diagnostic message counts are excluded. Time is separate from state comparison;
tool steps and retries do not refresh it. A time-sensitive long task can obtain
a new observation through a tool rather than treating an old sample as a live clock.

Context messages carry an internal source marker. They cannot be mistaken for
human input or approval. System instructions define section replacement and
scope. Plugin context is appended on change rather than editing the last user
message. Tool call/result groups remain adjacent.

Reusing an admission id with the same input replays the committed admission;
completed turns replay their saved response without a second model call.
Different input under the same id is rejected. Session resets and recreated
sessions have separate history generations; delegated invocations have separate
streams. Existing sessions migrate their available history once. Legacy
cancel-resume files are consumed only when no model transcript exists.

Compression and explicit history repairs append a new baseline. The latest
section states, including clears and unavailable states, are carried into it.
UI cleanup, timestamp formatting and text merging no longer reconstruct earlier
model messages on normal subsequent turns. Inline media and opaque provider
metadata are preserved; tool argument key order is preserved on disk because
argument JSON becomes model-visible text.

Custom unmarked prompts are unchanged. Mode-specific rules, tool schemas,
plans, provider/model changes, compaction and provider cache persistence/eviction
can still cause misses. Real improvements require repeated API measurements;
offline prefix tests do not predict a hit percentage. The event journal retains
old baseline data on disk; compression reduces model input, not journal size.

See [durable model context](durable-model-context.md) for semantics and acceptance
criteria, and `tests/unit/test_model_transcript.py` for executable regressions.

## Usage counters

All three Chat Completions response paths (non-streaming, usage-only streaming
chunks and finish chunks) use the same parser. DeepSeek's
`prompt_cache_hit_tokens` is read alongside the OpenAI-compatible
`prompt_tokens_details.cached_tokens` and `cached_tokens` variants. The raw
DeepSeek hit field takes precedence when present, including an explicit zero.

For OpenAI Chat Completions and Responses, input tokens already include cache
reads. Cache reads are a subset, so costs charge ordinary input prices only for
`input - cache_read`, and token budgets count input once. Anthropic retains its
separate uncached-input and cache counters. Compiler endpoint calls use their
own endpoint configuration for accounting. Historical database rows are not
rewritten or backfilled when their original usage fields are unavailable.

For DeepSeek, the input cache-hit ratio is:

```text
sum(cache_read_tokens) / sum(input_tokens)
```

Output tokens are excluded from the denominator. For meaningful comparisons,
separate main replies from intent analysis, retrieval and other background calls.

References: [DeepSeek context caching](https://api-docs.deepseek.com/guides/kv_cache/),
[Chat Completions usage fields](https://api-docs.deepseek.com/api/create-chat-completion/).
