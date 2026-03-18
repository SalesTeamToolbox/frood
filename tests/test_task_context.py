"""Tests for task metadata foundation (Phase 20: TMETA-01 through TMETA-04)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.task_context import TaskContext, begin_task, end_task, get_task_context
from core.task_types import TaskType


class TestTaskTypeEnum:
    """TMETA-01: TaskType enum has correct members."""

    def test_has_eight_members(self):
        assert len(TaskType) == 8

    def test_values_are_lowercase_strings(self):
        for member in TaskType:
            assert member.value == member.value.lower()
            assert isinstance(member.value, str)

    def test_expected_members(self):
        expected = {
            "coding",
            "debugging",
            "research",
            "content",
            "strategy",
            "app_create",
            "marketing",
            "general",
        }
        actual = {t.value for t in TaskType}
        assert actual == expected

    def test_coding_value(self):
        assert TaskType.CODING.value == "coding"

    def test_all_member_names(self):
        names = {t.name for t in TaskType}
        assert "CODING" in names
        assert "DEBUGGING" in names
        assert "RESEARCH" in names
        assert "GENERAL" in names


class TestLifecycle:
    """TMETA-04: begin_task/end_task lifecycle protocol."""

    def test_begin_task_returns_task_context(self):
        ctx = begin_task(TaskType.CODING)
        assert isinstance(ctx, TaskContext)
        assert ctx.task_id is not None
        assert len(ctx.task_id) == 36  # UUID format
        assert ctx.task_type == TaskType.CODING
        end_task(ctx)

    def test_context_set_during_task(self):
        ctx = begin_task(TaskType.DEBUGGING)
        task_id, task_type = get_task_context()
        assert task_id == ctx.task_id
        assert task_type == "debugging"
        end_task(ctx)

    def test_context_cleared_after_end_task(self):
        ctx = begin_task(TaskType.RESEARCH)
        end_task(ctx)
        task_id, task_type = get_task_context()
        assert task_id is None
        assert task_type is None

    def test_no_context_outside_task(self):
        task_id, task_type = get_task_context()
        assert task_id is None
        assert task_type is None

    def test_nested_tasks(self):
        outer = begin_task(TaskType.CODING)
        outer_id = outer.task_id
        inner = begin_task(TaskType.DEBUGGING)
        inner_id = inner.task_id

        # Inner is active
        tid, tt = get_task_context()
        assert tid == inner_id
        assert tt == "debugging"

        # End inner — outer restored
        end_task(inner)
        tid, tt = get_task_context()
        assert tid == outer_id
        assert tt == "coding"

        end_task(outer)

    def test_task_ids_are_unique(self):
        ctx1 = begin_task(TaskType.GENERAL)
        id1 = ctx1.task_id
        end_task(ctx1)
        ctx2 = begin_task(TaskType.GENERAL)
        id2 = ctx2.task_id
        end_task(ctx2)
        assert id1 != id2

    def test_get_task_context_returns_string_value_not_enum(self):
        """get_task_context must return a string, not the enum member."""
        ctx = begin_task(TaskType.APP_CREATE)
        _, task_type = get_task_context()
        assert task_type == "app_create"
        assert isinstance(task_type, str)
        end_task(ctx)


class TestPayloadInjection:
    """TMETA-01: Memory entries include task_id/task_type in Qdrant payload."""

    @pytest.mark.asyncio
    async def test_index_history_entry_includes_task_fields(self):
        """index_history_entry adds task_id and task_type to upsert payload."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        mock_qdrant.upsert_single = MagicMock(return_value=True)

        from memory.embeddings import EmbeddingStore

        store = EmbeddingStore.__new__(EmbeddingStore)
        store._qdrant = mock_qdrant
        store._onnx_model = None
        store._client = None
        store._provider_resolved = True

        with patch.object(store, "embed_text", new_callable=AsyncMock, return_value=[0.1] * 384):
            ctx = begin_task(TaskType.CODING)
            await store.index_history_entry("test_event", "test summary", "details")
            end_task(ctx)

        # Verify upsert_single was called with task fields in payload
        mock_qdrant.upsert_single.assert_called_once()
        call_args = mock_qdrant.upsert_single.call_args
        # payload is the 4th positional arg or keyword arg
        payload = call_args[1].get("payload") if call_args[1] else call_args[0][3]
        assert payload["task_id"] == ctx.task_id
        assert payload["task_type"] == "coding"

    @pytest.mark.asyncio
    async def test_index_history_entry_omits_task_fields_outside_task(self):
        """Outside a task, payload has no task_id or task_type."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        mock_qdrant.upsert_single = MagicMock(return_value=True)

        from memory.embeddings import EmbeddingStore

        store = EmbeddingStore.__new__(EmbeddingStore)
        store._qdrant = mock_qdrant
        store._onnx_model = None
        store._client = None
        store._provider_resolved = True

        with patch.object(store, "embed_text", new_callable=AsyncMock, return_value=[0.1] * 384):
            await store.index_history_entry("test_event", "test summary")

        call_args = mock_qdrant.upsert_single.call_args
        payload = call_args[1].get("payload") if call_args[1] else call_args[0][3]
        assert "task_id" not in payload
        assert "task_type" not in payload


class TestPayloadInjectionAddEntry:
    """TMETA-01: add_entry stores task fields in metadata."""

    @pytest.mark.asyncio
    async def test_add_entry_includes_task_fields_in_metadata(self):
        from memory.embeddings import EmbeddingStore

        store = EmbeddingStore.__new__(EmbeddingStore)
        store._qdrant = None
        store._onnx_model = None
        store._client = None
        store._provider_resolved = True
        store._loaded = True
        store._entries = []
        store.store_path = MagicMock()

        with patch.object(store, "embed_text", new_callable=AsyncMock, return_value=[0.1] * 384):
            with patch.object(store, "_save"):
                ctx = begin_task(TaskType.RESEARCH)
                entry = await store.add_entry("test text", source="test")
                end_task(ctx)

        assert entry.metadata["task_id"] == ctx.task_id
        assert entry.metadata["task_type"] == "research"

    @pytest.mark.asyncio
    async def test_add_entry_omits_task_fields_outside_task(self):
        from memory.embeddings import EmbeddingStore

        store = EmbeddingStore.__new__(EmbeddingStore)
        store._qdrant = None
        store._onnx_model = None
        store._client = None
        store._provider_resolved = True
        store._loaded = True
        store._entries = []
        store.store_path = MagicMock()

        with patch.object(store, "embed_text", new_callable=AsyncMock, return_value=[0.1] * 384):
            with patch.object(store, "_save"):
                entry = await store.add_entry("test text", source="test")

        assert "task_id" not in entry.metadata
        assert "task_type" not in entry.metadata

    @pytest.mark.asyncio
    async def test_add_entry_preserves_existing_metadata(self):
        """Existing metadata keys are preserved alongside task fields."""
        from memory.embeddings import EmbeddingStore

        store = EmbeddingStore.__new__(EmbeddingStore)
        store._qdrant = None
        store._onnx_model = None
        store._client = None
        store._provider_resolved = True
        store._loaded = True
        store._entries = []
        store.store_path = MagicMock()

        with patch.object(store, "embed_text", new_callable=AsyncMock, return_value=[0.1] * 384):
            with patch.object(store, "_save"):
                ctx = begin_task(TaskType.CODING)
                entry = await store.add_entry(
                    "test text", source="test", metadata={"custom_key": "custom_value"}
                )
                end_task(ctx)

        assert entry.metadata["custom_key"] == "custom_value"
        assert entry.metadata["task_id"] == ctx.task_id
        assert entry.metadata["task_type"] == "coding"


class TestPayloadIndexes:
    """TMETA-03: Qdrant payload indexes on task_type and task_id."""

    def test_ensure_collection_creates_indexes_for_memory(self):
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = set()

        store._ensure_collection(QdrantStore.MEMORY)

        # Should call create_payload_index for task_type and task_id
        index_calls = mock_client.create_payload_index.call_args_list
        field_names = [c[1].get("field_name") or c[0][1] for c in index_calls]
        assert "task_type" in field_names
        assert "task_id" in field_names

    def test_ensure_collection_creates_indexes_for_history(self):
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = set()

        store._ensure_collection(QdrantStore.HISTORY)

        index_calls = mock_client.create_payload_index.call_args_list
        field_names = [c[1].get("field_name") or c[0][1] for c in index_calls]
        assert "task_type" in field_names
        assert "task_id" in field_names

    def test_no_indexes_for_conversations(self):
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = set()

        store._ensure_collection(QdrantStore.CONVERSATIONS)

        # create_payload_index should NOT be called for task fields
        for call_obj in mock_client.create_payload_index.call_args_list:
            field_name = call_obj[1].get("field_name") or call_obj[0][1]
            assert field_name not in ("task_type", "task_id")

    def test_no_indexes_for_knowledge(self):
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = set()

        store._ensure_collection(QdrantStore.KNOWLEDGE)

        for call_obj in mock_client.create_payload_index.call_args_list:
            field_name = call_obj[1].get("field_name") or call_obj[0][1]
            assert field_name not in ("task_type", "task_id")

    def test_ensure_task_indexes_is_idempotent(self):
        """Calling _ensure_task_indexes twice doesn't crash."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_client.get_collections.return_value = MagicMock(collections=[])

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = set()

        # Call twice — should not raise
        store._ensure_task_indexes("agent42_memory")
        store._ensure_task_indexes("agent42_memory")


