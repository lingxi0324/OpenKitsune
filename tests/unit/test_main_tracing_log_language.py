import importlib


def test_tracing_enabled_log_is_english(monkeypatch, tmp_path):
    config = importlib.import_module("openkitsune.config")
    monkeypatch.setattr(config.settings, "log_format", "%(message)s")
    monkeypatch.setattr(config.settings, "log_to_console", False)
    monkeypatch.setattr(config.settings, "log_to_file", False)
    main = importlib.import_module("openkitsune.main")

    from openkitsune.tracing import get_tracer, set_tracer

    previous_tracer = get_tracer()
    messages: list[str] = []
    monkeypatch.setattr(main.settings, "tracing_enabled", True)
    monkeypatch.setattr(main.settings, "tracing_console_export", False)
    monkeypatch.setattr(main.settings, "tracing_export_dir", str(tmp_path / "traces"))
    monkeypatch.setattr(main.logger, "info", messages.append)

    try:
        main._init_tracing()
    finally:
        set_tracer(previous_tracer)

    assert messages == ["[Tracing] Tracing system enabled"]
