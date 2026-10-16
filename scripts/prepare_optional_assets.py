#!/usr/bin/env python3
"""Resolve optional feature artifacts for OSS mirroring.

Providers are adapters that turn a repository catalog entry into immutable
upstream URLs.  The output inventory is consumed by the release workflow,
which checks OSS before downloading anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlparse

_PLAYWRIGHT_HEADER = re.compile(r"^(.+?) \(playwright (.+?) v([^\)]+)\)$")
_PLAYWRIGHT_URL = re.compile(r"^\s*Download (?:url|fallback \d+):\s+(https?://\S+)\s*$")


def parse_playwright_dry_run(output: str) -> list[dict]:
    artifacts: list[dict] = []
    current: dict | None = None
    for line in output.splitlines():
        header = _PLAYWRIGHT_HEADER.match(line.strip())
        if header:
            current = {
                "name": header.group(1),
                "component": header.group(2),
                "revision": header.group(3),
                "sources": [],
            }
            continue
        url_match = _PLAYWRIGHT_URL.match(line)
        if url_match and current is not None:
            current["sources"].append(url_match.group(1))
            if len(current["sources"]) == 1:
                artifacts.append(current)
    return artifacts


def _playwright_artifacts(feature: dict) -> tuple[str, list[dict]]:
    from playwright._impl._driver import compute_driver_executable

    node, cli = compute_driver_executable()
    resolved: dict[str, dict] = {}
    for platform_name in feature["platforms"]:
        env = dict(os.environ)
        env["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = platform_name
        env.pop("PLAYWRIGHT_DOWNLOAD_HOST", None)
        result = subprocess.run(
            [str(node), str(cli), "install", "--dry-run", *feature["install_args"]],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        for artifact in parse_playwright_dry_run(result.stdout):
            upstream_path = urlparse(artifact["sources"][0]).path
            marker = "/builds/"
            if marker not in upstream_path:
                raise ValueError(f"Unsupported Playwright artifact URL: {upstream_path}")
            relative_path = "builds/" + upstream_path.split(marker, 1)[1]
            object_path = f"{feature['mirror_path'].strip('/')}/{relative_path}"
            entry = resolved.setdefault(
                object_path,
                {
                    **artifact,
                    "object_path": object_path,
                    "relative_path": relative_path,
                    "platforms": [],
                },
            )
            entry["platforms"].append(platform_name)
            for source in artifact["sources"]:
                if source not in entry["sources"]:
                    entry["sources"].append(source)
    return version("playwright"), list(resolved.values())


def _python_wheel_artifacts(feature: dict, lock_path: Path) -> tuple[str, list[dict]]:
    with open(lock_path, "rb") as lock_file:
        lock = tomllib.load(lock_file)
    package_name = feature["package"]
    package = next(
        (item for item in lock.get("package", []) if item.get("name") == package_name),
        None,
    )
    if not isinstance(package, dict):
        raise ValueError(f"Package {package_name!r} was not found in {lock_path}")
    package_version = str(package["version"])
    wheels = package.get("wheels") or []
    artifacts: list[dict] = []
    for platform_name, suffix in feature["platforms"].items():
        wheel = next(
            (
                item
                for item in wheels
                if isinstance(item, dict) and str(item.get("url", "")).endswith(suffix)
            ),
            None,
        )
        if not isinstance(wheel, dict):
            raise ValueError(f"No {package_name} wheel ending in {suffix!r}")
        upstream_url = str(wheel["url"])
        filename = upstream_url.rsplit("/", 1)[-1]
        hash_value = str(wheel.get("hash") or "")
        sha256 = hash_value.removeprefix("sha256:")
        object_path = f"{feature['mirror_path'].strip('/')}/{package_version}/{filename}"
        artifacts.append(
            {
                "name": filename,
                "component": package_name,
                "revision": package_version,
                "object_path": object_path,
                "relative_path": f"{package_version}/{filename}",
                "platforms": [platform_name],
                "platform": platform_name,
                "sources": [upstream_url],
                "upstream_url": upstream_url,
                "sha256": sha256,
                "size": int(wheel.get("size") or 0),
            }
        )
    return package_version, artifacts


def prepare(
    catalog: dict,
    cdn_base_url: str,
    *,
    lock_path: Path = Path("uv.lock"),
    existing_manifest: dict | None = None,
) -> tuple[dict, dict]:
    inventory: list[dict] = []
    public_features: dict[str, dict] = {}
    for feature in catalog.get("features", []):
        provider = feature.get("provider")
        if provider == "playwright":
            provider_version, artifacts = _playwright_artifacts(feature)
        elif provider == "python_lock_wheel":
            provider_version, artifacts = _python_wheel_artifacts(feature, lock_path)
        else:
            raise ValueError(f"Unsupported optional asset provider: {provider}")
        inventory.extend({"feature_id": feature["id"], **item} for item in artifacts)
        mirror_base = f"{cdn_base_url.rstrip('/')}/{feature['mirror_path'].strip('/')}"
        public_feature = {
            "provider": provider,
            "provider_version": provider_version,
            "strategy": feature["strategy"],
            "mirror_base_url": mirror_base,
            "platforms": feature["platforms"],
            "artifacts": [
                {
                    "name": item["name"],
                    "component": item["component"],
                    "revision": item["revision"],
                    "path": item["relative_path"],
                    "platforms": item["platforms"],
                }
                for item in artifacts
            ],
        }
        if provider == "python_lock_wheel":
            previous_feature = (existing_manifest or {}).get("features", {}).get(feature["id"], {})
            versions = dict(previous_feature.get("versions") or {})
            versions[provider_version] = {
                "artifacts": [
                    {
                        "name": item["name"],
                        "platform": item["platform"],
                        "size": item["size"],
                        "sha256": item["sha256"],
                        "path": item["object_path"],
                        "mirror_url": f"{cdn_base_url.rstrip('/')}/{item['object_path']}",
                        "upstream_url": item["upstream_url"],
                    }
                    for item in artifacts
                ]
            }
            public_feature["versions"] = versions
        public_features[feature["id"]] = public_feature
    generated_at = datetime.now(UTC).isoformat()
    return (
        {"schema_version": 1, "generated_at": generated_at, "artifacts": inventory},
        {"schema_version": 1, "generated_at": generated_at, "features": public_features},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--cdn-base-url", required=True)
    parser.add_argument("--lock", default="uv.lock")
    parser.add_argument("--existing-manifest", default="")
    args = parser.parse_args()

    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    existing_manifest = None
    if args.existing_manifest:
        existing_manifest = json.loads(Path(args.existing_manifest).read_text(encoding="utf-8"))
    inventory, manifest = prepare(
        catalog,
        args.cdn_base_url,
        lock_path=Path(args.lock),
        existing_manifest=existing_manifest,
    )
    for path, payload in ((args.inventory, inventory), (args.manifest, manifest)):
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(f"Resolved {len(inventory['artifacts'])} optional artifact(s)")


if __name__ == "__main__":
    main()
