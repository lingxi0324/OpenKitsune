"""Provider-neutral marketplace models and provider adapters.

Marketplace providers expose different identifiers, metrics, and installation
protocols.  This module is the boundary between those provider payloads and the
stable representation consumed by OpenKitsune's API, desktop bridge, and UI.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse

MARKETPLACE_SCHEMA_VERSION = 1
SKILLHUB_PROVIDER = "skillhub"
SKILLHUB_API_BASE = "https://api.skillhub.cn"
SKILLHUB_SKILLS_API = f"{SKILLHUB_API_BASE}/api/skills"
SKILLHUB_DOWNLOAD_API = f"{SKILLHUB_API_BASE}/api/v1/download"

MARKETPLACE_INSTALL_RECORD = ".openkitsune-marketplace.json"


def _read_local_metadata(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as stream:
            data = json.loads(stream.read(1024 * 1024))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def installed_marketplace_names(
    skill_paths: list[str | Path],
    jobs_dir: Path | None = None,
) -> dict[str, str]:
    """Resolve official display names offline, without changing skill identifiers.

    Older installations have no local receipt; recover their names from successful
    installation history only when both resource ID and installed version match.
    """
    if jobs_dir is None:
        from openkitsune.config import settings

        jobs_dir = settings.openkitsune_home / "marketplace" / "jobs"
    history: dict[tuple[str, str], tuple[float, str]] = {}
    for path in jobs_dir.glob("*.json"):
        job = _read_local_metadata(path)
        if job.get("status") != "installed" or job.get("resource_type") != "skill":
            continue
        rid, version, name = (job.get(key) for key in ("resource_id", "version", "resource_name"))
        if not all(isinstance(value, str) and value.strip() for value in (rid, version, name)):
            continue
        stamp = job.get("created_at", 0)
        stamp = stamp if isinstance(stamp, (int, float)) else 0
        key = (rid, version)
        if key not in history or stamp >= history[key][0]:
            history[key] = (stamp, name.strip())

    names = {}
    for skill_path in skill_paths:
        directory = Path(skill_path).parent
        manifest = _read_local_metadata(directory / "manifest.json")
        rid, version = manifest.get("resource_id"), manifest.get("version")
        if (
            manifest.get("resource_type") != "skill"
            or not isinstance(rid, str)
            or not isinstance(version, str)
        ):
            continue
        receipt = _read_local_metadata(directory / MARKETPLACE_INSTALL_RECORD)
        name = receipt.get("resource_name")
        if (
            receipt.get("resource_id") == rid
            and receipt.get("version") == version
            and receipt.get("resource_type") == "skill"
            and isinstance(name, str)
            and name.strip()
        ):
            names[str(skill_path)] = name.strip()
        elif (rid, version) in history:
            names[str(skill_path)] = history[(rid, version)][1]
    return names


def installed_marketplace_resource_id(skill_path: str | Path | None) -> str | None:
    """Read catalog identity from the manifest retained by the official installer.

    This is display metadata, not an entitlement or signature verification.
    Never infer identity from a directory name or the skill's display name.
    """
    if not skill_path:
        return None
    try:
        manifest_path = Path(skill_path).parent / "manifest.json"
        with manifest_path.open(encoding="utf-8") as stream:
            manifest = json.loads(stream.read(1024 * 1024))
        if not isinstance(manifest, dict) or manifest.get("resource_type") != "skill":
            return None
        resource_id = manifest.get("resource_id")
        if isinstance(resource_id, str) and resource_id.strip():
            return resource_id.strip()
    except (OSError, ValueError, TypeError):
        pass
    return None


_COORDINATE_PART_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_VERSION_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")


@dataclass(frozen=True)
class SkillHubLocator:
    """Parsed ``skillhub:`` installation locator."""

    slug: str
    namespace: str | None = None
    version: str | None = None

    @property
    def coordinate(self) -> str:
        if self.namespace:
            return f"@{self.namespace}/{self.slug}"
        return self.slug

    @property
    def canonical_locator(self) -> str:
        return f"skillhub:{self.coordinate}"


def build_skillhub_locator(namespace: str | None, slug: str) -> str:
    """Build a stable SkillHub locator without pinning a version."""
    normalized_namespace = (namespace or "").strip().removeprefix("@") or None
    parsed = SkillHubLocator(slug=slug.strip(), namespace=normalized_namespace)
    _validate_skillhub_locator(parsed)
    return parsed.canonical_locator


def parse_skillhub_locator(value: str) -> SkillHubLocator:
    """Parse ``skillhub:slug`` or ``skillhub:@namespace/slug?version=...``."""
    if not value.startswith("skillhub:"):
        raise ValueError("SkillHub locator must start with 'skillhub:'")

    raw = value.removeprefix("skillhub:").strip()
    coordinate, _, query = raw.partition("?")
    namespace: str | None = None
    slug = coordinate
    if coordinate.startswith("@"):
        namespaced = coordinate.removeprefix("@")
        namespace, separator, slug = namespaced.partition("/")
        if not separator:
            raise ValueError("SkillHub namespaced locator must contain a slug")
    elif "/" in coordinate:
        raise ValueError("SkillHub locator namespaces must start with '@'")

    query_values = parse_qs(query, keep_blank_values=False)
    version = (query_values.get("version") or [None])[0]
    parsed = SkillHubLocator(slug=slug, namespace=namespace, version=version)
    _validate_skillhub_locator(parsed)
    return parsed


def normalize_skillhub_source(value: str) -> str | None:
    """Normalize a SkillHub locator or public detail URL to an installer locator.

    Returns ``None`` for non-SkillHub values so callers can continue their
    existing Git/URL dispatch. Malformed SkillHub values raise ``ValueError``
    instead of silently falling through to a generic downloader.
    """
    source = (value or "").strip()
    if source.startswith("skillhub:"):
        locator = parse_skillhub_locator(source)
        return _locator_with_version(locator)
    if not source.startswith(("http://", "https://")):
        return None

    parsed_url = urlparse(source)
    host = (parsed_url.hostname or "").lower()
    if host not in {"skillhub.cn", "www.skillhub.cn", "api.skillhub.cn"}:
        return None

    query = parse_qs(parsed_url.query, keep_blank_values=False)
    version = (query.get("version") or query.get("v") or [None])[0]
    namespace: str | None = None
    slug = ""
    parts = [unquote(part) for part in parsed_url.path.split("/") if part]

    if host == "api.skillhub.cn" and parts == ["api", "v1", "download"]:
        slug = (query.get("slug") or [""])[0]
        namespace = (query.get("namespace") or [None])[0]
    elif parts and parts[0] == "skills":
        if len(parts) == 2:
            slug = parts[1]
        elif len(parts) == 3:
            namespace, slug = parts[1], parts[2]
    elif host == "api.skillhub.cn" and len(parts) == 2 and parts[0] != "api":
        namespace, slug = parts

    if not slug:
        raise ValueError("Unsupported SkillHub skill URL")
    locator = SkillHubLocator(
        slug=slug,
        namespace=(namespace or "").removeprefix("@") or None,
        version=version,
    )
    _validate_skillhub_locator(locator)
    return _locator_with_version(locator)


def build_skillhub_download_url(locator: SkillHubLocator) -> str:
    """Build the official registry ZIP endpoint for a parsed locator."""
    params = {"slug": locator.slug}
    if locator.namespace:
        params["namespace"] = locator.namespace
    if locator.version:
        params["version"] = locator.version
    return f"{SKILLHUB_DOWNLOAD_API}?{urlencode(params)}"


def resolve_marketplace_install_source(install: dict[str, Any]) -> str:
    """Validate an internal install descriptor and return an installer source."""
    strategy = _string(install.get("strategy"))
    locator_value = _string(install.get("locator"))
    if not locator_value:
        raise ValueError("Marketplace install locator is required")
    if strategy in {"git", "url"}:
        return locator_value
    if strategy != "registry-zip":
        raise ValueError(f"Unsupported marketplace install strategy: {strategy or 'missing'}")
    locator = parse_skillhub_locator(locator_value)

    version = _string(install.get("version")) or locator.version
    if version:
        locator = SkillHubLocator(
            slug=locator.slug,
            namespace=locator.namespace,
            version=version,
        )
        _validate_skillhub_locator(locator)
        return f"{locator.canonical_locator}?{urlencode({'version': version})}"
    return locator.canonical_locator


def normalize_skillhub_response(
    payload: dict[str, Any],
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Convert a SkillHub response to OpenKitsune's marketplace contract."""
    data = payload.get("data")
    if payload.get("code") != 0 or not isinstance(data, dict):
        message = payload.get("message") or "SkillHub returned an invalid response"
        raise ValueError(str(message))

    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list):
        raw_skills = []

    skills: list[dict[str, Any]] = []
    for raw in raw_skills:
        if not isinstance(raw, dict):
            continue
        normalized = _normalize_skillhub_skill(raw)
        if normalized is not None:
            skills.append(normalized)

    total = data.get("total")
    if not isinstance(total, int):
        total = len(skills)
    return {
        "schemaVersion": MARKETPLACE_SCHEMA_VERSION,
        "provider": SKILLHUB_PROVIDER,
        "skills": skills,
        "pagination": {
            "page": page,
            "pageSize": page_size,
            "total": total,
        },
    }


