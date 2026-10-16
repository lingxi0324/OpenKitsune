"""L2 Component Tests: SelfChecker test case loading and report generation."""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from openkitsune.evolution.log_analyzer import ErrorPattern, LogEntry
from openkitsune.evolution.self_check import SelfChecker, SelfCheckPromptUnavailableError


@pytest.fixture
def mock_brain():
    brain = MagicMock()
    brain.max_tokens = 4096
    return brain


class TestSelfCheckerInit:
    def test_create_with_brain(self, mock_brain):
        checker = SelfChecker(brain=mock_brain)
        assert checker is not None

    def test_create_with_test_dir(self, mock_brain, tmp_path):
        test_dir = tmp_path / "test_cases"
        test_dir.mkdir()
        checker = SelfChecker(brain=mock_brain, test_dir=test_dir)
        assert checker is not None


class TestLoadTestCases:
    def test_load_builtin_cases(self, mock_brain):
        checker = SelfChecker(brain=mock_brain)
        count = checker.load_test_cases()
        assert isinstance(count, int)
        assert count >= 0

    def test_load_from_custom_dir(self, mock_brain, tmp_path):
        test_dir = tmp_path / "custom_tests"
        test_dir.mkdir()
        checker = SelfChecker(brain=mock_brain, test_dir=test_dir)
        count = checker.load_test_cases()
        assert isinstance(count, int)


class TestReportManagement:
    def test_get_pending_report_when_none(self, mock_brain):
        checker = SelfChecker(brain=mock_brain)
        report = checker.get_pending_report()
        # May be None or a string
        assert report is None or isinstance(report, str)


class TestSelfCheckResilience:
    def test_workspace_prompt_takes_precedence(self, mock_brain, tmp_path, monkeypatch):
        prompt_path = tmp_path / "prompts" / "selfcheck_system.md"
        prompt_path.parent.mkdir()
        prompt_path.write_text("workspace selfcheck policy", encoding="utf-8")
        monkeypatch.setattr("openkitsune.config.settings.project_root", tmp_path)

        checker = SelfChecker(brain=mock_brain)

        assert checker._load_selfcheck_system_prompt() == "workspace selfcheck policy"

    def test_bundled_prompt_is_used_without_workspace_override(
        self,
        mock_brain,
        tmp_path,
        monkeypatch,
    ):
        workspace_root = tmp_path / "workspace"
        package_root = tmp_path / "package" / "openkitsune"
        bundled_prompt = package_root / "prompts" / "selfcheck" / "system.md"
        workspace_root.mkdir()
        bundled_prompt.parent.mkdir(parents=True)
        bundled_prompt.write_text("bundled selfcheck policy", encoding="utf-8")
        monkeypatch.setattr("openkitsune.config.settings.project_root", workspace_root)
        monkeypatch.setattr(
            "openkitsune.evolution.self_check.resources.files",
            lambda package: package_root,
        )

        checker = SelfChecker(brain=mock_brain)

        assert checker._load_selfcheck_system_prompt() == "bundled selfcheck policy"

    def test_missing_prompts_fail_closed(self, mock_brain, tmp_path, monkeypatch):
        workspace_root = tmp_path / "workspace"
        package_root = tmp_path / "package" / "openkitsune"
        workspace_root.mkdir()
        package_root.mkdir(parents=True)
        monkeypatch.setattr("openkitsune.config.settings.project_root", workspace_root)
        monkeypatch.setattr(
            "openkitsune.evolution.self_check.resources.files",
            lambda package: package_root,
        )

        checker = SelfChecker(brain=mock_brain)

        with pytest.raises(SelfCheckPromptUnavailableError, match="prompt is unavailable"):
            checker._load_selfcheck_system_prompt()

    def test_parse_llm_analysis_preserves_unstructured_string_items(self, mock_brain):
        checker = SelfChecker(brain=mock_brain)

        result = checker._parse_llm_analysis('["检查浏览器依赖", {"error_id": "x"}]')

        assert result[0]["error_type"] == "core"
        assert result[0]["can_fix"] is False
        assert result[0]["analysis"] == "检查浏览器依赖"
        assert result[1]["error_id"] == "x"

    def test_filter_selfcheck_timeout_feedback_patterns(self, mock_brain):
        checker = SelfChecker(brain=mock_brain)
        now = datetime.now()
        patterns = {
            "selfcheck_timeout": ErrorPattern(
                pattern="selfcheck_timeout",
                count=2,
                first_seen=now,
                last_seen=now,
                samples=[
                    LogEntry(
                        timestamp=now,
                        level="ERROR",
                        logger_name="openkitsune.scheduler.executor",
                        message="TaskExecutor: System task system:daily_selfcheck timed out after 300s",
                    )
                ],
            ),
            "real_error": ErrorPattern(
                pattern="real_error",
                count=1,
                first_seen=now,
                last_seen=now,
                samples=[
                    LogEntry(
                        timestamp=now,
                        level="ERROR",
                        logger_name="openkitsune.tools.browser",
                        message="Browser failed",
                    )
                ],
            ),
        }

        filtered = checker._filter_selfcheck_feedback_patterns(patterns)

        assert list(filtered) == ["real_error"]

    @pytest.mark.asyncio
    async def test_run_daily_check_saves_partial_report_on_time_budget(
        self,
        mock_brain,
        tmp_path,
        monkeypatch,
    ):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "error.log").write_text(
            "2026-03-31 00:00:00,000 - openkitsune.tools.browser - ERROR - Browser failed\n",
            encoding="utf-8",
        )

        monkeypatch.setattr("openkitsune.config.settings.project_root", tmp_path)
        checker = SelfChecker(brain=mock_brain)

        async def no_memory_insights():
            return {}

        monkeypatch.setattr(checker, "_extract_memory_insights", no_memory_insights)
        ticks = iter([0.0, 2.0])
        monkeypatch.setattr(
            "openkitsune.evolution.self_check.time.monotonic",
            lambda: next(ticks, 2.0),
        )

        report = await checker.run_daily_check(max_runtime_seconds=1)

        assert report.partial is True
        assert "时间预算" in report.status_note
        assert (tmp_path / "data" / "selfcheck" / f"{report.date}_report.json").exists()

    @pytest.mark.asyncio
    async def test_run_daily_check_skips_llm_and_fix_when_prompt_is_unavailable(
        self,
        mock_brain,
        tmp_path,
        monkeypatch,
    ):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        (log_dir / "error.log").write_text(
            "2026-03-31 00:00:00,000 - openkitsune.tools.browser - ERROR - Browser failed\n",
            encoding="utf-8",
        )
        package_root = tmp_path / "empty-package" / "openkitsune"
        package_root.mkdir(parents=True)
        monkeypatch.setattr("openkitsune.config.settings.project_root", tmp_path)
        monkeypatch.setattr(
            "openkitsune.evolution.self_check.resources.files",
            lambda package: package_root,
        )
        checker = SelfChecker(brain=mock_brain)

        async def no_memory_insights():
            return {}

        monkeypatch.setattr(checker, "_extract_memory_insights", no_memory_insights)

        report = await checker.run_daily_check()

        assert report.partial is True
        assert "提示词不可用" in report.status_note
        assert report.fix_attempted == 0
        mock_brain.think.assert_not_called()
        assert (tmp_path / "data" / "selfcheck" / f"{report.date}_report.json").exists()
