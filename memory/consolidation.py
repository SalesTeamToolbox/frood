"""
Memory consolidation pipeline — converts ephemeral conversations into
permanent, searchable knowledge.

Flow:
1. Session messages accumulate in Redis (hot buffer)
2. Periodically, older messages are summarized by an LLM
3. Summaries are embedded and stored in Qdrant for cross-session search
4. Original messages remain in JSONL for audit/replay

This enables Agent42 to answer "what did we discuss last week about X?"
across any channel, without keeping thousands of raw messages in context.
"""

import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("agent42.memory.consolidation")


class ConsolidationRouter:
    """Lightweight LLM router for consolidation summarization.

    Tries cheap/free providers first, falls back through available API keys.
    Implements the .complete(model, messages) -> (text, provider) interface
    expected by ConsolidationPipeline.
    """

    async def complete(self, model: str, messages: list[dict]) -> tuple[str, str | None]:
        """Send a chat completion request through available providers.

        Args:
            model: Model identifier (used as hint; each provider maps to its own model).
            messages: OpenAI-format message list.

        Returns:
            (response_text, provider_name) or raises if all providers fail.
        """
        providers = self._build_provider_chain(model)
        if not providers:
            raise RuntimeError("ConsolidationRouter: no API keys configured")

        last_error = ""
        for name, call in providers:
            try:
                text = await call(messages)
                if text:
                    return text, name
            except Exception as e:
                last_error = f"{name}: {e}"
                logger.debug("ConsolidationRouter: %s failed — %s", name, e)

        raise RuntimeError(f"ConsolidationRouter: all providers failed. Last: {last_error}")

    @property
    def has_providers(self) -> bool:
        """Whether at least one API key is configured."""
        return bool(self._build_provider_chain(""))

    def _build_provider_chain(self, model: str) -> list[tuple[str, object]]:
        """Build ordered list of (name, async_callable) provider attempts."""
        chain = []

        or_key = os.environ.get("OPENROUTER_API_KEY", "")
        if or_key:
            chain.append(
                ("openrouter", lambda msgs, k=or_key, m=model: self._call_openrouter(k, m, msgs))
            )

        synthetic_key = os.environ.get("SYNTHETIC_API_KEY", "")
        if synthetic_key:
            chain.append(
                (
                    "synthetic",
                    lambda msgs, k=synthetic_key: self._call_anthropic_compat(
                        k,
                        "https://api.synthetic.new",
                        msgs,
                    ),
                )
            )

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if anthropic_key:
            base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
            chain.append(
                (
                    "anthropic",
                    lambda msgs, k=anthropic_key, b=base: self._call_anthropic_compat(
                        k,
                        b,
                        msgs,
                    ),
                )
            )

        openai_key = os.environ.get("OPENAI_API_KEY", "")
        if openai_key:
            chain.append(("openai", lambda msgs, k=openai_key: self._call_openai(k, msgs)))

        return chain

    @staticmethod
    async def _call_openrouter(api_key: str, model: str, messages: list[dict]) -> str:
        or_model = model if model and "/" in model else "deepseek/deepseek-chat:free"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": or_model, "messages": messages, "max_tokens": 2048},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    @staticmethod
    async def _call_anthropic_compat(api_key: str, base_url: str, messages: list[dict]) -> str:
        system = ""
        chat_msgs = []
        for m in messages:
            if m.get("role") == "system":
                system += m.get("content", "") + "\n"
            else:
                chat_msgs.append(m)
        body: dict = {
            "model": "claude-sonnet-4-5-20250514",
            "max_tokens": 2048,
            "messages": chat_msgs or messages,
        }
        if system.strip():
            body["system"] = system.strip()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                base_url.rstrip("/") + "/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            return "".join(
                b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text"
            )

    @staticmethod
    async def _call_openai(api_key: str, messages: list[dict]) -> str:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": "gpt-4o-mini", "messages": messages, "max_tokens": 2048},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


@dataclass
class ConversationSummary:
    """A summarized conversation segment."""

    channel_type: str
    channel_id: str
    summary: str
    topics: list[str]
    participants: list[str]
    message_count: int
    time_start: float
    time_end: float


SUMMARIZE_PROMPT = """\
Summarize the following conversation concisely. Focus on:
- Key decisions made
- Important information shared
- Action items or tasks discussed
- Technical details or preferences expressed

Conversation ({channel_type} / {channel_id}):
{messages_text}

Respond with a structured summary:

## Summary
(2-4 sentence summary of the conversation)

## Key Topics
- (topic 1)
- (topic 2)

## Important Details
- (any facts, preferences, or decisions worth remembering)
"""


