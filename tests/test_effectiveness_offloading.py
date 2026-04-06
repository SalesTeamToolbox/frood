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
