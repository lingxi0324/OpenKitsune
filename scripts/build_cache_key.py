#!/usr/bin/env python3
"""Compute stable cache fingerprints for expensive desktop build outputs."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

INPUTS = {
    "rust": (
        "apps/setup-center/src",
        "apps/setup-center/index.html",
        "apps/setup-center/package.json",
        "apps/setup-center/package-lock.json",
        "apps/setup-center/vite.config.ts",
        "apps/setup-center/tsconfig.json",
        "apps/setup-center/src-tauri/Cargo.toml",
        "apps/setup-center/src-tauri/Cargo.lock",
        "apps/setup-center/src-tauri/build.rs",
        "apps/setup-center/src-tauri/src",
        "apps/setup-center/src-tauri/capabilities",
        "apps/setup-center/src-tauri/icons",
        "apps/setup-center/src-tauri/tauri.conf.json",
        "apps/setup-center/src-tauri/Entitlements.plist",
        "src/openkitsune/optional_modules.json",
        "identity",
        "data/llm_endpoints.json.example",
        "scripts/build_cache_key.py",
        "scripts/prepare_tauri_binary.py",
    ),
}


def _git_available() -> bool:
    """git 仓库可用性探测（解压目录/CI 外等无 git 环境应优雅降级而非报错）。"""
    try:
        subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _collect_by_glob(inputs: tuple[str, ...]) -> list[Path]:
    """无 git 时的确定性回退：按输入路径直接收集（目录递归、文件直取），
    排序基于仓库相对路径，保证指纹跨环境稳定。"""
    found: set[Path] = set()
    for rel in inputs:
        p = (ROOT / rel).resolve()
        if p.is_dir():
            for child in p.rglob("*"):
                if child.is_file():
                    found.add(child)
        elif p.is_file():
            found.add(p)
    return sorted(found, key=lambda path: path.relative_to(ROOT).as_posix())


def _tracked_files(inputs: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    if _git_available():
        try:
            output = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(ROOT),
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "-z",
                    "--",
                    *inputs,
                ],
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            files = sorted(
                (ROOT / item.decode()).resolve()
                for item in output.split(b"\0")
                if item
            )
            files = [path for path in files if path.is_file()]
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("git ls-files 失败，退化为 glob 收集: %s", exc)
            files = []
    if not files:
        files = _collect_by_glob(inputs)
    return files


def _add_file(digest: Any, path: Path) -> None:
    relative = path.relative_to(ROOT).as_posix().encode()
    digest.update(len(relative).to_bytes(4, "big"))
    digest.update(relative)
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)


def _rust_environment() -> list[str]:
    rustc = subprocess.check_output(["rustc", "-Vv"], text=True, encoding="utf-8")
    return [rustc, os.environ.get("CARGO_BUILD_TARGET", "native")]


def fingerprint(kind: str) -> str:
    digest = hashlib.sha256()
    files = _tracked_files(INPUTS[kind])
    if not files:
        raise RuntimeError(f"no tracked inputs found for {kind}")
    for path in files:
        _add_file(digest, path)
    environment = _rust_environment()
    for value in environment:
        digest.update(b"\0env\0")
        digest.update(value.encode())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=sorted(INPUTS))
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    value = fingerprint(args.kind)
    if args.github_output:
        output = os.environ.get("GITHUB_OUTPUT")
        if not output:
            raise RuntimeError("GITHUB_OUTPUT is not set")
        with Path(output).open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"fingerprint={value}\n")
    print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
