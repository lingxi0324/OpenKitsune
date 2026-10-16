"""Resolve accelerated download sources for optional OpenKitsune features.

The public manifest is deliberately declarative: it may select a mirror for a
locally-known installer strategy, but it cannot supply commands for OpenKitsune
to execute.  New optional features can reuse this resolver while keeping their
installation logic in the owning module.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urljoin, urlparse

DEFAULT_OPTIONAL_ASSET_MANIFEST = "https://dl-openkitsune.fzstack.com/api/optional-assets.json"
_MANIFEST_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class OptionalAssetMirror:
    feature_id: str
    strategy: str
    base_url: str


def _valid_base_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


@lru_cache(maxsize=4)
def _fetch_manifest(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OpenKitsune optional-assets"},
    )
    with urllib.request.urlopen(request, timeout=_MANIFEST_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("optional asset manifest must be a JSON object")
    return payload


def resolve_optional_asset_mirror(
    feature_id: str,
    *,
    strategy: str,
    mirror_path: str,
) -> OptionalAssetMirror | None:
    """Return the preferred mirror for a locally-known optional feature.

    ``OPENKITSUNE_OPTIONAL_ASSET_MIRROR`` overrides the public manifest and is
    interpreted as the root that contains ``mirror_path``.  The manifest URL
    itself can be overridden with ``OPENKITSUNE_OPTIONAL_ASSET_MANIFEST``.
    Resolution failures are intentionally non-fatal so callers can use their
    upstream source.
    """

    override_root = _valid_base_url(os.environ.get("OPENKITSUNE_OPTIONAL_ASSET_MIRROR"))
    if override_root:
        base_url = urljoin(f"{override_root}/", mirror_path.strip("/"))
        return OptionalAssetMirror(feature_id, strategy, base_url.rstrip("/"))

    manifest_url = os.environ.get(
        "OPENKITSUNE_OPTIONAL_ASSET_MANIFEST", DEFAULT_OPTIONAL_ASSET_MANIFEST
    ).strip()
    if not _valid_base_url(manifest_url):
        return None
    try:
        manifest = _fetch_manifest(manifest_url)
    except Exception:
        return None

    features = manifest.get("features")
    feature = features.get(feature_id) if isinstance(features, dict) else None
    if not isinstance(feature, dict) or feature.get("strategy") != strategy:
        return None
    base_url = _valid_base_url(feature.get("mirror_base_url"))
    if not base_url:
        return None
    return OptionalAssetMirror(feature_id, strategy, base_url)


def load_optional_asset_feature(feature_id: str) -> dict | None:
    """Load one declarative feature entry from the optional asset manifest."""

    manifest_url = os.environ.get(
        "OPENKITSUNE_OPTIONAL_ASSET_MANIFEST", DEFAULT_OPTIONAL_ASSET_MANIFEST
    ).strip()
    if not _valid_base_url(manifest_url):
        return None
    try:
        manifest = _fetch_manifest(manifest_url)
    except Exception:
        return None
    features = manifest.get("features")
    feature = features.get(feature_id) if isinstance(features, dict) else None
    return dict(feature) if isinstance(feature, dict) else None
