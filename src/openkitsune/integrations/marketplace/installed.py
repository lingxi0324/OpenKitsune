"""Read installed Marketplace identity from the actual workspace, not job history."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

from openkitsune.config import settings
from openkitsune.utils.atomic_io import read_json_safe


def inspect_installation(job: dict[str, Any]) -> dict[str, Any]:
    kind = job["resource_type"]
    slug = job["resource_slug"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", slug):
        raise ValueError("Invalid resource slug")
    if kind == "skill":
        root, marker = settings.skills_path, "SKILL.md"
    elif kind == "plugin":
        root, marker = settings.project_root / "data" / "plugins", "plugin.json"
    elif kind == "mcp":
        root, marker = settings.mcp_config_path, "SERVER_METADATA.json"
    else:
        raise ValueError("Unsupported resource type")
    root = Path(root).resolve()
    target = root / slug
    candidates = [target]
    if root.is_dir():
        candidates += sorted(path for path in root.iterdir() if path != target and path.is_dir())
    pending: set[Path] = set()
    if kind == "plugin":
        state = read_json_safe(settings.project_root / "data" / "plugin_state.json") or {}
        updates = (settings.project_root / "data" / "plugin-updates").resolve()
        for plugin_id, entry in state.get("plugins", {}).items():
            if not (root / plugin_id / marker).is_file():
                continue
            raw = entry.get("pending_update_path")
            if not raw:
                continue
            path = Path(raw).resolve()
            if path.is_relative_to(updates) and path.is_dir():
                pending.add(path)
                candidates.insert(0, path)

    found = None
    manifest: dict[str, Any] = {}
    for path in candidates:
        if not path.is_dir() or (path not in pending and not path.resolve().is_relative_to(root)):
            continue
        data = read_json_safe(path / "manifest.json")
        if (
            isinstance(data, dict)
            and data.get("resource_id") == job["resource_id"]
            and data.get("resource_type") == kind
            and (path / marker).is_file()
        ):
            found, manifest = path, data
            break

    action, version = "install", ""
    if found is not None:
        version = str(manifest.get("version") or "")
        try:
            current, requested = Version(version), Version(str(job["version"]))
            action = (
                "already_installed" if current == requested
                else "upgrade" if current < requested else "downgrade"
            )
        except InvalidVersion:
            action = "replace"
    elif target.exists():
        found, action = target, "replace"

    # The preview is valid only for this installation. A second job, manual
    # removal, or workspace switch must not silently change a confirmed action.
    fingerprint: list[Any] = [str(root), str(found), action, version]
    if found is not None:
        fingerprint.append(found.stat().st_mtime_ns)
        for name in ("manifest.json", marker):
            path = found / name
            if path.is_file():
                fingerprint.append([name, path.stat().st_mtime_ns, path.stat().st_size])
        fingerprint.append(manifest)
    snapshot = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    plugin_manifest = read_json_safe(found / marker) if kind == "plugin" and found else None
    return {
        "install_action": action,
        "installed_version": version or None,
        "installed_pending_restart": found in pending,
        **({"plugin_id": plugin_manifest.get("id")} if isinstance(plugin_manifest, dict) else {}),
        "_installation_snapshot": snapshot,
        "_installation_scope": str(root),
    }
