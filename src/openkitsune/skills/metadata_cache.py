"""Disposable, versioned skill metadata snapshots; source files remain authoritative."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

_VERSION = 1
_generation = 0
_cache_paths: set[Path] = set()


def invalidate_metadata_caches() -> None:
    global _generation
    _generation += 1
    for path in tuple(_cache_paths):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


class SkillMetadataCache:
    """Read/write once per discovery pass, never one file per skill."""

    def __init__(self, path: Path):
        self.path = path
        self.generation = _generation
        self.entries: dict[str, Any] = {}
        self.dirty = False
        _cache_paths.add(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("version") == _VERSION and isinstance(payload.get("entries"), dict):
                self.entries = payload["entries"]
        except (OSError, ValueError, AttributeError):
            pass

    def get(self, path: str, signature: tuple[int, ...]) -> dict | None:
        if self.generation != _generation:
            return None
        entry = self.entries.get(path)
        if not isinstance(entry, dict) or entry.get("signature") != list(signature):
            return None
        metadata = entry.get("metadata")
        return metadata if isinstance(metadata, dict) else None

    def put(self, path: str, signature: tuple[int, ...], metadata: dict) -> None:
        self.entries[path] = {"signature": list(signature), "metadata": metadata}
        self.dirty = True

    def flush(self) -> None:
        if not self.dirty or self.generation != _generation:
            return
        temporary = None
        try:
            payload = json.dumps({"version": _VERSION, "entries": self.entries}, ensure_ascii=False)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
            os.replace(temporary, self.path)
        except (OSError, TypeError, ValueError):
            # A read-only workspace or non-JSON YAML extension is a cache miss,
            # never a reason to reject an otherwise valid skill.
            pass
        finally:
            if temporary is not None:
                with suppress(OSError):
                    temporary.unlink(missing_ok=True)