class TestBackwardCompat:
    """TMETA-02: Existing entries without task fields remain queryable."""

    def test_unfiltered_search_returns_entries_without_task_fields(self):
        """Entries without task_type/task_id are returned in unfiltered searches."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()

        # Simulate a response with entries that have no task fields
        mock_point = MagicMock()
        mock_point.payload = {
            "text": "old memory",
            "source": "memory",
            "section": "notes",
            "timestamp": 1.0,
        }
        mock_point.score = 0.95
        mock_response = MagicMock()
        mock_response.points = [mock_point]
        mock_client.query_points.return_value = mock_response

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = {QdrantStore.MEMORY}

        results = store.search(QdrantStore.MEMORY, [0.1] * 384, top_k=5)

        assert len(results) == 1
        assert results[0]["text"] == "old memory"
        assert results[0]["score"] == 0.95

    def test_unfiltered_search_returns_entries_with_and_without_task_fields(self):
        """Mix of old (no task fields) and new (with task fields) entries both returned."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()

        old_point = MagicMock()
        old_point.payload = {"text": "old entry", "source": "memory", "timestamp": 1.0}
        old_point.score = 0.90

        new_point = MagicMock()
        new_point.payload = {
            "text": "new entry",
            "source": "memory",
            "timestamp": 2.0,
            "task_id": "abc-123",
            "task_type": "coding",
        }
        new_point.score = 0.85

        mock_response = MagicMock()
        mock_response.points = [old_point, new_point]
        mock_client.query_points.return_value = mock_response

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = {QdrantStore.MEMORY}

        results = store.search(QdrantStore.MEMORY, [0.1] * 384, top_k=5)

        assert len(results) == 2
        texts = [r["text"] for r in results]
        assert "old entry" in texts
        assert "new entry" in texts


