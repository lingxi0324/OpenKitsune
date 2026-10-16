"""Single-source plugin configuration storage."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openkitsune.utils.atomic_io import atomic_json_write, path_transaction_lock, read_json_safe

logger = logging.getLogger(__name__)


class PluginConfigError(ValueError):
    """The persisted plugin configuration is not a JSON object."""


class PluginConfigStore:
    """Own migration and transactional read-modify-write for one plugin."""

    def __init__(self, config_path: Path, legacy_path: Path | None = None):
        self.config_path = Path(config_path)
        self.legacy_path = Path(legacy_path) if legacy_path is not None else None

    @classmethod
    def for_plugin(cls, plugins_dir: Path, plugin_id: str) -> PluginConfigStore:
        """Build the canonical and legacy paths from the plugin installation root."""
        plugins_dir = Path(plugins_dir)
        return cls(
            plugins_dir.parent / "plugin_data" / plugin_id / "config.json",
            legacy_path=plugins_dir / plugin_id / "config.json",
        )

    @classmethod
    def for_data_dir(
        cls,
        data_dir: Path,
        *,
        legacy_path: Path | None = None,
    ) -> PluginConfigStore:
        """Compatibility factory for callers that already own a plugin data directory."""
        return cls(Path(data_dir) / "config.json", legacy_path=legacy_path)

    @staticmethod
    def _require_object(data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise PluginConfigError("plugin config must be a JSON object")
        return data

    def _read_legacy(self) -> dict[str, Any]:
        assert self.legacy_path is not None
        try:
            data = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise PluginConfigError(f"legacy plugin config is invalid: {exc}") from exc
        return self._require_object(data)

    def _read_locked(self) -> dict[str, Any]:
        if self.config_path.is_file() or self.config_path.with_suffix(
            self.config_path.suffix + ".bak"
        ).is_file():
            data = read_json_safe(self.config_path)
            if data is None:
                raise PluginConfigError("plugin config and backup are unreadable")
            return self._require_object(data)

        if self.legacy_path is None or not self.legacy_path.is_file():
            return {}

        config = self._read_legacy()
        atomic_json_write(self.config_path, config)
        try:
            self.legacy_path.unlink()
        except OSError as exc:
            logger.warning("Legacy plugin config cleanup failed for %s: %s", self.legacy_path, exc)
        return config

    def read(self) -> dict[str, Any]:
        with path_transaction_lock(self.config_path):
            return dict(self._read_locked())

    def update(
        self,
        updates: dict[str, Any],
        *,
        validate: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        with path_transaction_lock(self.config_path):
            config = self._read_locked()
            config.update(updates)
            if validate is not None:
                validate(config)
            atomic_json_write(self.config_path, config)
            return dict(config)
