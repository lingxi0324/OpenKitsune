from __future__ import annotations

from pathlib import Path

from openkitsune.api.server import _select_web_dist


def _write_web_dist(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "index.html").write_text("<html></html>", encoding="utf-8")


def test_select_web_dist_prefers_development_build_when_both_exist(tmp_path: Path) -> None:
    pkg_web = tmp_path / "src" / "openkitsune" / "web"
    dev_web = tmp_path / "apps" / "setup-center" / "dist-web"
    _write_web_dist(pkg_web)
    _write_web_dist(dev_web)

    assert _select_web_dist(pkg_web=pkg_web, dev_web=dev_web) == dev_web


def test_select_web_dist_falls_back_to_package_assets(tmp_path: Path) -> None:
    pkg_web = tmp_path / "src" / "openkitsune" / "web"
    dev_web = tmp_path / "apps" / "setup-center" / "dist-web"
    _write_web_dist(pkg_web)

    assert _select_web_dist(pkg_web=pkg_web, dev_web=dev_web) == pkg_web


def test_select_web_dist_returns_none_when_assets_are_missing(tmp_path: Path) -> None:
    assert _select_web_dist(
        pkg_web=tmp_path / "src" / "openkitsune" / "web",
        dev_web=tmp_path / "apps" / "setup-center" / "dist-web",
    ) is None
