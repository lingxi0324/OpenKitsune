from __future__ import annotations

import json
import os
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

import pytest


class _FakeDownloadResponse(BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False


def _skillhub_zip(*, skill_md: str = "---\nname: demo\n---\n# Demo\n") -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", skill_md)
        archive.writestr("references/usage.md", "# Usage\n")
    return buffer.getvalue()


def test_install_skillhub_registry_package_records_canonical_origin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    from openkitsune.setup_center import bridge

    archive = _skillhub_zip()
    requested_urls: list[str] = []

    def fake_urlopen(request, timeout=0):
        requested_urls.append(request.full_url)
        assert timeout == 30
        return _FakeDownloadResponse(archive)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    bridge.install_skill(
        str(tmp_path),
        "https://skillhub.cn/skills/community_demo/demo?version=1.2.3",
    )

    target = tmp_path / "skills" / "demo"
    assert (target / "SKILL.md").is_file()
    assert (target / "references" / "usage.md").is_file()
    assert (target / ".openkitsune-source").read_text(encoding="utf-8") == (
        "skillhub:@community_demo/demo"
    )
    origin = json.loads((target / ".openkitsune-origin.json").read_text(encoding="utf-8"))
    assert origin == {
        "provider": "skillhub",
        "locator": "skillhub:@community_demo/demo",
        "namespace": "community_demo",
        "slug": "demo",
        "version": "1.2.3",
    }
    assert requested_urls == [
        "https://api.skillhub.cn/api/v1/download?slug=demo&namespace=community_demo&version=1.2.3"
    ]

    capsys.readouterr()
    bridge.list_skills(str(tmp_path))
    listed = json.loads(capsys.readouterr().out)
    installed = next(skill for skill in listed["skills"] if skill["skill_id"] == "demo")
    assert installed["source_url"] == "skillhub:@community_demo/demo"


def test_install_skillhub_registry_package_rejects_zip_slip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from openkitsune.setup_center import bridge

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("SKILL.md", "---\nname: demo\n---\n")
        archive.writestr("../outside.txt", "unsafe")

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=0: _FakeDownloadResponse(buffer.getvalue()),
    )

    with pytest.raises(RuntimeError, match="Zip Slip"):
        bridge.install_skill(str(tmp_path), "skillhub:demo")

    assert not (tmp_path / "outside.txt").exists()
    assert not (tmp_path / "skills" / "demo").exists()
    assert not list((tmp_path / "skills").glob(".openkitsune-skillhub-*"))


def test_git_proxy_validation_rejects_malformed_fullwidth_proxy(monkeypatch: pytest.MonkeyPatch):
    from openkitsune.setup_center import bridge

    monkeypatch.setenv("ALL_PROXY", "htpp：//127.0.0.1:7897")

    with pytest.raises(bridge.SkillInstallError) as exc:
        bridge._validate_git_proxy_environment(os.environ.copy())

    assert exc.value.code == "git_proxy_invalid"
    assert "代理配置格式错误" in exc.value.message


def test_install_github_repo_copies_from_temp_without_git_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from openkitsune.setup_center import bridge

    def fake_git_clone(args: list[str]) -> None:
        clone_dir = Path(args[-1])
        clone_dir.mkdir(parents=True)
        (clone_dir / ".git").mkdir()
        (clone_dir / ".git" / "HEAD").write_text("ref: refs/heads/main", encoding="utf-8")
        (clone_dir / "SKILL.md").write_text(
            "---\nname: demo\ndescription: demo\n---\n# Demo\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(bridge, "_has_git", lambda: True)
    monkeypatch.setattr(bridge, "_git_clone", fake_git_clone)

    bridge.install_skill(str(tmp_path), "https://github.com/acme/demo")

    target = tmp_path / "skills" / "demo"
    assert (target / "SKILL.md").exists()
    assert not (target / ".git").exists()
    assert (target / ".openkitsune-source").read_text(encoding="utf-8") == (
        "https://github.com/acme/demo"
    )


def test_broken_residual_skill_dir_is_quarantined_when_delete_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from openkitsune.setup_center import bridge

    skills_dir = tmp_path / "skills"
    broken = skills_dir / "broken"
    broken.mkdir(parents=True)
    (broken / ".git").mkdir()

    def fail_remove(_: Path, *, retries: int = 3) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(bridge, "_remove_tree", fail_remove)
    bridge._ensure_target_available(broken, "github:owner/broken")

    assert not broken.exists()
    quarantined = list((skills_dir / ".openkitsune-broken").glob("broken-*"))
    assert len(quarantined) == 1
    assert (quarantined[0] / ".git").exists()


def test_shorthand_install_rechecks_target_after_failed_platform_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from openkitsune.setup_center import bridge

    def fake_platform_cache(_: str, dest_dir: Path) -> bool:
        dest_dir.mkdir(parents=True)
        (dest_dir / ".git").mkdir()
        return False

    def fake_git_clone(args: list[str]) -> None:
        clone_dir = Path(args[-1])
        skill_dir = clone_dir / "skills" / "demo"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: demo\ndescription: demo\n---\n# Demo\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(bridge, "_try_platform_skill_download", fake_platform_cache)
    monkeypatch.setattr(bridge, "_has_git", lambda: True)
    monkeypatch.setattr(bridge, "_git_clone", fake_git_clone)

    bridge.install_skill(str(tmp_path), "owner/repo@demo")

    target = tmp_path / "skills" / "demo"
    assert (target / "SKILL.md").exists()
    assert not (target / ".git").exists()
