#!/usr/bin/env python3
"""Reject mutable or commit-mismatched GitHub releases before packaging."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote

JsonFetcher = Callable[[str, bool], dict[str, Any] | None]


def _gh_json(endpoint: str, allow_not_found: bool = False) -> dict[str, Any] | None:
    result = subprocess.run(
        ["gh", "api", endpoint],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode == 0:
        return json.loads(result.stdout)
    error = (result.stderr or result.stdout).strip()
    if allow_not_found and ("HTTP 404" in error or "Not Found" in error):
        return None
    raise RuntimeError(f"GitHub API request failed for {endpoint}: {error[:500]}")


def _resolve_tag_commit(repo: str, tag: str, fetch_json: JsonFetcher) -> str:
    encoded_tag = quote(tag, safe="")
    ref = fetch_json(f"repos/{repo}/git/ref/tags/{encoded_tag}", False)
    if ref is None:
        raise RuntimeError(f"tag {tag!r} does not exist")
    obj = ref.get("object") or {}
    for _ in range(5):
        obj_type = str(obj.get("type") or "")
        sha = str(obj.get("sha") or "")
        if obj_type == "commit" and sha:
            return sha
        if obj_type != "tag" or not sha:
            break
        tag_obj = fetch_json(f"repos/{repo}/git/tags/{sha}", False)
        if tag_obj is None:
            break
        obj = tag_obj.get("object") or {}
    raise RuntimeError(f"tag {tag!r} does not resolve to a commit")


def check_release_contract(
    *,
    repo: str,
    tag: str,
    expected_commit: str,
    release_id: int | None = None,
    asset_names: Sequence[str] = (),
    require_release: bool = False,
    wait_seconds: int = 0,
    fetch_json: JsonFetcher = _gh_json,
) -> None:
    """Validate tag provenance and reject any release asset collision."""
    if not tag.startswith("v"):
        raise RuntimeError(f"release tag must start with 'v', got {tag!r}")
    tag_commit = _resolve_tag_commit(repo, tag, fetch_json)
    if tag_commit.lower() != expected_commit.lower():
        raise RuntimeError(
            f"tag {tag!r} points to {tag_commit}, but the build checkout is {expected_commit}"
        )

    release: dict[str, Any] | None
    if release_id is not None:
        if release_id <= 0:
            raise RuntimeError(f"release ID must be positive, got {release_id}")
        release = fetch_json(f"repos/{repo}/releases/{release_id}", False)
        if release is None:
            raise RuntimeError(f"release ID {release_id} does not exist")
        release_tag = str(release.get("tag_name") or "")
        if release_tag != tag:
            raise RuntimeError(
                f"release ID {release_id} belongs to tag {release_tag!r}, expected {tag!r}"
            )
    else:
        encoded_tag = quote(tag, safe="")
        deadline = time.monotonic() + max(0, wait_seconds)
        while True:
            release = fetch_json(f"repos/{repo}/releases/tags/{encoded_tag}", True)
            if release is not None or not require_release or time.monotonic() >= deadline:
                break
            time.sleep(2)

    if release is None:
        if require_release:
            raise RuntimeError(f"release {tag!r} does not exist after waiting {wait_seconds}s")
        return

    existing = {str(asset.get("name") or "") for asset in release.get("assets") or []}
    conflicts = sorted(existing.intersection(asset_names) if asset_names else existing)
    if conflicts:
        joined = ", ".join(conflicts)
        raise RuntimeError(
            f"release {tag!r} already contains immutable assets: {joined}. "
            "Publish a new version instead of replacing them."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub repository in owner/name form")
    parser.add_argument("--tag", required=True, help="Release tag to validate")
    parser.add_argument("--expected-commit", required=True, help="Full checkout commit SHA")
    parser.add_argument("--release-id", type=int, help="Numeric GitHub Release ID")
    parser.add_argument(
        "--asset-name",
        action="append",
        default=[],
        help="Reject only this existing asset name; omit to reject every existing asset",
    )
    parser.add_argument("--require-release", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()

    try:
        check_release_contract(
            repo=args.repo,
            tag=args.tag,
            expected_commit=args.expected_commit,
            release_id=args.release_id,
            asset_names=args.asset_name,
            require_release=args.require_release,
            wait_seconds=args.wait_seconds,
        )
    except Exception as exc:
        print(f"[ERROR] release contract failed: {exc}", file=sys.stderr)
        return 1
    print(f"[OK] release contract passed for {args.tag} at {args.expected_commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