# ---------------------------------------------------------------------------
# Plan 02: RETR-01 and RETR-02
# ---------------------------------------------------------------------------


class TestFilteredSearch:
    """RETR-01: search() and search_with_lifecycle() accept task_type_filter."""

    def test_search_with_task_type_filter(self):
        """QdrantStore.search builds FieldCondition for task_type when filter provided."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points.return_value = mock_response

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = {QdrantStore.MEMORY}

        store.search(QdrantStore.MEMORY, [0.1] * 384, task_type_filter="coding")

        # Verify query_filter includes task_type condition
        call_kwargs = mock_client.query_points.call_args[1]
        query_filter = call_kwargs.get("query_filter")
        assert query_filter is not None
        # Filter.must should contain a FieldCondition with key="task_type"
        field_keys = [c.key for c in query_filter.must]
        assert "task_type" in field_keys

    def test_search_without_task_type_filter(self):
        """QdrantStore.search does NOT add task_type filter when filter is empty."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points.return_value = mock_response

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = {QdrantStore.MEMORY}

        store.search(QdrantStore.MEMORY, [0.1] * 384)

        call_kwargs = mock_client.query_points.call_args[1]
        query_filter = call_kwargs.get("query_filter")
        # No filter at all when no filters provided
        assert query_filter is None

    def test_search_with_task_id_filter(self):
        """QdrantStore.search builds FieldCondition for task_id when filter provided."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points.return_value = mock_response

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = {QdrantStore.MEMORY}

        store.search(QdrantStore.MEMORY, [0.1] * 384, task_id_filter="abc-123")

        call_kwargs = mock_client.query_points.call_args[1]
        query_filter = call_kwargs.get("query_filter")
        assert query_filter is not None
        field_keys = [c.key for c in query_filter.must]
        assert "task_id" in field_keys


class TestFilteredSearchLifecycle:
    """RETR-01: search_with_lifecycle() accepts task_type_filter."""

    def test_lifecycle_search_with_task_type_filter(self):
        """search_with_lifecycle with task_type_filter adds condition to filter."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points.return_value = mock_response

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = {QdrantStore.MEMORY}

        store.search_with_lifecycle(QdrantStore.MEMORY, [0.1] * 384, task_type_filter="coding")

        call_kwargs = mock_client.query_points.call_args[1]
        query_filter = call_kwargs.get("query_filter")
        assert query_filter is not None
        # task_type condition should be in must list
        all_must = query_filter.must or []
        task_type_conditions = [c for c in all_must if hasattr(c, "key") and c.key == "task_type"]
        assert len(task_type_conditions) >= 1

    def test_lifecycle_search_without_task_type_filter(self):
        """search_with_lifecycle without task_type_filter has no task_type condition."""
        from memory.qdrant_store import QdrantConfig, QdrantStore

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.points = []
        mock_client.query_points.return_value = mock_response

        config = QdrantConfig(url="http://localhost:6333")
        store = QdrantStore.__new__(QdrantStore)
        store.config = config
        store._client = mock_client
        store._initialized_collections = {QdrantStore.MEMORY}

        store.search_with_lifecycle(QdrantStore.MEMORY, [0.1] * 384)

        call_kwargs = mock_client.query_points.call_args[1]
        query_filter = call_kwargs.get("query_filter")
        # Should have forgotten filter but no task_type
        if query_filter and query_filter.must:
            task_type_conditions = [
                c for c in query_filter.must if hasattr(c, "key") and c.key == "task_type"
            ]
            assert len(task_type_conditions) == 0


