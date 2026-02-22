"""Tests for the heartbeat service."""

import time

from core.heartbeat import (
    STALL_THRESHOLD,
    AgentHeartbeat,
    HeartbeatService,
    SystemHealth,
)


class TestAgentHeartbeat:
    """Tests for individual agent heartbeat records."""

    def test_initial_state(self):
        hb = AgentHeartbeat(task_id="task-1")
        assert hb.task_id == "task-1"
        assert hb.status == "running"
        assert hb.iteration == 0
        assert not hb.is_stalled

    def test_age_increases(self):
        hb = AgentHeartbeat(task_id="task-1")
        # Manually set last_beat to a past time
        hb.last_beat = time.monotonic() - 10
        assert hb.age_seconds >= 10

    def test_stalled_detection(self):
        hb = AgentHeartbeat(task_id="task-1")
        # Not stalled initially
        assert not hb.is_stalled
        # Force it to be stalled
        hb.last_beat = time.monotonic() - STALL_THRESHOLD - 1
        assert hb.is_stalled

    def test_to_dict(self):
        hb = AgentHeartbeat(task_id="task-1", iteration=3, message="working")
        d = hb.to_dict()
        assert d["task_id"] == "task-1"
        assert d["iteration"] == 3
        assert d["status"] == "running"
        assert d["message"] == "working"
        assert "last_beat_age_s" in d
        assert "stalled" in d


class TestSystemHealth:
    """Tests for the system health snapshot."""

    def test_defaults(self):
        health = SystemHealth()
        assert health.active_agents == 0
        assert health.stalled_agents == 0
        assert health.uptime_seconds == 0

    def test_to_dict(self):
        health = SystemHealth(
            active_agents=3,
            stalled_agents=1,
            tasks_pending=5,
            tasks_completed=10,
            tasks_failed=2,
            uptime_seconds=3600.123,
            memory_mb=128.456,
            tools_registered=15,
        )
        d = health.to_dict()
        assert d["active_agents"] == 3
        assert d["stalled_agents"] == 1
        assert d["tasks_pending"] == 5
        assert d["tasks_completed"] == 10
        assert d["tasks_failed"] == 2
        assert d["uptime_seconds"] == 3600.1
        assert d["memory_mb"] == 128.5
        assert d["tools_registered"] == 15


class TestHeartbeatService:
    """Tests for the heartbeat monitoring service."""

    def setup_method(self):
        self.service = HeartbeatService(interval=1)

    def test_register_agent(self):
        self.service.register_agent("task-1")
        assert len(self.service.active_agents) == 1
        assert self.service.active_agents[0].task_id == "task-1"

    def test_unregister_agent(self):
        self.service.register_agent("task-1")
        self.service.unregister_agent("task-1")
        assert len(self.service.active_agents) == 0

    def test_beat_updates_existing(self):
        self.service.register_agent("task-1")
        self.service.beat("task-1", iteration=5, message="progressing")
        agents = self.service.active_agents
        assert agents[0].iteration == 5
        assert agents[0].message == "progressing"

    def test_beat_creates_new(self):
        self.service.beat("task-new", iteration=1)
        assert len(self.service.active_agents) == 1
        assert self.service.active_agents[0].task_id == "task-new"

    def test_mark_complete(self):
        self.service.register_agent("task-1")
        self.service.mark_complete("task-1")
        # Completed agents are not "active"
        assert len(self.service.active_agents) == 0

    def test_mark_failed(self):
        self.service.register_agent("task-1")
        self.service.mark_failed("task-1", error="timeout")
        assert len(self.service.active_agents) == 0

    def test_stalled_agents(self):
        self.service.register_agent("task-1")
        # Force stall
        self.service._agents["task-1"].last_beat = time.monotonic() - STALL_THRESHOLD - 1
        stalled = self.service.stalled_agents
        assert len(stalled) == 1
        assert stalled[0].task_id == "task-1"

    def test_get_health(self):
        self.service.register_agent("task-1")
        self.service.register_agent("task-2")
        self.service.mark_complete("task-2")

        health = self.service.get_health()
        assert health.active_agents == 1
        assert health.uptime_seconds >= 0

    def test_multiple_agents(self):
        for i in range(5):
            self.service.register_agent(f"task-{i}")
        assert len(self.service.active_agents) == 5

        self.service.mark_complete("task-0")
        self.service.mark_complete("task-1")
        assert len(self.service.active_agents) == 3

    def test_stop_without_start(self):
        # Should not raise
        self.service.stop()
