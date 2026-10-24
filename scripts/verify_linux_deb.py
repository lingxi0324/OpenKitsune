#!/usr/bin/env python3
"""Check the packaged Linux launcher and exercise URI delivery through GIO.

Only the launcher is exercised, with a harmless argument recorder substituted
for the application. No installed associations, accounts or resources change.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAURI_DIR = ROOT / "apps" / "setup-center" / "src-tauri"
DEEP_LINK_SCHEME = "openkitsune"


def verify_deb(package: Path) -> None:
    config = json.loads((TAURI_DIR / "tauri.conf.json").read_text(encoding="utf-8"))
    binary = config["mainBinaryName"]
    with tempfile.TemporaryDirectory(prefix="openkitsune-deb-check-") as directory:
        work = Path(directory)
        subprocess.run(["dpkg-deb", "--extract", str(package), str(work / "root")], check=True)
        desktop = work / "root/usr/share/applications" / f"{config['productName']}.desktop"
        source = desktop.read_text(encoding="utf-8")
        entry = configparser.ConfigParser(interpolation=None)
        entry.optionxform = str
        entry.read_string(source)
        launcher = entry["Desktop Entry"]
        command = shlex.split(launcher["Exec"])
        if command != [binary, "%u"]:
            raise ValueError(f"{package.name}: Exec must forward one URL: {launcher['Exec']!r}")
        if f"x-scheme-handler/{DEEP_LINK_SCHEME}" not in launcher.get("MimeType", "").split(";"):
            raise ValueError(f"{package.name}: missing {DEEP_LINK_SCHEME} URI association")
        if launcher.get("Type") != "Application" or not (work / "root/usr/bin" / binary).is_file():
            raise ValueError(f"{package.name}: launcher does not point to the packaged application")

        # Use the actual packaged desktop entry. Replace only its executable so
        # the test cannot open the app or consume a real deep-link instruction.
        output = work / "argv.json"
        probe = work / "argument recorder"
        probe.write_text(
            "#!/usr/bin/env python3\nimport json, pathlib, sys\n"
            f"output = pathlib.Path({str(output)!r})\n"
            "pending = output.with_suffix('.tmp')\n"
            "pending.write_text(json.dumps(sys.argv[1:]))\n"
            "pending.replace(output)\n",
            encoding="utf-8",
        )
        probe.chmod(0o755)
        launcher["Exec"] = f'"{probe}" %u'
        test_desktop = work / "probe.desktop"
        with test_desktop.open("w", encoding="utf-8") as stream:
            entry.write(stream, space_around_delimiters=False)
        uri = (
            f"{DEEP_LINK_SCHEME}://verify/deb-handoff?token=packaging-probe"
            "&endpoint=https%3A%2F%2Fexample.com%2Fhandoff&state=a%20b%26c"
        )
        env = os.environ.copy()
        env.pop("GIO_LAUNCHED_DESKTOP_FILE", None)
        subprocess.run(["gio", "launch", str(test_desktop), uri], check=True, env=env)
        deadline = time.monotonic() + 10
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not output.exists() or json.loads(output.read_text()) != [uri]:
            raise ValueError(
                f"{package.name}: GIO did not deliver the complete URL as one argument"
            )
        print(
            f"Verified {package.name}: packaged executable, URI association, full GIO URL delivery"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="*", type=Path, help="DEB files to verify")
    parser.add_argument("--target", default="", help="Optional Rust target triple")
    args = parser.parse_args()
    release = TAURI_DIR / "target" / args.target / "release"
    packages = args.packages or sorted((release / "bundle/deb").glob("*.deb"))
    if not packages:
        parser.error(f"No DEB packages found under {release / 'bundle/deb'}")
    for package in packages:
        verify_deb(package.resolve())


if __name__ == "__main__":
    main()
