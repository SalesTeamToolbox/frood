"""
MemoryBridge — scoped memory recall and learning extraction for sidecar agents.

Provides:
- recall():       Scope-filtered semantic search over MEMORY + HISTORY collections,
                  requires agent_id to prevent unfiltered cross-agent data access.
- learn_async():  Fire-and-forget learning extraction via instructor (Gemini/OpenAI),
                  upserts structured learnings into the KNOWLEDGE collection.

Both methods degrade gracefully when Qdrant/embeddings are unavailable — they
return empty results or log and return, never raise outside of documented
ValueError cases.
"""

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger("agent42.sidecar.memory")


class MemoryBridge:
    """Orchestrator-owned memory interface for sidecar agents.

    Owns all memory read/write operations for an agent session. The
    orchestrator instantiates one MemoryBridge per execution context,
    injecting the shared MemoryStore.

    Design decisions:
    - agent_id is required for recall() — unfiltered searches are prohibited
      (D-10: scope-leak prevention).
    - learn_async() is fire-and-forget safe — wraps entire body in try/except
      so callers can use asyncio.create_task() without propagation risk (P7).
    - Calls _qdrant directly instead of going through MemoryStore.semantic_search()
      because semantic_search() lacks agent_id filter support (research OQ1).
    """

    def __init__(self, memory_store: Any = None):
        self.memory_store = memory_store

    async def recall(
        self,
        query: str,
        agent_id: str,
        company_id: str = "",
        top_k: int = 5,
        score_threshold: float = 0.25,
        run_id: str = "",
    ) -> list[dict]:
        """Scope-filtered semantic memory recall.

        Args:
            query:           Natural language query to embed and search.
            agent_id:        Required. Scopes results to this agent only.
            company_id:      Optional. Further scopes to company when provided.
            top_k:           Maximum number of results to return.
            score_threshold: Minimum cosine similarity score (0.0–1.0).
            run_id:          Optional. Tags returned results with which run consumed them (D-22).

        Returns:
            List of dicts with keys: text, score, source, metadata.
            Returns [] on any error or when dependencies are unavailable.

        Raises:
            ValueError: When agent_id is empty (unfiltered recall is prohibited).
        """
        if not agent_id:
            raise ValueError("agent_id is required for recall() — never search unfiltered")

        # Graceful degradation: no memory store or embeddings unavailable
        if not self.memory_store:
            return []
        if not getattr(self.memory_store.embeddings, "is_available", False):
            return []

        qdrant = getattr(self.memory_store, "_qdrant", None)
        if not qdrant or not getattr(qdrant, "is_available", False):
            return []

        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            # Embed query
            query_vector = await self.memory_store.embeddings.embed_text(query)

            # Build agent-scoped filter conditions
            conditions = [FieldCondition(key="agent_id", match=MatchValue(value=agent_id))]
            if company_id:
                conditions.append(
                    FieldCondition(key="company_id", match=MatchValue(value=company_id))
                )
            query_filter = Filter(must=conditions)

            all_results: list[dict] = []

            # Search both MEMORY and HISTORY collections
            for collection_suffix in (qdrant.MEMORY, qdrant.HISTORY):
                try:
                    collection_name = qdrant._collection_name(collection_suffix)
                    qdrant._ensure_collection(collection_suffix)
                    response = qdrant._client.query_points(
                        collection_name=collection_name,
                        query=query_vector,
                        limit=top_k,
                        query_filter=query_filter,
                    )
                    for hit in response.points:
                        payload = hit.payload or {}
                        result_dict: dict = {
                            "text": payload.get("text", ""),
                            "score": round(hit.score, 4),
                            "source": payload.get("source", ""),
                            "metadata": {
                                k: v
                                for k, v in payload.items()
                                if k not in ("text", "source", "timestamp")
                            },
                        }
                        if run_id:
                            result_dict["run_id"] = run_id
                        all_results.append(result_dict)
                except Exception as e:
                    logger.debug("recall: collection %s search failed: %s", collection_suffix, e)

            # Apply score threshold, sort by score descending, take top_k
            filtered = [r for r in all_results if r["score"] >= score_threshold]
            filtered.sort(key=lambda x: x["score"], reverse=True)
            return filtered[:top_k]

        except Exception as e:
            logger.warning("recall failed for agent %s: %s", agent_id, e)
            return []

    async def learn_async(
        self,
        summary: str,
        agent_id: str,
        company_id: str = "",
        task_type: str = "",
        run_id: str = "",
    ) -> None:
        """Extract learnings from an agent execution summary and store in KNOWLEDGE.

        Fire-and-forget safe — never raises. Callers may use
        asyncio.create_task(mb.learn_async(...)) without exception guards.

        Args:
            summary:    Agent execution summary text to extract learnings from.
            agent_id:   Agent whose session produced this summary.
            company_id: Optional company scope for multi-tenant isolation.
            task_type:  Optional task type hint for categorisation.
            run_id:     Optional. Tags Qdrant KNOWLEDGE points with the originating run (D-23).
        """
        try:
            from core.config import settings as _settings

            if not _settings.learning_enabled:
                logger.debug("learn_async: skipping — learning disabled via LEARNING_ENABLED=false")
                return

            if not summary or not agent_id or not self.memory_store:
                logger.debug("learn_async: skipping — missing summary, agent_id, or memory_store")
                return

            qdrant = getattr(self.memory_store, "_qdrant", None)
            if not qdrant or not getattr(qdrant, "is_available", False):
                logger.debug("learn_async: Qdrant unavailable — skipping learning extraction")
                return

            from pydantic import BaseModel as _BaseModel

            class Learning(_BaseModel):
                content: str
                tags: list[str] = []

            class ExtractionResult(_BaseModel):
                learnings: list[Learning] = []

            def _sync_extract(prompt_text: str) -> dict:
                try:
                    import instructor
                    from openai import OpenAI
                except ImportError:
                    logger.info("instructor not installed — skipping learning extraction")
                    return {"learnings": []}

                import os as _os

                # Prefer OpenRouter (Gemini Flash), fall back to OpenAI
                api_key = _os.environ.get("OPENROUTER_API_KEY", "")
                if api_key:
                    client_kwargs = {
                        "api_key": api_key,
                        "base_url": "https://openrouter.ai/api/v1",
                    }
                    model = "google/gemini-2.0-flash-001"
                else:
                    api_key = _os.environ.get("OPENAI_API_KEY", "")
                    if not api_key:
                        return {"learnings": []}
                    client_kwargs = {"api_key": api_key}
                    model = "gpt-4o-mini"

                client = instructor.from_openai(OpenAI(**client_kwargs), mode=instructor.Mode.JSON)
                result = client.chat.completions.create(
                    model=model,
                    response_model=ExtractionResult,
                    max_retries=2,
                    messages=[{"role": "user", "content": prompt_text}],
                )
                return result.model_dump()

            prompt = (
                "Extract key learnings from this agent execution summary. "
                "Return structured JSON.\n\n"
                f"Summary:\n{summary}\n\n"
                f"Agent ID: {agent_id}\n"
                f"Task Type: {task_type}"
            )

            extraction = await asyncio.to_thread(_sync_extract, prompt)

            for learning in extraction.get("learnings", []):
                content = (
                    learning.get("content", "") if isinstance(learning, dict) else learning.content
                )
                tags = learning.get("tags", []) if isinstance(learning, dict) else learning.tags
                if not content:
                    continue

                try:
                    vector = await self.memory_store.embeddings.embed_text(content)
                    payload = {
                        "text": content,
                        "source": "learn_async",
                        "agent_id": agent_id,
                        "company_id": company_id,
                        "task_type": task_type,
                        "tags": tags,
                        "run_id": run_id,
                        "timestamp": time.time(),
                    }
                    await asyncio.to_thread(
                        qdrant.upsert_single,
                        qdrant.KNOWLEDGE,
                        content,
                        vector,
                        payload,
                    )
                    logger.debug(
                        "learn_async: stored learning for agent %s: %.60s", agent_id, content
                    )
                except Exception as e:
                    logger.debug("learn_async: failed to store individual learning: %s", e)

        except Exception as exc:
            logger.warning("learn_async failed for agent %s: %s", agent_id, exc)
