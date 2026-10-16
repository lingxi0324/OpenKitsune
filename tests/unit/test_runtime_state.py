"""L1 Unit Tests: RuntimeState persistence."""

import json
import threading

import pytest

from openkitsune.config import RuntimeState


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "runtime_state.json"


class TestRuntimeState:
    def test_default_creation(self, state_file):
        state = RuntimeState(state_file=state_file)
        assert isinstance(state, RuntimeState)

    def test_save_and_load(self, state_file):
        state = RuntimeState(state_file=state_file)
        state.save()
        assert state_file.exists()

        state2 = RuntimeState(state_file=state_file)
        state2.load()

    def test_load_nonexistent_file(self, tmp_path):
        state = RuntimeState(state_file=tmp_path / "missing.json")
        state.load()  # Should not crash

    def test_state_file_is_json(self, state_file):
        state = RuntimeState(state_file=state_file)
        state.save()
        content = state_file.read_text(encoding="utf-8")
        data = json.loads(content)
        assert isinstance(data, dict)

    def test_save_propagates_atomic_write_failure(self, state_file, monkeypatch):
        from openkitsune.utils import atomic_io

        state = RuntimeState(state_file=state_file)
        monkeypatch.setattr(
            atomic_io,
            "atomic_json_write",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(OSError, match="disk full"):
            state.save()

    def test_save_updates_rolls_back_settings_when_write_fails(self, state_file, monkeypatch):
        from openkitsune.config import settings
        from openkitsune.utils import atomic_io

        state = RuntimeState(state_file=state_file)
        monkeypatch.setattr(settings, "ui_theme", "light")
        monkeypatch.setattr(
            atomic_io,
            "atomic_json_write",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
        )

        with pytest.raises(OSError, match="disk full"):
            state.save_updates(ui_theme="dark")

        assert settings.ui_theme == "light"

    def test_save_updates_serializes_snapshot_and_write_across_threads(
        self, state_file, monkeypatch
    ):
        from openkitsune.config import settings
        from openkitsune.utils import atomic_io

        state = RuntimeState(state_file=state_file)
        monkeypatch.setattr(settings, "ui_theme", "system")
        first_write_entered = threading.Event()
        release_first_write = threading.Event()
        writes: list[str] = []

        def controlled_write(_path, data, **_kwargs):
            writes.append(data["ui_theme"])
            if len(writes) == 1:
                first_write_entered.set()
                assert release_first_write.wait(timeout=2)

        monkeypatch.setattr(atomic_io, "atomic_json_write", controlled_write)
        first = threading.Thread(target=state.save_updates, kwargs={"ui_theme": "light"})
        second = threading.Thread(target=state.save_updates, kwargs={"ui_theme": "dark"})

        first.start()
        assert first_write_entered.wait(timeout=2)
        second.start()
        assert writes == ["light"]
        release_first_write.set()
        first.join(timeout=2)
        second.join(timeout=2)

        assert not first.is_alive()
        assert not second.is_alive()
        assert writes == ["light", "dark"]
        assert settings.ui_theme == "dark"

    def test_separate_instances_merge_updates_from_latest_disk_state(
        self, state_file, monkeypatch
    ):
        from openkitsune.config import settings

        monkeypatch.setattr(settings, "ui_theme", "system")
        monkeypatch.setattr(settings, "ui_language", "zh")
        first = RuntimeState(state_file=state_file)
        second = RuntimeState(state_file=state_file)

        first.save_updates(ui_theme="dark")
        second.save_updates(ui_language="en")

        saved = json.loads(state_file.read_text(encoding="utf-8"))
        assert saved["ui_theme"] == "dark"
        assert saved["ui_language"] == "en"
        assert settings.ui_theme == "dark"
        assert settings.ui_language == "en"

    def test_save_updates_does_not_apply_unrelated_disk_changes_locally(
        self, state_file, monkeypatch
    ):
        from openkitsune.config import settings

        monkeypatch.setattr(settings, "ui_theme", "light")
        monkeypatch.setattr(settings, "ui_language", "zh")
        state_file.write_text(
            json.dumps({"ui_theme": "dark", "ui_language": "zh"}),
            encoding="utf-8",
        )

        RuntimeState(state_file=state_file).save_updates(ui_language="en")

        saved = json.loads(state_file.read_text(encoding="utf-8"))
        assert saved["ui_theme"] == "dark"
        assert saved["ui_language"] == "en"
        assert settings.ui_theme == "light"
        assert settings.ui_language == "en"

    def test_load_rejects_invalid_snapshot_without_partial_mutation(
        self, state_file, monkeypatch
    ):
        from openkitsune.config import settings

        monkeypatch.setattr(settings, "ui_theme", "light")
        monkeypatch.setattr(settings, "memory_nudge_interval", 5)
        state_file.write_text(
            json.dumps({"ui_theme": "dark", "memory_nudge_interval": "invalid"}),
            encoding="utf-8",
        )

        RuntimeState(state_file=state_file).load()

        assert settings.ui_theme == "light"
        assert settings.memory_nudge_interval == 5