class ConsolidationPipeline:
    """Consolidates conversation sessions into searchable long-term memory."""

    def __init__(self, model_router=None, embedding_store=None, qdrant_store=None):
        """Initialize the consolidation pipeline.

        Args:
            model_router: ModelRouter for LLM summarization calls
            embedding_store: EmbeddingStore for generating embeddings
            qdrant_store: QdrantStore for storing summaries (optional)
        """
        self.router = model_router
        self.embeddings = embedding_store
        self.qdrant = qdrant_store

    @property
    def is_available(self) -> bool:
        """Whether consolidation can run (needs at minimum a router and embeddings)."""
        return (
            self.router is not None and self.embeddings is not None and self.embeddings.is_available
        )

    async def summarize_messages(
        self,
        messages: list[dict],
        channel_type: str = "",
        channel_id: str = "",
        model: str = "or-free-deepseek-chat",
    ) -> ConversationSummary | None:
        """Summarize a list of messages into a ConversationSummary.

        Args:
            messages: List of message dicts with role, content, timestamp
            channel_type: Channel type for metadata
            channel_id: Channel ID for metadata
            model: LLM model to use for summarization

        Returns:
            ConversationSummary or None if summarization fails.
        """
        if not self.router or not messages:
            return None

        # Build conversation text
        lines = []
        participants = set()
        for msg in messages:
            role = msg.get("role", "unknown")
            sender = msg.get("sender_name", role)
            content = msg.get("content", "")
            lines.append(f"[{sender}]: {content}")
            if sender != "assistant":
                participants.add(sender)

        messages_text = "\n".join(lines)

        # Truncate if too long (keep under ~4000 chars for summarization)
        if len(messages_text) > 4000:
            messages_text = messages_text[:4000] + "\n... (truncated)"

        prompt = SUMMARIZE_PROMPT.format(
            channel_type=channel_type or "unknown",
            channel_id=channel_id or "unknown",
            messages_text=messages_text,
        )

        try:
            summary_text, _ = await self.router.complete(
                model, [{"role": "user", "content": prompt}]
            )
        except Exception as e:
            logger.warning(f"Consolidation: summarization failed — {e}")
            return None

        # Extract topics from the summary
        topics = self._extract_topics(summary_text)

        timestamps = [msg.get("timestamp", 0.0) for msg in messages if msg.get("timestamp")]

        return ConversationSummary(
            channel_type=channel_type,
            channel_id=channel_id,
            summary=summary_text,
            topics=topics,
            participants=list(participants),
            message_count=len(messages),
            time_start=min(timestamps) if timestamps else time.time(),
            time_end=max(timestamps) if timestamps else time.time(),
        )

    async def consolidate_and_store(
        self,
        messages: list[dict],
        channel_type: str = "",
        channel_id: str = "",
        model: str = "or-free-deepseek-chat",
    ) -> ConversationSummary | None:
        """Summarize messages and store the summary in Qdrant.

        This is the main entry point for the consolidation pipeline.
        """
        if not self.is_available:
            logger.debug("Consolidation: pipeline not available (missing router/embeddings)")
            return None

        summary = await self.summarize_messages(messages, channel_type, channel_id, model)
        if not summary:
            return None

        # Embed the summary
        try:
            vector = await self.embeddings.embed_text(summary.summary)
        except Exception as e:
            logger.warning(f"Consolidation: embedding failed — {e}")
            return summary  # Return summary even if storage fails

        # Store in Qdrant if available
        if self.qdrant and self.qdrant.is_available:
            from memory.qdrant_store import QdrantStore

            payload = {
                "source": "conversation_summary",
                "channel_type": channel_type,
                "channel_id": channel_id,
                "topics": summary.topics,
                "participants": summary.participants,
                "message_count": summary.message_count,
                "time_start": summary.time_start,
                "time_end": summary.time_end,
            }
            self.qdrant.upsert_single(
                QdrantStore.CONVERSATIONS,
                summary.summary,
                vector,
                payload,
            )
            logger.info(
                f"Consolidation: stored summary for {channel_type}/{channel_id} "
                f"({summary.message_count} messages -> Qdrant)"
            )
        else:
            # Fallback: store in JSON embedding store
            await self.embeddings.add_entry(
                summary.summary,
                source="conversation_summary",
                section=f"{channel_type}/{channel_id}",
                metadata={
                    "topics": summary.topics,
                    "message_count": summary.message_count,
                },
            )
            logger.info(
                f"Consolidation: stored summary for {channel_type}/{channel_id} "
                f"({summary.message_count} messages -> JSON embeddings)"
            )

        return summary

    async def index_messages(
        self,
        messages: list[dict],
        channel_type: str = "",
        channel_id: str = "",
    ) -> int:
        """Index individual messages into Qdrant for fine-grained search.

        Use this for important messages that should be individually searchable,
        in addition to the conversation summary.

        Returns number of messages indexed.
        """
        if not self.embeddings or not self.embeddings.is_available:
            return 0

        # Filter to substantive messages (skip very short ones)
        substantive = [m for m in messages if len(m.get("content", "")) > 20]
        if not substantive:
            return 0

        texts = [m["content"] for m in substantive]

        try:
            vectors = await self.embeddings.embed_texts(texts)
        except Exception as e:
            logger.warning(f"Consolidation: batch embedding failed — {e}")
            return 0

        if self.qdrant and self.qdrant.is_available:
            from memory.qdrant_store import QdrantStore

            payloads = [
                {
                    "source": "conversation_message",
                    "channel_type": channel_type,
                    "channel_id": channel_id,
                    "role": m.get("role", ""),
                    "sender_name": m.get("sender_name", ""),
                    "section": f"{channel_type}/{channel_id}",
                }
                for m in substantive
            ]
            return self.qdrant.upsert_vectors(QdrantStore.CONVERSATIONS, texts, vectors, payloads)

        return 0

    @staticmethod
    def _extract_topics(summary_text: str) -> list[str]:
        """Extract topic bullet points from the summary text."""
        topics = []
        in_topics = False
        for line in summary_text.split("\n"):
            stripped = line.strip()
            if "## Key Topics" in stripped or "## Topics" in stripped:
                in_topics = True
                continue
            if in_topics:
                if stripped.startswith("##"):
                    break
                if stripped.startswith("- "):
                    topic = stripped[2:].strip()
                    if topic:
                        topics.append(topic)
        return topics
