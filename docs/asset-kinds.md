# Asset Kinds — 宿主 Asset Bus 跨插件契约登记

> **Purpose**: central, authoritative registry of every `asset_kind` string
> that crosses the host Asset Bus (`src/openkitsune/plugins/asset_bus.py`).
> When a plugin needs a new kind, it adds a row here in the **same commit**
> that starts producing / consuming it. Consumers treat this file as the
> source of truth for the metadata shape and can hold publishers to the
> documented schema at runtime via `schema_version` checks.
>
> The Asset Bus itself (`docs/asset-bus.md`) purposefully stays schema-less:
> it only knows `asset_kind`, `source_path`, `preview_url`, `duration_sec`,
> `metadata_json`, and ACL fields. All semantic contracts live here.

## How to add a new kind

1. Pick a snake_case string that reads like the **thing** (`subtitle_pack`),
   not like the action (`subtitle_generated`).
2. Bump `schema_version` whenever metadata keys are removed/renamed or
   their type changes. Adding an optional key is a **minor** bump; do not
   re-version for purely additive changes.
3. Document producer, typical consumers, metadata keys, and TTL here.
4. Keep the metadata payload **safe for `shared_with=["*"]`**: no cookies,
   no tokens, no raw user content. Put those in the per-plugin DB.
5. Include a short "downstream invariants" paragraph so consumers know
   what they can rely on (e.g. "`published_url` is either `null` or a
   fully-qualified https URL — never a redirect stub").

## Registered kinds

### `video`

- **Producer**: `clip-sense`
- **Typical consumers**: `omni-post` (as publish source), `media-post`
- **metadata**: `{ duration_sec, resolution, codec, thumbnail_path? }`
- **TTL**: 24h (enough for downstream render + publish window)
- **Notes**: Path points at an `.mp4` in the producer's private data dir.
  Consumers MUST re-hash before trusting (see `docs/asset-bus.md` §7).

### `cover`

- **Producer**: `media-post`
- **Typical consumers**: `omni-post` (paired with `video`)
- **metadata**: `{ width, height, format, source_prompt? }`
- **TTL**: 24h

### `article_draft`

- **Producer**: `idea-research`
- **Typical consumers**: `omni-post` (pre-fills `payload_json.{title, content}`)
- **metadata**: `{ title, word_count, tone?, topic_tags?: string[] }`
- **TTL**: 7 days

### `subtitle_pack`

- **Producer**: `subtitle-craft`
- **Typical consumers**: `omni-post` (attaches as `payload_json.subtitles`),
  `media-post` (burn-in), future `video-editor`
- **metadata**: `{ language, format: "srt"|"vtt", speaker_diarized: bool }`
- **TTL**: 24h

### `publish_receipt` *(new — omni-post S3)*

- **Producer**: `omni-post`
- **Typical consumers**: `fin-pulse` (ROI 归因), `idea-research` (选题复盘),
  `comment-hub` (评论回流), MDRM (发布记忆图谱写入)
- **TTL**: 90 days (long enough to reconcile monetisation cycles, short
  enough to bound the bus)
- **`shared_with`**: `["*"]` — receipts are intentionally public across the
  plugin ecosystem; do **not** put cookies, tokens, or free-form caption
  text in the metadata.
- **`source_path`**: `data/omni-post/receipts/<task_id>.json` — the full
  receipt payload on disk for deep-reading. The in-bus `metadata` mirrors
  the JSON so cheap consumers never need to open the file.

#### metadata schema (schema_version = 1)

```jsonc
{
  "schema_version": 1,

  // Trace identity
  "task_id": "tk-uuid",               // non-null, unique per publish attempt
  "asset_id": "ast-uuid" | null,      // omni-post internal asset_id (not bus id)

  // Target
  "platform": "douyin",               // see omni_post_models.PLATFORMS
  "account_id": "acc-uuid",
  "account_nickname": "xxx" | null,   // hint only; not an auth handle

  // Outcome
  "status": "succeeded" | "failed",
  "error_kind": null | "cookie_expired" | "content_moderated" | …,
  "published_url": "https://…" | null,
  "published_at": "2026-04-24T10:00:00+00:00",

  // Execution metadata
  "engine": "pw" | "mp" | null,
  "retry_count": 0,
  "screenshot_path": "/abs/path/to/<task_id>.png" | null,
  "metrics": {
    "duration_ms": 45123,
    "upload_ms": 22000
    // … engine may add further numeric counters, all optional
  }
}
```

#### downstream invariants

- `task_id` is stable across retries — consumers can dedupe on it.
- `status ∈ {succeeded, failed}` only; running tasks do not emit receipts.
- `published_url`, when present, is fully-qualified and canonical (not a
  tracking / shortened variant).
- `error_kind`, when present, is drawn from `omni_post_models.ErrorKind`.
- `metrics` is a flat string/number/bool dict. No nested structures,
  no strings longer than 256 chars.

#### producer notes

- Receipts are emitted on both terminal success **and** terminal failure
  (retries exhausted or non-retryable). They are never emitted mid-retry.
- The JSON file at `source_path` is written before the bus publish; a
  consumer that sees a bus row is guaranteed the file exists (modulo
  user-initiated disk wipes).
- The plugin does **not** add a new method to `openkitsune-plugin-sdk/`.
  All cross-plugin choreography stays on the host Asset Bus, preserving
  SDK minimalism.
