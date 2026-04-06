"""
Unit tests for Phase 43 effectiveness workflow offloading.

Covers:
- New DB tables (tool_sequences, workflow_suggestions, workflow_mappings)
- record_sequence() with upsert, threshold, compound unique index, single-tool skip
- create_suggestion(), get_pending_suggestions(), mark_suggestion_status()
- record_workflow_mapping()
- Config fields n8n_pattern_threshold, n8n_auto_create_workflows
- Graceful degradation when aiosqlite unavailable
"""

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path):
    """Create a fresh EffectivenessStore for each test."""
    from memory.effectiveness import EffectivenessStore

    return EffectivenessStore(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Schema tests — verify all 3 new tables exist with correct columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_sequences_table_schema(store):
    """tool_sequences table must have correct columns."""
    import aiosqlite

    await store._ensure_db()
    async with aiosqlite.connect(store._db_path) as db:
        async with db.execute("PRAGMA table_info(tool_sequences)") as cursor:
            cols = {row[1] for row in await cursor.fetchall()}
    expected = {
        "id",
        "agent_id",
        "task_type",
        "tool_sequence",
        "execution_count",
        "first_seen",
        "last_seen",
        "fingerprint",
        "status",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


@pytest.mark.asyncio
async def test_workflow_suggestions_table_schema(store):
    """workflow_suggestions table must have correct columns."""
    import aiosqlite

    await store._ensure_db()
    async with aiosqlite.connect(store._db_path) as db:
        async with db.execute("PRAGMA table_info(workflow_suggestions)") as cursor:
            cols = {row[1] for row in await cursor.fetchall()}
    expected = {
        "id",
        "agent_id",
        "task_type",
        "fingerprint",
        "tool_sequence",
        "execution_count",
        "tokens_saved_estimate",
        "suggested_at",
        "status",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


@pytest.mark.asyncio
async def test_workflow_mappings_table_schema(store):
    """workflow_mappings table must have correct columns."""
    import aiosqlite

    await store._ensure_db()
    async with aiosqlite.connect(store._db_path) as db:
        async with db.execute("PRAGMA table_info(workflow_mappings)") as cursor:
            cols = {row[1] for row in await cursor.fetchall()}
    expected = {
        "id",
        "agent_id",
        "fingerprint",
        "workflow_id",
        "webhook_url",
        "template",
        "created_at",
        "last_triggered",
        "trigger_count",
        "status",
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


# ---------------------------------------------------------------------------
# record_sequence() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_sequence_inserts_first_row(store):
    """First call inserts row with execution_count=1; returns None (below threshold=3)."""
    result = await store.record_sequence("a1", "coding", ["http_client", "data_tool"])
    assert result is None  # count=1 < threshold=3


@pytest.mark.asyncio
async def test_record_sequence_upserts_count(store):
    """Same agent+task_type+tools increments execution_count on each call."""
    import aiosqlite

    await store.record_sequence("a1", "coding", ["http_client", "data_tool"])
    await store.record_sequence("a1", "coding", ["http_client", "data_tool"])
    count_result = await store.record_sequence("a1", "coding", ["http_client", "data_tool"])

    # Third call hits threshold=3 — should return 3
    assert count_result == 3

    # Verify DB has execution_count=3
    async with aiosqlite.connect(store._db_path) as db:
        async with db.execute(
            "SELECT execution_count FROM tool_sequences WHERE agent_id='a1' AND task_type='coding'"
        ) as cursor:
            row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 3


@pytest.mark.asyncio
async def test_record_sequence_compound_unique_different_agent(store):
    """Different agent_id with same tool_names creates a separate row."""
    import aiosqlite

    await store.record_sequence("agent-A", "coding", ["http_client", "data_tool"])
    await store.record_sequence("agent-B", "coding", ["http_client", "data_tool"])

    async with aiosqlite.connect(store._db_path) as db:
        async with db.execute(
            "SELECT agent_id, execution_count FROM tool_sequences WHERE task_type='coding'"
        ) as cursor:
            rows = await cursor.fetchall()
    agents = {r[0] for r in rows}
    assert "agent-A" in agents
    assert "agent-B" in agents
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_record_sequence_skips_single_tool(store):
    """Single-tool sequence (len < 2) returns None without inserting."""
    import aiosqlite

    result = await store.record_sequence("a1", "coding", ["shell"])
    assert result is None

    await store._ensure_db()
    async with aiosqlite.connect(store._db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM tool_sequences") as cursor:
            row = await cursor.fetchone()
    assert row[0] == 0


@pytest.mark.asyncio
async def test_record_sequence_skips_empty_tools(store):
    """Empty tool list returns None without inserting."""
    import aiosqlite

    result = await store.record_sequence("a1", "coding", [])
    assert result is None

    await store._ensure_db()
    async with aiosqlite.connect(store._db_path) as db:
        async with db.execute("SELECT COUNT(*) FROM tool_sequences") as cursor:
            row = await cursor.fetchone()
    assert row[0] == 0


# ---------------------------------------------------------------------------
# create_suggestion() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_suggestion_inserts_row(store):
    """create_suggestion() writes row with status='pending' and correct token estimate."""
    import aiosqlite

    await store.create_suggestion(
        agent_id="a1",
        task_type="coding",
        fingerprint="fp-test-001",
        tool_names=["http_client", "data_tool"],
        execution_count=5,
    )

    async with aiosqlite.connect(store._db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM workflow_suggestions WHERE fingerprint='fp-test-001'"
        ) as cursor:
            row = dict(await cursor.fetchone())

    assert row["status"] == "pending"
    assert row["tokens_saved_estimate"] == 5 * 1000
    assert row["agent_id"] == "a1"
    assert row["task_type"] == "coding"


# ---------------------------------------------------------------------------
# get_pending_suggestions() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_pending_suggestions_returns_list(store):
    """get_pending_suggestions() returns list of dicts with expected keys."""
    await store.create_suggestion("a1", "coding", "fp-001", ["http_client", "data_tool"], 5)

    results = await store.get_pending_suggestions("a1")
    assert isinstance(results, list)
    assert len(results) == 1
    row = results[0]
    assert "fingerprint" in row
    assert "tool_sequence" in row
    assert "execution_count" in row
    assert "tokens_saved_estimate" in row
    assert "task_type" in row


@pytest.mark.asyncio
async def test_get_pending_suggestions_empty_for_unknown_agent(store):
    """get_pending_suggestions() returns empty list for unknown agent."""
    results = await store.get_pending_suggestions("nonexistent-agent")
    assert results == []


# ---------------------------------------------------------------------------
# mark_suggestion_status() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_suggestion_status_suggested(store):
    """mark_suggestion_status to 'suggested' removes from pending results."""
    await store.create_suggestion("a1", "coding", "fp-001", ["http_client", "data_tool"], 5)

    # Before: should appear in pending
    before = await store.get_pending_suggestions("a1")
    assert len(before) == 1

    await store.mark_suggestion_status("fp-001", "a1", "suggested")

    # After: should NOT appear in pending
    after = await store.get_pending_suggestions("a1")
    assert len(after) == 0


@pytest.mark.asyncio
async def test_mark_suggestion_status_dismissed(store):
    """mark_suggestion_status to 'dismissed' works without error."""
    await store.create_suggestion("a1", "coding", "fp-002", ["shell", "data_tool"], 4)
    await store.mark_suggestion_status("fp-002", "a1", "dismissed")

    results = await store.get_pending_suggestions("a1")
    assert len(results) == 0


# ---------------------------------------------------------------------------
# record_workflow_mapping() tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_workflow_mapping_inserts_row(store):
    """record_workflow_mapping() inserts row with status='active'."""
    import aiosqlite

    await store.create_suggestion("a1", "coding", "fp-map-001", ["http_client", "data_tool"], 5)
    await store.record_workflow_mapping(
        agent_id="a1",
        fingerprint="fp-map-001",
        workflow_id="wf-123",
        webhook_url="http://n8n:5678/webhook/abc",
        template="{}",
    )

    async with aiosqlite.connect(store._db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM workflow_mappings WHERE fingerprint='fp-map-001'"
        ) as cursor:
            row = dict(await cursor.fetchone())

    assert row["status"] == "active"
    assert row["workflow_id"] == "wf-123"
    assert row["webhook_url"] == "http://n8n:5678/webhook/abc"
    assert row["agent_id"] == "a1"


# ---------------------------------------------------------------------------
# Config field tests
# ---------------------------------------------------------------------------


def test_settings_n8n_pattern_threshold_default():
    """Settings.n8n_pattern_threshold defaults to 3."""
    from core.config import Settings

    s = Settings()
    assert s.n8n_pattern_threshold == 3


def test_settings_n8n_auto_create_workflows_default():
    """Settings.n8n_auto_create_workflows defaults to False."""
    from core.config import Settings

    s = Settings()
    assert s.n8n_auto_create_workflows is False


def test_settings_from_env_reads_n8n_pattern_threshold(monkeypatch):
    """from_env() reads N8N_PATTERN_THRESHOLD env var."""
    monkeypatch.setenv("N8N_PATTERN_THRESHOLD", "7")
    from core.config import Settings

    s = Settings.from_env()
    assert s.n8n_pattern_threshold == 7


def test_settings_from_env_reads_n8n_auto_create_workflows(monkeypatch):
    """from_env() reads N8N_AUTO_CREATE_WORKFLOWS env var."""
    monkeypatch.setenv("N8N_AUTO_CREATE_WORKFLOWS", "true")
    from core.config import Settings

    s = Settings.from_env()
    assert s.n8n_auto_create_workflows is True


# ---------------------------------------------------------------------------
# Graceful degradation test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_sequence_graceful_degradation(tmp_path, monkeypatch):
    """record_sequence() returns None gracefully when AIOSQLITE_AVAILABLE is False."""
    import memory.effectiveness as eff_module

    monkeypatch.setattr(eff_module, "AIOSQLITE_AVAILABLE", False)
    from memory.effectiveness import EffectivenessStore

    store = EffectivenessStore(tmp_path / "test_degrade.db")
    result = await store.record_sequence("a1", "coding", ["http_client", "data_tool"])
    assert result is None


# ---------------------------------------------------------------------------
# Task-context accumulator tests (Plan 01, Task 2)
# ---------------------------------------------------------------------------


def test_append_tool_to_task():
    """append_tool_to_task accumulates tools, pop_task_tools returns and cleans up."""
    from core.task_context import _current_task_tools, append_tool_to_task, pop_task_tools

    task_id = "test-accumulator-001"
    _current_task_tools.pop(task_id, None)

    append_tool_to_task(task_id, "http_client")
    append_tool_to_task(task_id, "data_tool")
    assert _current_task_tools[task_id] == ["http_client", "data_tool"]

    result = pop_task_tools(task_id)
    assert result == ["http_client", "data_tool"]
    assert task_id not in _current_task_tools


def test_append_tool_empty_task_id():
    """Empty or None task_id does not create entries."""
    from core.task_context import _current_task_tools, append_tool_to_task

    before = len(_current_task_tools)
    append_tool_to_task("", "http_client")
    append_tool_to_task(None, "http_client")
    assert len(_current_task_tools) == before


def test_pop_task_tools_missing_key():
    """pop_task_tools returns empty list for unknown task_id."""
    from core.task_context import pop_task_tools

    result = pop_task_tools("nonexistent-task-id-xyz")
    assert result == []


# ---------------------------------------------------------------------------
# Plan 02 integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_accumulates_tools(tmp_path):
    """ToolRegistry.execute() appends tool_name to task accumulator."""
    from core.task_context import begin_task, end_task, pop_task_tools
    from core.task_types import TaskType
    from memory.effectiveness import EffectivenessStore
    from tools.base import Tool, ToolResult
    from tools.registry import ToolRegistry

    class FakeTool(Tool):
        name = "fake_tool"
        description = "Test"
        parameters = {"type": "object", "properties": {}}

        async def execute(self, **kwargs):
            return ToolResult(output="ok", success=True)

    store = EffectivenessStore(tmp_path / "test.db")
    registry = ToolRegistry(effectiveness_store=store)
    registry.register(FakeTool())

    ctx = begin_task(TaskType.CODING)
    await registry.execute("fake_tool", agent_id="test-agent")
    await registry.execute("fake_tool", agent_id="test-agent")

    tools = pop_task_tools(ctx.task_id)
    assert tools == ["fake_tool", "fake_tool"]
    end_task(ctx)


def test_end_task_pops_accumulator():
    """end_task() always pops the accumulator, preventing memory leaks."""
    from core.task_context import _current_task_tools, append_tool_to_task, begin_task, end_task
    from core.task_types import TaskType

    ctx = begin_task(TaskType.CODING)
    append_tool_to_task(ctx.task_id, "tool_a")
    append_tool_to_task(ctx.task_id, "tool_b")
    assert ctx.task_id in _current_task_tools

    end_task(ctx)
    assert ctx.task_id not in _current_task_tools


@pytest.mark.asyncio
async def test_build_prompt_injects_suggestions(tmp_path):
    """_build_prompt() injects automation suggestions from pending patterns."""

    from core.agent_runtime import AgentRuntime
    from memory.effectiveness import EffectivenessStore, set_shared_store

    store = EffectivenessStore(tmp_path / "test.db")
    set_shared_store(store)

    await store.create_suggestion(
        agent_id="test-agent",
        task_type="coding",
        fingerprint="abc123",
        tool_names=["http_client", "data_tool"],
        execution_count=5,
    )

    runtime = AgentRuntime(workspace=str(tmp_path))
    agent_config = {
        "id": "test-agent",
        "name": "TestBot",
        "description": "A test agent",
        "tools": ["n8n_create_workflow"],
    }
    prompt = await runtime._build_prompt(agent_config)

    assert "AUTOMATION SUGGESTION" in prompt
    assert "http_client -> data_tool" in prompt
    assert "5 times" in prompt
    assert "5000 tokens" in prompt
    assert "n8n_create_workflow" in prompt

    set_shared_store(None)


@pytest.mark.asyncio
async def test_build_prompt_no_suggestions_when_none_pending(tmp_path):
    """_build_prompt() works normally with no pending suggestions."""
    from core.agent_runtime import AgentRuntime
    from memory.effectiveness import EffectivenessStore, set_shared_store

    store = EffectivenessStore(tmp_path / "test.db")
    set_shared_store(store)

    runtime = AgentRuntime(workspace=str(tmp_path))
    agent_config = {"id": "no-suggestions-agent", "name": "Bot", "description": "test"}
    prompt = await runtime._build_prompt(agent_config)

    assert "AUTOMATION SUGGESTION" not in prompt
    assert "You are Bot" in prompt

    set_shared_store(None)


@pytest.mark.asyncio
async def test_suggestion_marked_suggested_after_injection(tmp_path):
    """After injection, suggestion status changes from 'pending' to 'suggested'."""
    from core.agent_runtime import AgentRuntime
    from memory.effectiveness import EffectivenessStore, set_shared_store

    store = EffectivenessStore(tmp_path / "test.db")
    set_shared_store(store)

    await store.create_suggestion(
        agent_id="agent-x",
        task_type="coding",
        fingerprint="fp001",
        tool_names=["tool_a", "tool_b"],
        execution_count=3,
    )

    runtime = AgentRuntime(workspace=str(tmp_path))
    prompt1 = await runtime._build_prompt({"id": "agent-x", "name": "Bot", "description": ""})
    assert "AUTOMATION SUGGESTION" in prompt1

    prompt2 = await runtime._build_prompt({"id": "agent-x", "name": "Bot", "description": ""})
    assert "AUTOMATION SUGGESTION" not in prompt2

    set_shared_store(None)


@pytest.mark.asyncio
async def test_build_prompt_graceful_without_store(tmp_path):
    """_build_prompt() works normally when no shared store is set."""
    from core.agent_runtime import AgentRuntime
    from memory.effectiveness import set_shared_store

    set_shared_store(None)

    runtime = AgentRuntime(workspace=str(tmp_path))
    prompt = await runtime._build_prompt({"id": "agent", "name": "Bot", "description": "test"})

    assert "You are Bot" in prompt
    assert "AUTOMATION SUGGESTION" not in prompt


@pytest.mark.asyncio
async def test_create_workflow_records_mapping(tmp_path):
    """record_workflow_mapping records mapping and marks suggestion as created."""
    import aiosqlite

    from memory.effectiveness import EffectivenessStore, set_shared_store

    store = EffectivenessStore(tmp_path / "test.db")
    set_shared_store(store)
    await store._ensure_db()

    await store.record_workflow_mapping(
        agent_id="test-agent",
        fingerprint="fp-wiring-test",
        workflow_id="wf-123",
        webhook_url="http://n8n:5678/webhook/agent42-fp-wiring",
        template="webhook_to_http",
    )

    async with aiosqlite.connect(str(tmp_path / "test.db")) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM workflow_mappings WHERE fingerprint = ?",
            ("fp-wiring-test",),
        ) as cursor:
            row = await cursor.fetchone()
            assert row is not None
            assert dict(row)["workflow_id"] == "wf-123"
            assert dict(row)["webhook_url"] == "http://n8n:5678/webhook/agent42-fp-wiring"
            assert dict(row)["status"] == "active"

    set_shared_store(None)