class TestEmbeddingStoreFilterPassthrough:
    """RETR-01: EmbeddingStore.search passes task_type_filter to Qdrant."""

    @pytest.mark.asyncio
    async def test_search_passes_task_type_filter(self):
        from memory.embeddings import EmbeddingStore

        store = EmbeddingStore.__new__(EmbeddingStore)
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        store._qdrant = mock_qdrant
        store._provider_resolved = True
        store._onnx_model = None
        store._client = None

        with patch.object(store, "embed_text", new_callable=AsyncMock, return_value=[0.1] * 384):
            with patch.object(store, "_search_qdrant", return_value=[]) as mock_search:
                await store.search("test query", task_type_filter="debugging")

        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        # _search_qdrant is called with positional args or kwargs
        # Check that task_type_filter was passed
        assert "debugging" in str(call_kwargs)


class TestBuildContextSemantic:
    """RETR-02: build_context_semantic passes task_type to filtered search."""

    @pytest.mark.asyncio
    async def test_passes_task_type_to_search(self):
        from memory.store import MemoryStore

        store = MemoryStore.__new__(MemoryStore)
        store.memory_path = MagicMock()
        store.memory_path.read_text.return_value = "# Memory\nSome content"

        mock_embeddings = MagicMock()
        mock_embeddings.is_available = True
        mock_embeddings.search = AsyncMock(return_value=[])
        mock_embeddings.search_conversations = AsyncMock(return_value=[])
        store.embeddings = mock_embeddings
        store._qdrant = None

        await store.build_context_semantic("test query", task_type="coding")

        mock_embeddings.search.assert_called_once()
        call_kwargs = mock_embeddings.search.call_args
        # Verify task_type_filter="coding" was passed
        assert call_kwargs[1].get("task_type_filter") == "coding" or "coding" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_empty_task_type_passes_empty_string(self):
        from memory.store import MemoryStore

        store = MemoryStore.__new__(MemoryStore)
        store.memory_path = MagicMock()
        store.memory_path.read_text.return_value = "# Memory"

        mock_embeddings = MagicMock()
        mock_embeddings.is_available = True
        mock_embeddings.search = AsyncMock(return_value=[])
        mock_embeddings.search_conversations = AsyncMock(return_value=[])
        store.embeddings = mock_embeddings
        store._qdrant = None

        await store.build_context_semantic("test query")

        mock_embeddings.search.assert_called_once()
        call_kwargs = mock_embeddings.search.call_args
        # task_type_filter should be "" (empty) or not present
        ttf = call_kwargs[1].get("task_type_filter", "")
        assert ttf == ""
