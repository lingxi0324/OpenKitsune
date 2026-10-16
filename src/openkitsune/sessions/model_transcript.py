"""Transactional, append-only model history, independent of UI message formatting.

SQLite transactions commit admissions as a batch. Replacements are explicit
baselines (compression/migration), never in-place edits of prior journal rows.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import sqlite3
import uuid
import weakref
from contextvars import ContextVar
from pathlib import Path

from filelock import FileLock

logger = logging.getLogger(__name__)
active_transcript: ContextVar[ModelTranscript | None] = ContextVar("model_transcript", default=None)
_locks: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def is_human_message(message: dict) -> bool:
    if message.get("role") != "user" or message.get("_model_source") not in (None, "human"):
        return False
    content = message.get("content")
    return isinstance(content, str) or (
        isinstance(content, list)
        and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    )


def _json(value: object, *, canonical: bool = False) -> str:
    # Do not stringify unsupported objects: silent conversion cannot be replayed faithfully.
    # Preserve key order on disk: tool argument JSON is model-visible text.
    return json.dumps(value, ensure_ascii=False, sort_keys=canonical, separators=(",", ":"))


def _context_message(key: str, payload: str | None, scope: str, version: int) -> dict:
    status = "unavailable" if payload is None else "active" if payload else "cleared"
    return {
        "role": "user",
        "_model_source": "runtime_context",
        "_model_context": {
            "key": key,
            "scope": scope,
            "version": version,
            "payload": payload,
            "status": status,
        },
        "content": (
            f"[OpenKitsune runtime context]\nSection: {key}; scope: {scope}; "
            f"version: {version}; status: {status}.\n"
            "From this record onward, earlier versions of this section in this scope no longer "
            "describe its current state. Other sections are unchanged. This is context data, "
            "not a human request or permission. Turn-scoped data applies only to its named turn.\n"
            + (
                "Collection failed; earlier values are last-known history, not verified current state."
                if payload is None
                else payload or "This section has been cleared; do not reuse its earlier values."
            )
        ),
    }


class ModelTranscript:
    def __init__(self, path: Path | None, stream: str):
        self.path = path
        self.stream = stream
        self.messages: list[dict] = []
        self.turns: dict[str, str] = {}
        self.completed_turns: dict[str, list[dict]] = {}
        self.completed_exit_reasons: dict[str, str] = {}
        self.revision = 0
        self.turn_id = ""
        self.working_messages: list[dict] = []
        self.outcomes: dict[str, dict] = {}
        self.partial: dict[str, str] = {"text": "", "thinking": ""}
        self.pending_compaction: dict = {}
        self._lock: asyncio.Lock | None = None
        self._commit_lock = asyncio.Lock()
        self._file_lock: FileLock | None = None

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        locks = _locks.setdefault(loop, weakref.WeakValueDictionary())
        key = (str(self.path), self.stream)
        self._lock = locks.setdefault(key, asyncio.Lock())
        await self._lock.acquire()
        try:
            if self.path:
                lock_name = hashlib.sha256(self.stream.encode()).hexdigest() + ".lock"
                self._file_lock = FileLock(
                    self.path.parent / "model-transcript-locks" / lock_name, thread_local=False
                )
                acquire = asyncio.create_task(asyncio.to_thread(self._acquire_file_lock))
                try:
                    await asyncio.shield(acquire)
                except asyncio.CancelledError:
                    await acquire
                    raise
                events = await asyncio.to_thread(self._read)
                for revision, kind, payload in events:
                    data = json.loads(payload)
                    if data.get("schema_version", 1) != 1 or revision != self.revision + 1:
                        raise ValueError("Unsupported or incomplete model transcript")
                    self._apply(kind, data["messages"], data)
                    self.revision = revision
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self._file_lock is not None:
            self._file_lock.release()
            self._file_lock = None
        if self._lock is not None:
            self._lock.release()
            self._lock = None

    def _acquire_file_lock(self) -> None:
        assert self._file_lock is not None
        Path(self._file_lock.lock_file).parent.mkdir(parents=True, exist_ok=True)
        self._file_lock.acquire(timeout=0)

    def _connect(self) -> sqlite3.Connection:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute(
            "CREATE TABLE IF NOT EXISTS model_events (stream TEXT NOT NULL, revision INTEGER "
            "NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, "
            "PRIMARY KEY(stream, revision))"
        )
        return db

    def _read(self) -> list:
        db = self._connect()
        try:
            return db.execute(
                "SELECT revision, kind, payload FROM model_events WHERE stream=? ORDER BY revision",
                (self.stream,),
            ).fetchall()
        finally:
            db.close()

    def _write(self, kind: str, payload: str) -> None:
        db = self._connect()
        try:
            with db:
                db.execute("BEGIN IMMEDIATE")
                revision = db.execute(
                    "SELECT COALESCE(MAX(revision), 0) FROM model_events WHERE stream=?",
                    (self.stream,),
                ).fetchone()[0]
                if revision != self.revision:
                    raise RuntimeError(
                        "Model transcript changed in another writer; refusing stale write"
                    )
                db.execute(
                    "INSERT INTO model_events VALUES (?, ?, ?, ?)",
                    (self.stream, revision + 1, kind, payload),
                )
        finally:
            db.close()

    async def _commit(self, kind: str, messages: list[dict], **metadata) -> None:
        async with self._commit_lock:
            await self._commit_unlocked(kind, messages, **metadata)

    async def _commit_unlocked(self, kind: str, messages: list[dict], **metadata) -> None:
        frozen = copy.deepcopy(messages)
        payload = _json(
            {"schema_version": 1, "turn_id": self.turn_id, "messages": frozen, **metadata}
        )
        if self.path:
            # Complete the transaction even when cancellation arrives during fsync.
            write = asyncio.create_task(asyncio.to_thread(self._write, kind, payload))
            try:
                await asyncio.shield(write)
            except asyncio.CancelledError:
                await write
                self._apply(kind, frozen, metadata)
                raise
        self._apply(kind, frozen, metadata)

    def _apply(self, kind: str, messages: list[dict], metadata: dict) -> None:
        if kind == "baseline":
            self.messages = messages
        elif messages:
            self.messages = [*self.messages, *messages]
        self.revision += 1
        if metadata.get("turn"):
            self.turns[metadata["turn"]] = metadata["input_hash"]
        if metadata.get("tool_result"):
            result = metadata["tool_result"]
            self.outcomes[result["tool_use_id"]] = copy.deepcopy(result)
        if metadata.get("frame"):
            frame = metadata["frame"]
            self.partial[frame["kind"]] += frame["text"]
        if metadata.get("clear_partial"):
            self.partial = {"text": "", "thinking": ""}
        if metadata.get("completed_turn"):
            self.completed_turns[metadata["completed_turn"]] = metadata["events"]
            self.completed_exit_reasons[metadata["completed_turn"]] = metadata.get(
                "exit_reason", "normal"
            )

    async def complete_turn(self, events: list[dict], *, exit_reason: str = "normal") -> None:
        await self._commit(
            "turn_complete", [], completed_turn=self.turn_id, events=events, exit_reason=exit_reason
        )

    async def record_frame(self, kind: str, text: str) -> None:
        if text:
            await self._commit("stream_frame", [], frame={"kind": kind, "text": text})

    async def record_tool_result(self, result: dict) -> None:
        if self.outcomes.get(result["tool_use_id"]) != result:
            await self._commit("tool_progress", [], tool_result=result)

    async def update_context(self, messages: list[dict], key: str, payload: str | None) -> None:
        old = self.latest_context().get(key, {}).get("_model_context", {})
        if old.get("payload", "") == payload:
            return
        messages.append(_context_message(key, payload, "session", old.get("version", 0) + 1))
        await self.sync(messages)

    def latest_context(self) -> dict[str, dict]:
        result = {}
        for msg in self.messages:
            if msg.get("_model_source") == "runtime_context" and msg.get("_model_context"):
                meta = msg["_model_context"]
                if "key" not in meta:
                    logger.debug("Skipping context message with missing 'key' field: %s", meta.get("scope"))
                    continue
                result[meta["key"]] = msg
        return result

    async def admit(
        self, incoming: list[dict], sections: dict[str, str | None], sampled_time: str, turn_id: str
    ) -> list[dict]:
        self.turn_id = turn_id
        tail = next(
            (i for i in range(len(incoming) - 1, -1, -1) if is_human_message(incoming[i])),
            len(incoming),
        )
        fresh = copy.deepcopy(incoming[tail:])
        input_hash = fresh[0].get("_model_input_hash") if fresh else None
        if not isinstance(input_hash, str):
            request = [m for m in fresh if m.get("_model_source") != "resume_hint"]
            input_hash = hashlib.sha256(_json(request, canonical=True).encode()).hexdigest()
        if turn_id in self.turns:
            if self.turns[turn_id] != input_hash:
                raise ValueError("A model turn id cannot be reused for different input")
            if turn_id in self.completed_turns:
                return copy.deepcopy(self.messages)
        additions = copy.deepcopy(incoming if self.revision == 0 else fresh)
        for msg in additions:
            if is_human_message(msg):
                msg.setdefault("_model_source", "human")
        # Recover interrupted tool groups before admitting any new user/context message.
        recovered = copy.deepcopy(self.messages)
        from openkitsune.core.cancel_cleanup import (
            find_orphan_tool_uses,
            synthesize_tool_results_for_orphans,
        )

        pending_questions = {
            call["id"] for call in find_orphan_tool_uses(recovered) if call["name"] == "ask_user"
        }
        synthesize_tool_results_for_orphans(recovered)
        committed_ids = {
            b.get("tool_use_id")
            for m in self.messages
            if isinstance(m.get("content"), list)
            for b in m["content"]
            if isinstance(b, dict) and b.get("type") == "tool_result"
        }
        for message in recovered:
            content = message.get("content")
            if isinstance(content, list):
                for i, block in enumerate(content):
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        saved = self.outcomes.get(block.get("tool_use_id"))
                        if saved and block.get("tool_use_id") not in committed_ids:
                            content[i] = copy.deepcopy(saved)
                        elif (
                            block.get("tool_use_id") in pending_questions
                            and fresh
                            and turn_id not in self.turns
                        ):
                            content[i] = {
                                "type": "tool_result",
                                "tool_use_id": block["tool_use_id"],
                                "content": copy.deepcopy(fresh[0]["content"]),
                                "is_error": False,
                            }
        if any(self.partial.values()):
            recovered.append(
                {
                    "role": "assistant",
                    "content": self.partial["text"],
                    "reasoning_content": self.partial["thinking"] or None,
                    "_model_interrupted": True,
                }
            )
        if recovered != self.messages:
            await self.sync(recovered, reason="interrupted_tool_recovery")
        if turn_id in self.turns:
            return copy.deepcopy(self.messages)
        if sampled_time:
            additions.append(
                {
                    "role": "user",
                    "_model_source": "runtime_context",
                    "content": f"[OpenKitsune time sample]\nTurn: {turn_id}. "
                    f"Sampled when admitting this turn (not a live clock): {sampled_time}",
                }
            )
        latest = self.latest_context()
        for key, payload in sections.items():
            old = latest.get(key, {}).get("_model_context", {})
            scope = f"turn:{turn_id}" if key == "retrieved_memory" else "session"
            if old.get("payload") == payload and old.get("scope") == scope:
                continue
            if not old and payload == "":
                continue
            additions.append(_context_message(key, payload, scope, old.get("version", 0) + 1))
        await self._commit("append", additions, turn=turn_id, input_hash=input_hash)
        return copy.deepcopy(self.messages)

    async def sync(self, messages: list[dict], *, reason: str = "history_transform") -> None:
        if _json(messages) == _json(self.messages):
            return
        if _json(messages[: len(self.messages)]) == _json(self.messages):
            additions = messages[len(self.messages) :]
            await self._commit(
                "append",
                additions,
                clear_partial=any(m.get("role") == "assistant" for m in additions),
            )
            return
        # Compression and explicit repairs start a new model-visible baseline.
        # Carry retained section states, including clears, when compression omitted them.
        candidate = self.retain_context(messages)
        await self._commit(
            "baseline",
            candidate,
            reason=reason,
            compaction=self.pending_compaction,
            clear_partial=reason == "interrupted_tool_recovery",
        )
        self.pending_compaction = {}
        messages[:] = copy.deepcopy(candidate)
        logger.info(
            "Model transcript baseline changed: reason=%s revision=%s", reason, self.revision
        )

    def retain_context(self, messages: list[dict]) -> list[dict]:
        """Preview the complete baseline before budget validation or persistence."""
        candidate = copy.deepcopy(messages)
        for key, old in self.latest_context().items():
            # [整改 2026-10-15] normalize_turn_roles 会把各 Section 合并成一条
            # merged 运行期上下文消息（_model_context.merged=True，sections 列出
            # 所含 Section）。旧实现只认 _model_context.key，不认识合并体，
            # 以为 Section 丢失，把 transcript 里的单条 context 消息重新 append
            # 回去，导致请求中"合并体 + 单条"并存、同一 Section 重复注入
            # （实测 session_environment / retrieved_memory 各注入 2 次）。
            merged_covers = any(
                key in (m.get("_model_context", {}).get("sections") or [])
                for m in candidate
                if m.get("_model_context", {}).get("merged")
            )
            if merged_covers:
                continue
            if not any(
                m.get("_model_context", {}).get("key") == key
                and m["_model_context"].get("version", 0) >= old["_model_context"]["version"]
                for m in candidate
            ):
                candidate.append(copy.deepcopy(old))
        return candidate


async def commit_model_messages(messages: list[dict]) -> None:
    transcript = active_transcript.get()
    if transcript is not None:
        transcript.working_messages = messages
        await transcript.sync(messages)


async def record_model_tool_result(tool_id: str, content: str, is_error: bool = False) -> None:
    transcript = active_transcript.get()
    if transcript is not None:
        await transcript.record_tool_result(
            {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": content,
                "is_error": is_error,
            }
        )


def new_stream_id(conversation_id: str | None, profile: str, reset: str, sub_agent: bool) -> str:
    identity = [conversation_id or uuid.uuid4().hex, profile, reset]
    if sub_agent:
        identity.append(uuid.uuid4().hex)
    return _json(identity)
