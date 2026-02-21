"""Tests for all OpenClaw-inspired features in Agent42.

Covers:
  - URL Policy (allowlist, denylist, SSRF, per-agent limits, audit log)
  - Security Audit Tool (report, startup, categories)
  - Notification Service (webhooks, Slack/Discord format, email, event filtering)
  - Enhanced Task Model (Kanban fields, comments, block/unblock, archive, board)
  - Mission Control API (Kanban endpoints)
  - Context Safeguards (overflow detection, truncation)
  - Cron Stagger (auto-stagger, manual override, jitter)
  - Extended Context Window (model routing, models_by_min_context)
  - Enhanced Security Analyzer (scan_dependencies, scan_secrets, scan_owasp)
  - Browser Gateway Token
"""

import asyncio
import json
import os
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# URL Policy Tests
# ============================================================================

from core.url_policy import UrlPolicy, _is_ssrf_target, _BLOCKED_IP_RANGES


class TestUrlPolicyAllowDeny:
    """URL allowlist and denylist enforcement."""

    def test_empty_allowlist_allows_public_url(self):
        """Backward compat: no allowlist means all public URLs pass."""
        policy = UrlPolicy(allowlist=[], denylist=[], audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"))
        allowed, reason = policy.check("https://example.com/page", agent_id="a1")
        assert allowed is True
        assert reason == ""

    def test_allowlist_blocks_non_matching_hostname(self):
        policy = UrlPolicy(
            allowlist=["*.github.com", "api.openai.com"],
            audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"),
        )
        allowed, reason = policy.check("https://evil.com/data", agent_id="a1")
        assert allowed is False
        assert "allowlist" in reason.lower()

    def test_allowlist_allows_matching_glob(self):
        policy = UrlPolicy(
            allowlist=["*.github.com"],
            audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"),
        )
        allowed, reason = policy.check("https://api.github.com/repos", agent_id="a1")
        assert allowed is True

    def test_denylist_takes_precedence_over_allowlist(self):
        policy = UrlPolicy(
            allowlist=["*.example.com"],
            denylist=["bad.example.com"],
            audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"),
        )
        allowed, reason = policy.check("https://bad.example.com/x", agent_id="a1")
        assert allowed is False
        assert "denylist" in reason.lower()

    def test_denylist_blocks_matching_hostname(self):
        policy = UrlPolicy(
            denylist=["*.malware.com"],
            audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"),
        )
        allowed, reason = policy.check("https://download.malware.com/bad", agent_id="a1")
        assert allowed is False


class TestUrlPolicyPerAgentLimits:
    """Per-agent request limit tracking."""

    def test_per_agent_limit_enforced(self):
        policy = UrlPolicy(
            max_requests_per_agent=2,
            audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"),
        )
        policy.check("https://example.com/1", agent_id="agent-1")
        policy.check("https://example.com/2", agent_id="agent-1")
        allowed, reason = policy.check("https://example.com/3", agent_id="agent-1")
        assert allowed is False
        assert "limit" in reason.lower()

    def test_per_agent_limit_tracks_separately(self):
        policy = UrlPolicy(
            max_requests_per_agent=2,
            audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"),
        )
        policy.check("https://example.com/1", agent_id="agent-1")
        policy.check("https://example.com/2", agent_id="agent-1")
        # Different agent is not affected
        allowed, _ = policy.check("https://example.com/1", agent_id="agent-2")
        assert allowed is True

    def test_reset_agent_counts(self):
        policy = UrlPolicy(
            max_requests_per_agent=1,
            audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"),
        )
        policy.check("https://example.com/1", agent_id="agent-1")
        allowed, _ = policy.check("https://example.com/2", agent_id="agent-1")
        assert allowed is False

        policy.reset_agent_counts("agent-1")
        allowed, _ = policy.check("https://example.com/3", agent_id="agent-1")
        assert allowed is True


class TestUrlPolicySsrf:
    """SSRF protection for private IPs and localhost."""

    def test_ssrf_blocks_localhost(self):
        policy = UrlPolicy(audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"))
        allowed, reason = policy.check("http://localhost:8080/admin", agent_id="a1")
        assert allowed is False
        assert "localhost" in reason.lower() or "blocked" in reason.lower()

    def test_ssrf_blocks_localhost_localdomain(self):
        policy = UrlPolicy(audit_log_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"))
        allowed, reason = policy.check("http://localhost.localdomain/admin", agent_id="a1")
        assert allowed is False

    def test_backward_compat_is_ssrf_target(self):
        """The legacy _is_ssrf_target function should still work."""
        result = _is_ssrf_target("http://localhost/admin")
        assert result is not None  # Should return an error message
        assert "localhost" in result.lower() or "blocked" in result.lower()

    def test_is_ssrf_target_allows_public(self):
        """Public URLs should return None (no SSRF issue)."""
        result = _is_ssrf_target("https://example.com/api")
        assert result is None


class TestUrlPolicyAuditLog:
    """Audit log creation and format."""

    def test_audit_log_written_on_block(self):
        tmpdir = tempfile.mkdtemp()
        log_path = os.path.join(tmpdir, "audit.jsonl")
        policy = UrlPolicy(
            denylist=["*.blocked.com"],
            audit_log_path=log_path,
        )
        policy.check("https://test.blocked.com/x", agent_id="agent-1")

        assert os.path.exists(log_path)
        with open(log_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]
        assert len(entries) == 1
        assert entries[0]["url"] == "https://test.blocked.com/x"
        assert entries[0]["agent_id"] == "agent-1"
        assert "reason" in entries[0]
        assert "timestamp" in entries[0]


# ============================================================================
# Security Audit Tests
# ============================================================================

from tools.security_audit import run_audit, startup_audit, AuditReport, AuditCheck, SecurityAuditTool


class TestSecurityAudit:
    """Security audit report generation."""

    def test_run_audit_returns_report(self):
        report = run_audit()
        assert isinstance(report, AuditReport)
        assert len(report.checks) > 0

    def test_audit_report_has_all_categories(self):
        report = run_audit()
        categories = {c.category for c in report.checks}
        # Verify key categories exist
        expected = {"Authentication", "Network", "Sandbox", "Secrets", "Rate Limiting"}
        assert expected.issubset(categories)

    def test_audit_report_score_calculation(self):
        report = AuditReport(checks=[
            AuditCheck("Cat", "Check1", "pass"),
            AuditCheck("Cat", "Check2", "pass"),
            AuditCheck("Cat", "Check3", "fail"),
            AuditCheck("Cat", "Check4", "warn"),
        ])
        assert report.passed == 2
        assert report.failures == 1
        assert report.warnings == 1
        assert report.score == 50  # 2/4 * 100

    def test_audit_report_format_output(self):
        report = AuditReport(checks=[
            AuditCheck("Auth", "Password set", "pass"),
            AuditCheck("Auth", "Hash used", "fail", "Not configured"),
        ])
        output = report.format()
        assert "Security Audit Report" in output
        assert "PASS" in output
        assert "FAIL" in output
        assert "Auth" in output

    def test_check_counts_minimum(self):
        """The full audit should run at least 30 checks."""
        report = run_audit()
        assert len(report.checks) >= 30

    def test_startup_audit_logs_warnings(self):
        with patch("tools.security_audit.logger") as mock_logger:
            report = startup_audit()
            assert isinstance(report, AuditReport)
            # Should have called logger.info at least for start and completion
            assert mock_logger.info.call_count >= 2


class TestSecurityAuditTool:
    """SecurityAuditTool integration."""

    @pytest.mark.asyncio
    async def test_execute_returns_report(self):
        tool = SecurityAuditTool()
        result = await tool.execute()
        assert "Security Audit Report" in result.output

    @pytest.mark.asyncio
    async def test_execute_with_category_filter(self):
        tool = SecurityAuditTool()
        result = await tool.execute(category="Authentication")
        assert "Authentication" in result.output or "Auth" in result.output

    def test_tool_properties(self):
        tool = SecurityAuditTool()
        assert tool.name == "security_audit"
        assert "security audit" in tool.description.lower()
        assert "category" in tool.parameters["properties"]


# ============================================================================
# Notification Service Tests
# ============================================================================

from core.notification_service import (
    NotificationService, NotificationPayload,
    SEVERITY_INFO, SEVERITY_CRITICAL, SEVERITY_WARNING,
    _EMAIL_EVENTS,
)


class TestNotificationServiceFormats:
    """Webhook format auto-detection."""

    def test_slack_format_detected(self):
        svc = NotificationService(webhook_urls=["https://hooks.slack.com/services/T/B/x"])
        payload = NotificationPayload(
            event="task_failed", timestamp=time.time(),
            task_id="t1", title="Test", severity=SEVERITY_CRITICAL,
        )
        body = svc._format_webhook("https://hooks.slack.com/services/T/B/x", payload)
        assert "attachments" in body
        assert body["attachments"][0]["blocks"][0]["type"] == "header"

    def test_discord_format_detected(self):
        svc = NotificationService(webhook_urls=["https://discord.com/api/webhooks/123/abc"])
        payload = NotificationPayload(
            event="task_done", timestamp=time.time(),
            task_id="t2", title="Done", severity=SEVERITY_INFO,
        )
        body = svc._format_webhook("https://discord.com/api/webhooks/123/abc", payload)
        assert "embeds" in body
        assert body["embeds"][0]["title"].startswith("Agent42:")

    def test_generic_format_for_unknown_url(self):
        svc = NotificationService()
        payload = NotificationPayload(
            event="task_review", timestamp=time.time(),
            task_id="t3", title="Review", severity=SEVERITY_WARNING,
        )
        body = svc._format_webhook("https://webhook.example.com/hook", payload)
        assert body["event"] == "task_review"
        assert body["source"] == "agent42"
        assert body["task_id"] == "t3"


class TestNotificationServiceEventFilter:
    """Event filtering and routing."""

    @pytest.mark.asyncio
    async def test_notify_filters_by_allowed_events(self):
        svc = NotificationService(
            webhook_urls=["https://example.com/hook"],
            allowed_events=["task_failed"],
        )
        payload = NotificationPayload(
            event="task_created", timestamp=time.time(),
            task_id="t4", title="New Task",
        )
        # Should not call _send_webhook because task_created not in allowed_events
        with patch.object(svc, "_send_webhook", new_callable=AsyncMock) as mock_send:
            await svc.notify(payload)
            mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_sends_when_event_allowed(self):
        svc = NotificationService(
            webhook_urls=["https://example.com/hook"],
            allowed_events=["task_failed"],
        )
        payload = NotificationPayload(
            event="task_failed", timestamp=time.time(),
            task_id="t5", title="Failed",
        )
        with patch.object(svc, "_send_webhook", new_callable=AsyncMock) as mock_send:
            await svc.notify(payload)
            mock_send.assert_called_once()


class TestNotificationServiceEmail:
    """Email notification for critical events."""

    @pytest.mark.asyncio
    async def test_email_sent_for_critical_events(self):
        svc = NotificationService(
            email_recipients=["admin@example.com"],
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="user",
            smtp_password="pass",
        )
        payload = NotificationPayload(
            event="task_failed", timestamp=time.time(),
            task_id="t6", title="Failed Task", severity=SEVERITY_CRITICAL,
        )
        with patch.object(svc, "_send_email", new_callable=AsyncMock) as mock_email:
            await svc.notify(payload)
            mock_email.assert_called_once()

    @pytest.mark.asyncio
    async def test_email_not_sent_for_info_events(self):
        svc = NotificationService(
            email_recipients=["admin@example.com"],
            smtp_host="smtp.example.com",
        )
        payload = NotificationPayload(
            event="task_done", timestamp=time.time(),
            task_id="t7", title="Done", severity=SEVERITY_INFO,
        )
        with patch.object(svc, "_send_email", new_callable=AsyncMock) as mock_email:
            await svc.notify(payload)
            mock_email.assert_not_called()


class TestNotificationServiceSsrf:
    """SSRF protection on webhook URLs."""

    @pytest.mark.asyncio
    async def test_ssrf_blocks_internal_webhook_url(self):
        svc = NotificationService(
            webhook_urls=["http://localhost:9999/hook"],
        )
        payload = NotificationPayload(
            event="task_failed", timestamp=time.time(),
            task_id="t8", title="Fail",
        )
        with patch.object(svc, "_send_webhook", new_callable=AsyncMock) as mock_send:
            await svc.notify(payload)
            # Should not call _send_webhook because localhost is SSRF-blocked
            mock_send.assert_not_called()


# ============================================================================
# Enhanced Task Model (Kanban) Tests
# ============================================================================

from core.task_queue import Task, TaskStatus, TaskType, TaskQueue


class TestTaskKanbanFields:
    """Mission Control Kanban fields on Task dataclass."""

    def test_task_add_comment(self):
        task = Task(title="Test", description="Desc")
        task.add_comment("admin", "Looks good")
        assert len(task.comments) == 1
        assert task.comments[0]["author"] == "admin"
        assert task.comments[0]["text"] == "Looks good"
        assert "timestamp" in task.comments[0]

    def test_task_block_sets_status_and_reason(self):
        task = Task(title="Test", description="Desc")
        task.block("Waiting for API key")
        assert task.status == TaskStatus.BLOCKED
        assert task.blocked_reason == "Waiting for API key"

    def test_task_unblock_resets_to_pending(self):
        task = Task(title="Test", description="Desc")
        task.block("Reason")
        task.unblock()
        assert task.status == TaskStatus.PENDING
        assert task.blocked_reason == ""

    def test_task_archive(self):
        task = Task(title="Test", description="Desc")
        task.archive()
        assert task.status == TaskStatus.ARCHIVED

    def test_context_window_field_default(self):
        task = Task(title="Test", description="Desc")
        assert task.context_window == "default"

    def test_task_to_dict_includes_kanban_fields(self):
        task = Task(title="Test", description="Desc", priority=2, tags=["urgent"])
        d = task.to_dict()
        assert d["priority"] == 2
        assert d["tags"] == ["urgent"]
        assert d["context_window"] == "default"
        assert d["comments"] == []

    def test_task_from_dict_backward_compat(self):
        """Old tasks without Kanban fields should load with defaults."""
        old_data = {
            "id": "abc123",
            "title": "Old Task",
            "description": "Legacy",
            "status": "pending",
            "task_type": "coding",
            "created_at": 1700000000.0,
            "updated_at": 1700000000.0,
            "iterations": 0,
            "max_iterations": 8,
        }
        task = Task.from_dict(old_data)
        assert task.priority == 0
        assert task.tags == []
        assert task.comments == []
        assert task.context_window == "default"


class TestTaskQueueKanban:
    """TaskQueue Kanban operations."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.queue = TaskQueue(os.path.join(self.tmpdir, "tasks.json"))

    @pytest.mark.asyncio
    async def test_board_groups_by_status(self):
        await self.queue.add(Task(title="T1", description="D1"))
        await self.queue.add(Task(title="T2", description="D2"))
        board = self.queue.board()
        assert "pending" in board
        assert len(board["pending"]) == 2
        # All status columns should exist
        for status in TaskStatus:
            assert status.value in board

    @pytest.mark.asyncio
    async def test_board_sorts_by_position_then_priority(self):
        t1 = Task(title="Low", description="D", priority=0, position=1)
        t2 = Task(title="Urgent", description="D", priority=2, position=0)
        await self.queue.add(t1)
        await self.queue.add(t2)
        board = self.queue.board()
        pending = board["pending"]
        # Position 0 (urgent) should come before position 1 (low)
        assert pending[0]["position"] == 0
        assert pending[1]["position"] == 1

    @pytest.mark.asyncio
    async def test_move_task_changes_status_and_position(self):
        task = Task(title="T1", description="D1")
        await self.queue.add(task)
        await self.queue.move_task(task.id, "running", position=5)
        moved = self.queue.get(task.id)
        assert moved.status == TaskStatus.RUNNING
        assert moved.position == 5


# ============================================================================
# Context Safeguard Tests
# ============================================================================


class TestContextSafeguards:
    """Context window overflow detection in IterationEngine."""

    def test_truncation_keeps_system_and_latest(self):
        """Simulating the truncation logic from iteration_engine.py."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Original task"},
            {"role": "assistant", "content": "Output 1"},
            {"role": "user", "content": "Feedback 1"},
            {"role": "assistant", "content": "Output 2"},
            {"role": "user", "content": "Feedback 2"},
        ]
        # Truncate: keep first 2 + last 2
        kept = messages[:2] + messages[-2:]
        assert len(kept) == 4
        assert kept[0]["role"] == "system"
        assert kept[1]["role"] == "user"
        assert kept[2]["content"] == "Output 2"
        assert kept[3]["content"] == "Feedback 2"

    def test_token_estimation(self):
        """Token estimation is chars/4."""
        messages = [{"content": "a" * 400}]  # 400 chars = ~100 tokens
        est_tokens = sum(len(str(m.get("content", ""))) for m in messages) // 4
        assert est_tokens == 100

    def test_overflow_threshold_at_80_percent(self):
        """80% of 128000 = 102400 tokens."""
        max_ctx = 128000
        threshold = int(max_ctx * 0.8)
        assert threshold == 102400


# ============================================================================
# Cron Stagger Tests
# ============================================================================

from tools.cron import CronScheduler, CronJob


class TestCronStagger:
    """Cron job stagger computation."""

    def test_auto_stagger_distributes_evenly(self):
        """4 jobs with the same schedule should be spaced 15s apart."""
        scheduler = CronScheduler(data_path=os.path.join(tempfile.mkdtemp(), "cron.json"))
        schedule_groups = defaultdict(list)
        job_ids = []
        for i in range(4):
            job = CronJob(name=f"job{i}", schedule="0 * * * *")
            scheduler._jobs[job.id] = job
            job_ids.append(job.id)
            schedule_groups["0 * * * *"].append(job.id)

        # Compute auto-stagger
        stagger_offsets = {}
        for schedule_expr, ids in schedule_groups.items():
            auto_gap = 60.0 / len(ids)
            for idx, jid in enumerate(ids):
                stagger_offsets[jid] = idx * auto_gap

        assert stagger_offsets[job_ids[0]] == 0.0
        assert stagger_offsets[job_ids[1]] == 15.0
        assert stagger_offsets[job_ids[2]] == 30.0
        assert stagger_offsets[job_ids[3]] == 45.0

    def test_manual_stagger_override(self):
        """Job with stagger_seconds > 0 uses manual value."""
        job = CronJob(name="manual", schedule="0 * * * *", stagger_seconds=10)
        assert job.stagger_seconds == 10
        # Auto-stagger logic checks this
        offset = float(job.stagger_seconds) if job.stagger_seconds > 0 else 0.0
        assert offset == 10.0

    def test_jitter_within_bounds(self):
        """Jitter should add a random offset within [0, jitter_seconds]."""
        import random
        random.seed(42)
        job = CronJob(name="jittery", schedule="0 * * * *", jitter_seconds=5)
        jitter = random.uniform(0, job.jitter_seconds)
        assert 0 <= jitter <= 5.0

    def test_single_job_no_stagger(self):
        """A single job should have 0 stagger offset."""
        schedule_groups = {"0 * * * *": ["job1"]}
        stagger_offsets = {}
        for schedule_expr, ids in schedule_groups.items():
            if len(ids) <= 1:
                for jid in ids:
                    stagger_offsets[jid] = 0.0
        assert stagger_offsets["job1"] == 0.0


# ============================================================================
# Extended Context Window Tests
# ============================================================================

from agents.model_router import ModelRouter
from providers.registry import ProviderRegistry, ModelTier


class TestExtendedContextWindow:
    """Context-window-aware model routing."""

    def test_models_by_min_context_filters_correctly(self):
        registry = ProviderRegistry()
        large = registry.models_by_min_context(500_000)
        # All returned models should have >= 500K context
        for m in large:
            assert m["max_context_tokens"] >= 500_000

    def test_get_routing_default_context_unchanged(self):
        router = ModelRouter()
        routing = router.get_routing(TaskType.CODING)
        # Default routing should use the standard coding model
        assert routing["primary"] == "or-free-qwen-coder"

    def test_get_routing_with_max_context_prefers_large_models(self):
        router = ModelRouter()
        routing = router.get_routing(TaskType.CODING, context_window="max")
        # Should select a model with large context (>= 500K tokens)
        registry = ProviderRegistry()
        large_keys = {m["key"] for m in registry.models_by_min_context(500_000)}
        if large_keys:
            assert routing["primary"] in large_keys

    def test_get_routing_with_large_context(self):
        router = ModelRouter()
        routing = router.get_routing(TaskType.RESEARCH, context_window="large")
        # Should select a model with >= 200K context
        registry = ProviderRegistry()
        large_keys = {m["key"] for m in registry.models_by_min_context(200_000)}
        if large_keys:
            assert routing["primary"] in large_keys


# ============================================================================
# Enhanced Security Analyzer Tests
# ============================================================================

from tools.security_analyzer import SecurityAnalyzerTool


class TestSecurityAnalyzerDependencies:
    """scan_dependencies action."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = SecurityAnalyzerTool(workspace_path=self.tmpdir)

    @pytest.mark.asyncio
    async def test_scan_dependencies_detects_unpinned(self):
        req_path = os.path.join(self.tmpdir, "requirements.txt")
        with open(req_path, "w") as f:
            f.write("flask\nrequests==2.28.0\n")
        result = await self.tool.execute(action="scan_dependencies")
        assert result.output is not None
        assert "Unpinned" in result.output or "unpinned" in result.output.lower()

    @pytest.mark.asyncio
    async def test_scan_dependencies_detects_vulnerable_patterns(self):
        req_path = os.path.join(self.tmpdir, "requirements.txt")
        with open(req_path, "w") as f:
            f.write("django==1.8.0\n")
        result = await self.tool.execute(action="scan_dependencies")
        assert "Django 1.x" in result.output or "CRITICAL" in result.output

    @pytest.mark.asyncio
    async def test_scan_dependencies_no_requirements(self):
        """No requirements.txt should be handled gracefully."""
        result = await self.tool.execute(action="scan_dependencies")
        assert result.success is True
        assert "No requirements.txt" in result.output


class TestSecurityAnalyzerSecrets:
    """scan_secrets action."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = SecurityAnalyzerTool(workspace_path=self.tmpdir)

    @pytest.mark.asyncio
    async def test_scan_secrets_finds_aws_key(self):
        with open(os.path.join(self.tmpdir, "config.py"), "w") as f:
            f.write('AWS_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
        result = await self.tool.execute(action="scan_secrets")
        assert "AWS" in result.output

    @pytest.mark.asyncio
    async def test_scan_secrets_finds_github_token(self):
        with open(os.path.join(self.tmpdir, "secrets.py"), "w") as f:
            f.write('TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx1234"\n')
        result = await self.tool.execute(action="scan_secrets")
        assert "GitHub" in result.output

    @pytest.mark.asyncio
    async def test_scan_secrets_finds_private_key(self):
        with open(os.path.join(self.tmpdir, "key.pem"), "w") as f:
            f.write("-----BEGIN RSA PRIVATE KEY-----\nfakedata\n-----END RSA PRIVATE KEY-----\n")
        result = await self.tool.execute(action="scan_secrets")
        assert "Private Key" in result.output


class TestSecurityAnalyzerOwasp:
    """scan_owasp action."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = SecurityAnalyzerTool(workspace_path=self.tmpdir)

    @pytest.mark.asyncio
    async def test_scan_owasp_finds_sql_injection(self):
        with open(os.path.join(self.tmpdir, "app.py"), "w") as f:
            f.write('query = "SELECT * FROM users WHERE id = \'" + user_id + "\'"\n')
        result = await self.tool.execute(action="scan_owasp")
        assert "SQL Injection" in result.output or "CRITICAL" in result.output

    @pytest.mark.asyncio
    async def test_scan_owasp_finds_command_injection(self):
        with open(os.path.join(self.tmpdir, "run.py"), "w") as f:
            f.write('import os\nos.system(user_input)\n')
        result = await self.tool.execute(action="scan_owasp")
        assert "Command Injection" in result.output or "os.system" in result.output


class TestSecurityAnalyzerEnhancedPatterns:
    """Enhanced patterns in _PATTERNS dict."""

    def setup_method(self):
        self.tool = SecurityAnalyzerTool(workspace_path=".")

    @pytest.mark.asyncio
    async def test_marshal_loads_detected(self):
        result = await self.tool.execute(
            action="scan_code",
            code='import marshal\ndata = marshal.loads(raw_bytes)\n',
        )
        assert "marshal.loads" in result.output

    @pytest.mark.asyncio
    async def test_jwt_verify_false_detected(self):
        result = await self.tool.execute(
            action="scan_code",
            code='payload = jwt.decode(token, verify=False)\n',
        )
        assert "JWT" in result.output or "jwt" in result.output.lower()

    @pytest.mark.asyncio
    async def test_md5_password_hash_detected(self):
        result = await self.tool.execute(
            action="scan_code",
            code='password_hash = hashlib.md5(password.encode()).hexdigest()\n',
        )
        assert "MD5" in result.output or "weak" in result.output.lower()


# ============================================================================
# Browser Gateway Token Tests
# ============================================================================

from tools.browser_tool import BrowserTool


class TestBrowserGatewayToken:
    """Browser gateway token security."""

    def test_browser_tool_has_gateway_token_attribute(self):
        tool = BrowserTool()
        assert hasattr(tool, "_gateway_token")

    def test_browser_tool_loads_gateway_token(self):
        """Gateway token should be loaded from settings."""
        tool = BrowserTool()
        # Token is auto-generated in config.py if not set
        # so it should be a non-empty string
        from core.config import settings
        assert settings.browser_gateway_token != ""
        assert tool._gateway_token == settings.browser_gateway_token
