"""L1 Unit Tests: Scheduled task creation, state transitions, and triggers."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from openkitsune.scheduler.executor import TaskExecutor
from openkitsune.scheduler.task import (
    ScheduledTask,
    TaskDeliveryPolicy,
    TaskSource,
    TaskStatus,
    TaskType,
    TriggerType,
)
from openkitsune.scheduler.triggers import CronTrigger, IntervalTrigger, OnceTrigger, Trigger


class TestScheduledTaskCreation:
    def test_create_basic_task(self):
        task = ScheduledTask.create(
            name="test-task",
            description="A test task",
            trigger_type=TriggerType.ONCE,
            trigger_config={"run_at": (datetime.now() + timedelta(hours=1)).isoformat()},
            prompt="Do something",
        )
        assert task.name == "test-task"
        assert task.status == TaskStatus.PENDING
        assert task.enabled is True

    def test_create_reminder(self):
        run_at = datetime.now() + timedelta(hours=2)
        task = ScheduledTask.create_reminder(
            name="birthday-reminder",
            description="Remind about birthday",
            run_at=run_at,
            message="Happy birthday!",
        )
        assert task.is_reminder is True
        assert task.reminder_message == "Happy birthday!"

    def test_create_interval_task(self):
        task = ScheduledTask.create_interval(
            name="hourly-check",
            description="Check every hour",
            interval_minutes=60,
            prompt="Run health check",
        )
        assert task.trigger_type == TriggerType.INTERVAL

    def test_create_cron_task(self):
        task = ScheduledTask.create_cron(
            name="daily-report",
            description="Generate daily report",
            cron_expression="0 8 * * *",
            prompt="Generate report",
        )
        assert task.trigger_type == TriggerType.CRON


class TestTaskStateTransitions:
    def test_enable_disable(self):
        task = ScheduledTask.create(
            name="t",
            description="d",
            trigger_type=TriggerType.ONCE,
            trigger_config={"run_at": datetime.now().isoformat()},
            prompt="p",
        )
        task.disable()
        assert task.enabled is False
        task.enable()
        assert task.enabled is True

    def test_mark_running(self):
        task = ScheduledTask.create(
            name="t",
            description="d",
            trigger_type=TriggerType.ONCE,
            trigger_config={"run_at": datetime.now().isoformat()},
            prompt="p",
        )
        task.mark_running()
        assert task.status == TaskStatus.RUNNING

    def test_mark_completed(self):
        task = ScheduledTask.create(
            name="t",
            description="d",
            trigger_type=TriggerType.ONCE,
            trigger_config={"run_at": datetime.now().isoformat()},
            prompt="p",
        )
        task.mark_running()
        task.mark_completed()
        assert task.status == TaskStatus.COMPLETED
        assert task.run_count == 1

    def test_mark_failed(self):
        task = ScheduledTask.create(
            name="t",
            description="d",
            trigger_type=TriggerType.ONCE,
            trigger_config={"run_at": datetime.now().isoformat()},
            prompt="p",
        )
        task.mark_running()
        task.mark_failed("timeout")
        # After failure, task may go to FAILED or back to SCHEDULED for retry
        assert task.status in (TaskStatus.FAILED, TaskStatus.SCHEDULED)
        assert task.fail_count == 1


class TestSystemTaskTimeouts:
    async def test_daily_memory_timeout_is_safe_pause_not_failure(self, monkeypatch):
        async def fake_wait_for(_coro, timeout):
            if hasattr(_coro, "close"):
                _coro.close()
            raise TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        task = ScheduledTask.create(
            name="daily memory",
            description="daily memory",
            trigger_type=TriggerType.INTERVAL,
            trigger_config={"interval_minutes": 60},
            prompt="",
            action="system:daily_memory",
            deletable=False,
        )
        executor = TaskExecutor()

        success, message = await executor._execute_system_task(task)

        assert success is True
        assert "下次" in message

    async def test_daily_selfcheck_timeout_is_safe_pause_not_failure(self, monkeypatch):
        async def fake_wait_for(_coro, timeout):
            if hasattr(_coro, "close"):
                _coro.close()
            raise TimeoutError

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        task = ScheduledTask.create(
            name="daily selfcheck",
            description="daily selfcheck",
            trigger_type=TriggerType.CRON,
            trigger_config={"cron": "0 4 * * *"},
            prompt="",
            action="system:daily_selfcheck",
            deletable=False,
        )
        executor = TaskExecutor()

        success, message = await executor._execute_system_task(task)

        assert success is True
        assert "下次继续" in message

    async def test_system_task_sets_and_resets_background_token_budget(self, monkeypatch):
        from openkitsune.core.token_tracking import get_token_budget, record_usage

        task = ScheduledTask.create(
            name="daily memory",
            description="daily memory",
            trigger_type=TriggerType.INTERVAL,
            trigger_config={"interval_minutes": 60},
            prompt="",
            action="system:daily_memory",
            deletable=False,
        )
        executor = TaskExecutor()

        async def fake_daily_memory():
            assert get_token_budget() is not None
            record_usage(input_tokens=10, output_tokens=5)
            return True, "done"

        monkeypatch.setattr(
            "openkitsune.config.settings.scheduler_background_token_budget",
            20,
        )
        monkeypatch.setattr(executor, "_system_daily_memory", fake_daily_memory)

        success, message = await executor._execute_system_task(task)

        assert success is True
        assert message == "done"
        assert get_token_budget() is None


class TestTaskAgentProfiles:
    async def test_executor_creates_selected_agent_profile(self, monkeypatch):
        selected = SimpleNamespace(id="code-assistant")
        created = SimpleNamespace(name="profile-agent")
        seen: dict[str, object] = {}

        async def fake_create(self, profile):
            seen["profile"] = profile
            return created

        monkeypatch.setattr(
            TaskExecutor,
            "_resolve_agent_profile",
            lambda self, profile_id: selected if profile_id == "code-assistant" else None,
        )
        monkeypatch.setattr("openkitsune.agents.factory.AgentFactory.create", fake_create)

        executor = TaskExecutor()
        agent = await executor._create_agent("code-assistant")

        assert agent is created
        assert seen["profile"] is selected

    async def test_chat_created_task_inherits_current_agent_profile(self):
        from openkitsune.tools.handlers.scheduled import ScheduledHandler

        captured: dict[str, ScheduledTask] = {}

        class FakeScheduler:
            async def add_task(self, task):
                captured["task"] = task
                return task.id

        agent = SimpleNamespace(
            task_scheduler=FakeScheduler(),
            _current_session=SimpleNamespace(
                context=SimpleNamespace(agent_profile_id="researcher")
            ),
            _agent_profile_id="default",
        )
        handler = ScheduledHandler(agent)

        result = await handler._schedule_task(
            {
                "name": "research-task",
                "description": "research",
                "task_type": "task",
                "trigger_type": "interval",
                "trigger_config": {"interval_minutes": 60},
                "prompt": "do research",
            }
        )

        assert "已创建" in result
        assert captured["task"].agent_profile_id == "researcher"
        assert captured["task"].delivery_policy == TaskDeliveryPolicy.OWNER_ONLY
        assert captured["task"].channel_id is None
        assert captured["task"].chat_id is None
        assert captured["task"].metadata["origin"]["agent_profile_id"] == "researcher"
        assert captured["task"].metadata["delivery_target_source"] == "none"

    async def test_desktop_created_task_records_origin_without_im_target(self):
        from openkitsune.tools.handlers.scheduled import ScheduledHandler

        captured: dict[str, ScheduledTask] = {}

        class FakeScheduler:
            async def add_task(self, task):
                captured["task"] = task
                return task.id

        agent = SimpleNamespace(
            task_scheduler=FakeScheduler(),
            _current_session=SimpleNamespace(
                id="desktop-session",
                channel="desktop",
                chat_id="local-window",
                user_id="desktop-user",
                context=SimpleNamespace(agent_profile_id="desktop-profile"),
            ),
            _agent_profile_id="default",
        )
        handler = ScheduledHandler(agent)

        result = await handler._schedule_task(
            {
                "name": "desktop-reminder",
                "description": "desktop reminder",
                "task_type": "reminder",
                "trigger_type": "once",
                "trigger_config": {"run_at": (datetime.now() + timedelta(minutes=5)).isoformat()},
                "reminder_message": "stand up",
            }
        )

        task = captured["task"]
        assert "已创建" in result
        assert task.channel_id is None
        assert task.chat_id is None
        assert task.user_id == "desktop-user"
        assert task.agent_profile_id == "desktop-profile"
        assert task.delivery_policy == TaskDeliveryPolicy.OWNER_ONLY
        assert task.metadata["origin"]["channel"] == "desktop"
        assert task.metadata["origin"]["chat_id"] == "local-window"
        assert task.metadata["delivery_target_source"] == "none"

    async def test_im_created_task_records_exact_owner_target(self):
        from openkitsune.tools.handlers.scheduled import ScheduledHandler

        captured: dict[str, ScheduledTask] = {}

        class FakeScheduler:
            async def add_task(self, task):
                captured["task"] = task
                return task.id

        agent = SimpleNamespace(
            task_scheduler=FakeScheduler(),
            _current_session=SimpleNamespace(
                id="im-session",
                channel="feishu:bot-a",
                chat_id="oc_owner",
                user_id="im-user",
                context=SimpleNamespace(agent_profile_id="assistant-a"),
            ),
            _agent_profile_id="default",
        )
        handler = ScheduledHandler(agent)

        result = await handler._schedule_task(
            {
                "name": "im-reminder",
                "description": "im reminder",
                "task_type": "reminder",
                "trigger_type": "once",
                "trigger_config": {"run_at": (datetime.now() + timedelta(minutes=5)).isoformat()},
                "reminder_message": "ping",
            }
        )

        task = captured["task"]
        assert "已创建" in result
        assert task.channel_id == "feishu:bot-a"
        assert task.chat_id == "oc_owner"
        assert task.user_id == "im-user"
        assert task.agent_profile_id == "assistant-a"
        assert task.delivery_policy == TaskDeliveryPolicy.OWNER_ONLY
        assert task.metadata["origin"]["channel"] == "feishu:bot-a"
        assert task.metadata["delivery_target_source"] == "current_im_session"


class TestSystemTaskRegistration:
    async def test_memory_task_keeps_user_custom_trigger(self, monkeypatch):
        from openkitsune.agent.core import Agent

        task = ScheduledTask(
            id="system_daily_memory",
            name="记忆整理",
            trigger_type=TriggerType.INTERVAL,
            trigger_config={"interval_minutes": 720},
            action="system:daily_memory",
            prompt="",
            description="custom",
            task_type=TaskType.TASK,
            deletable=False,
            metadata={"user_custom_trigger": True},
        )

        class FakeTracker:
            def __init__(self, *_args, **_kwargs):
                pass

            def is_onboarding(self, _days):
                return False

        class FakeScheduler:
            def __init__(self):
                self.updates: list[tuple[str, dict]] = []
                self.saved = False

            def list_tasks(self):
                return [task]

            def get_task(self, task_id):
                return task if task_id == "system_daily_memory" else None

            async def update_task(self, task_id, updates):
                self.updates.append((task_id, updates))
                return True

            async def save(self):
                self.saved = True

            async def add_task(self, _task):
                return _task.id

        monkeypatch.setattr(
            "openkitsune.scheduler.consolidation_tracker.ConsolidationTracker",
            FakeTracker,
        )
        scheduler = FakeScheduler()
        agent = SimpleNamespace(task_scheduler=scheduler)

        await Agent._register_system_tasks(agent)

        assert scheduler.updates == []
        assert task.trigger_type == TriggerType.INTERVAL
        assert task.trigger_config == {"interval_minutes": 720}
        assert task.task_source == TaskSource.SYSTEM
        assert task.delivery_policy == TaskDeliveryPolicy.FALLBACK_ALLOWED
        assert scheduler.saved is True


class TestTaskSerialization:
    def test_to_dict_and_back(self):
        task = ScheduledTask.create(
            name="serialize-test",
            description="Test serialization",
            trigger_type=TriggerType.INTERVAL,
            trigger_config={"interval_minutes": 30},
            prompt="Do it",
            delivery_policy=TaskDeliveryPolicy.FALLBACK_ALLOWED,
        )
        d = task.to_dict()
        assert d["name"] == "serialize-test"
        assert d["delivery_policy"] == "fallback_allowed"
        restored = ScheduledTask.from_dict(d)
        assert restored.name == task.name
        assert restored.prompt == task.prompt
        assert restored.delivery_policy == TaskDeliveryPolicy.FALLBACK_ALLOWED

    def test_legacy_user_task_without_delivery_policy_loads_owner_only(self):
        task = ScheduledTask.create(
            name="legacy-user",
            description="legacy user task",
            trigger_type=TriggerType.ONCE,
            trigger_config={"run_at": (datetime.now() + timedelta(minutes=5)).isoformat()},
            prompt="",
            task_source=TaskSource.CHAT,
        )
        data = task.to_dict()
        data.pop("delivery_policy")

        restored = ScheduledTask.from_dict(data)

        assert restored.delivery_policy == TaskDeliveryPolicy.OWNER_ONLY
        assert restored.allows_global_im_fallback is False

    def test_legacy_system_task_without_delivery_policy_loads_fallback_allowed(self):
        task = ScheduledTask.create(
            name="legacy-system",
            description="legacy system task",
            trigger_type=TriggerType.CRON,
            trigger_config={"cron": "0 3 * * *"},
            prompt="",
            action="system:daily_memory",
            task_source=TaskSource.SYSTEM,
        )
        data = task.to_dict()
        data.pop("delivery_policy")

        restored = ScheduledTask.from_dict(data)

        assert restored.delivery_policy == TaskDeliveryPolicy.FALLBACK_ALLOWED
        assert restored.allows_global_im_fallback is True


class TestTriggers:
    def test_once_trigger_fires_once(self):
        run_at = datetime.now() + timedelta(seconds=-1)
        trigger = OnceTrigger(run_at=run_at)
        assert trigger.should_run() is True
        trigger.mark_fired()
        assert trigger.should_run() is False

    def test_interval_trigger_next_run(self):
        trigger = IntervalTrigger(interval_minutes=60)
        next_run = trigger.get_next_run_time(last_run=datetime.now())
        assert next_run > datetime.now()
        assert (next_run - datetime.now()).total_seconds() < 3700  # ~60 min

    def test_cron_trigger_next_run(self):
        trigger = CronTrigger(cron_expression="0 8 * * *")
        next_run = trigger.get_next_run_time()
        assert next_run is not None
        assert next_run > datetime.now()

    def test_cron_trigger_describe(self):
        trigger = CronTrigger(cron_expression="0 8 * * *")
        desc = trigger.describe()
        assert isinstance(desc, str)
        assert len(desc) > 0

    def test_trigger_from_config(self):
        trigger = Trigger.from_config(
            "once", {"run_at": (datetime.now() + timedelta(hours=1)).isoformat()}
        )
        assert isinstance(trigger, OnceTrigger)