def _normalize_skillhub_skill(raw: dict[str, Any]) -> dict[str, Any] | None:
    slug = _string(raw.get("slug"))
    if not slug:
        return None

    namespace_data = raw.get("namespace")
    if not isinstance(namespace_data, dict):
        namespace_data = {}
    namespace = _string(namespace_data.get("handle")) or None
    try:
        install_locator = build_skillhub_locator(namespace, slug)
    except ValueError:
        return None

    coordinate = install_locator.removeprefix("skillhub:")
    tags = _string_list(raw.get("tags"))
    subcategories = []
    raw_subcategories = raw.get("subCategories")
    if isinstance(raw_subcategories, list):
        for item in raw_subcategories:
            if isinstance(item, dict):
                key = _string(item.get("key"))
                name = _string(item.get("name"))
                if key or name:
                    subcategories.append({"key": key, "name": name})

    labels = raw.get("labels")
    if not isinstance(labels, dict):
        labels = {}
    verified = bool(raw.get("verified"))
    publisher_name = _string(raw.get("ownerName"))
    if not publisher_name:
        publisher_name = _string(namespace_data.get("displayName"))

    return {
        "canonicalId": f"{SKILLHUB_PROVIDER}:{coordinate}",
        "provider": SKILLHUB_PROVIDER,
        "coordinate": {"namespace": namespace, "slug": slug},
        "display": {
            "name": _string(raw.get("name")) or slug,
            "description": _string(raw.get("description_zh")) or _string(raw.get("description")),
            "descriptionI18n": {
                "zh": _string(raw.get("description_zh")),
                "default": _string(raw.get("description")),
            },
            "iconUrl": _string(raw.get("iconUrl")) or None,
        },
        "version": _string(raw.get("version")) or None,
        "publisher": {
            "name": publisher_name or namespace or "unknown",
            "namespace": namespace,
        },
        "classification": {
            "category": _string(raw.get("category")) or None,
            "subcategories": subcategories,
            "tags": tags,
        },
        "metrics": {
            "downloads": _integer(raw.get("downloads")),
            "installs": _integer(raw.get("installs")),
            "stars": _integer(raw.get("stars")),
        },
        "trust": {
            "verified": verified,
            "level": "verified" if verified else "community",
        },
        "requirements": {
            "requiresApiKey": _boolean_label(labels.get("requires_api_key")),
        },
        "source": {
            "kind": "registry",
            "registry": SKILLHUB_PROVIDER,
            "upstreamUrl": _string(raw.get("upstream_url")) or None,
            "homepageUrl": _string(raw.get("homepage")) or None,
        },
        "install": {
            "strategy": "registry-zip",
            "locator": install_locator,
            "version": _string(raw.get("version")) or None,
        },
    }


def _validate_skillhub_locator(locator: SkillHubLocator) -> None:
    if not locator.slug or not _COORDINATE_PART_RE.fullmatch(locator.slug):
        raise ValueError("Invalid SkillHub skill slug")
    if locator.namespace and not _COORDINATE_PART_RE.fullmatch(locator.namespace):
        raise ValueError("Invalid SkillHub namespace")
    if locator.version and not _VERSION_RE.fullmatch(locator.version):
        raise ValueError("Invalid SkillHub skill version")


def _locator_with_version(locator: SkillHubLocator) -> str:
    if locator.version:
        return f"{locator.canonical_locator}?{urlencode({'version': locator.version})}"
    return locator.canonical_locator


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _boolean_label(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return False
