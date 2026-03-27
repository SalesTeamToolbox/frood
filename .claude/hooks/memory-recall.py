#!/usr/bin/env python3
# hook_event: UserPromptSubmit
# hook_timeout: 10
"""Associative memory recall hook — surfaces relevant memories automatically.

Triggered on UserPromptSubmit. Searches Agent42's memory for content relevant
to the user's current prompt and injects it into Claude's context via stderr.

This is the core of Agent42's "human-like memory" — relevant past experiences
surface automatically when context triggers them, without being asked.

Also surfaces previous session's conversation context from handoff.json on the
first prompt of a new session. This ensures decisions and options from the
previous session survive context window clears.

Search strategy (layered, best-available):
0. Previous session context from handoff.json (first prompt only)
1. Semantic search via Qdrant + embeddings (if available)
2. Keyword search on MEMORY.md sections
3. Keyword search on HISTORY.md entries

Hook protocol:
- Receives JSON on stdin: {hook_event_name, project_dir, user_prompt, ...}
- Output to stderr is shown to Claude as context
- Exit code 0 = allow (always allow for this hook)
"""

import json
import os
import re
import sys
import time
from datetime import UTC
from pathlib import Path

# Module-level TTL-based search result cache: cache_key -> (timestamp, results)
_search_cache: dict[str, tuple[float, list]] = {}
_SEARCH_CACHE_TTL = 60  # seconds


def _cache_key(keywords: list[str]) -> str:
    """Build a cache key from sorted keywords."""
    return "|".join(sorted(keywords))


def _get_cached_search(key: str) -> list | None:
    """Return cached results if key exists and within TTL, else None."""
    if key in _search_cache:
        timestamp, results = _search_cache[key]
        if time.time() - timestamp < _SEARCH_CACHE_TTL:
            return results
    return None


def _set_cached_search(key: str, results: list) -> None:
    """Store results in the search cache with current timestamp."""
    _search_cache[key] = (time.time(), results)


# ── Configuration ───────────────────────────────────────────────────────
HIGH_RELEVANCE = 0.85  # Always inject
MEDIUM_RELEVANCE = 0.70  # Inject if domain matches
MIN_KEYWORD_MATCHES = 2  # Minimum keyword hits for text search
MAX_MEMORIES = 3  # Max memories to inject
MAX_OUTPUT_CHARS = 2000  # Rough output cap (~500 tokens)
MIN_PROMPT_LEN = 15  # Skip very short prompts

# Common words to skip during keyword extraction
STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "must",
        "need",
        "let",
        "lets",
        "please",
        "want",
        "like",
        "just",
        "make",
        "get",
        "use",
        "this",
        "that",
        "these",
        "those",
        "its",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "they",
        "them",
        "their",
        "him",
        "her",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "when",
        "where",
        "how",
        "what",
        "which",
        "who",
        "not",
        "no",
        "so",
        "too",
        "very",
        "also",
        "about",
        "to",
        "for",
        "with",
        "from",
        "at",
        "by",
        "on",
        "in",
        "of",
        "up",
        "out",
        "off",
        "over",
        "into",
        "onto",
        "all",
        "any",
        "each",
        "every",
        "some",
        "many",
        "much",
        "more",
        "now",
        "here",
        "there",
        "yes",
        "ok",
        "okay",
        "sure",
        "right",
        "well",
        "done",
    }
)


def extract_keywords(text):
    """Extract meaningful keywords from prompt text."""
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
    keywords = [w for w in words if len(w) >= 3 and w not in STOP_WORDS]
    return list(set(keywords))


def search_memory_sections(content, keywords):
    """Search MEMORY.md for sections matching keywords."""
    if not content.strip():
        return []

    results = []
    # Split into sections (## headings)
    sections = re.split(r"(?m)^## ", content)

    for section in sections:
        if not section.strip():
            continue
        lines = section.strip().split("\n")
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        full_text = f"{title} {body}".lower()

        matches = sum(1 for kw in keywords if kw in full_text)
        if matches >= MIN_KEYWORD_MATCHES:
            score = min(matches / max(len(keywords), 1), 1.0) * 0.7
            # Truncate body for display
            display = body[:250].strip()
            if len(body) > 250:
                display += "..."
            results.append(
                {
                    "text": f"[Memory: {title}] {display}",
                    "score": score,
                    "source": "memory",
                }
            )

    return results


def search_history_entries(content, keywords):
    """Search HISTORY.md for entries matching keywords."""
    if not content.strip():
        return []

    results = []
    # Split on --- separators or double newlines
    if "\n---\n" in content:
        entries = content.split("\n---\n")
    else:
        entries = content.split("\n\n")

    # Only search recent entries (last 100)
    for entry in entries[-100:]:
        entry = entry.strip()
        if not entry or len(entry) < 20:
            continue

        text_lower = entry.lower()
        matches = sum(1 for kw in keywords if kw in text_lower)
        if matches >= MIN_KEYWORD_MATCHES:
            score = min(matches / max(len(keywords), 1), 1.0) * 0.6
            display = entry[:200].strip()
            if len(entry) > 200:
                display += "..."
            results.append(
                {
                    "text": f"[History] {display}",
                    "score": score,
                    "source": "history",
                }
            )

    return results


def try_semantic_search(memory_dir, prompt, agent42_root):
    """Semantic search via the Agent42 search service (HTTP).

    The search service keeps the embedding model loaded in memory,
    so this call is fast (~50ms) instead of 10s for model loading.
    """
    import urllib.error
    import urllib.request

    search_url = os.environ.get("AGENT42_SEARCH_URL", "http://127.0.0.1:6380")

    try:
        data = json.dumps(
            {
                "query": prompt,
                "top_k": MAX_MEMORIES,
                "threshold": 0.20,
            }
        ).encode()

        req = urllib.request.Request(
            f"{search_url}/search",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=3) as resp:
            result = json.loads(resp.read())

        memories = []
        for r in result.get("results", []):
            score = r.get("score", 0)
            text = r.get("text", "").strip()[:250]
            section = r.get("section", "")
            if text:
                label = f"[{section}]" if section else "[Memory]"
                memories.append(
                    {
                        "text": f"{label} {text}",
                        "score": score,
                        "source": "semantic",
                    }
                )
        return memories
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        # Search service not running — fall through to keyword search
        return []


def try_agent42_api_search(prompt):
    """Fallback: query Agent42's memory via its HTTP API.

    The Agent42 server exposes a memory search endpoint that queries Qdrant
    directly. This works when the dedicated search service isn't running but
    the Agent42 dashboard server is.
    """
    import urllib.error
    import urllib.request

    api_url = os.environ.get("AGENT42_API_URL", "http://127.0.0.1:8000")

    try:
        # Try the MCP-exposed memory search via the API
        data = json.dumps({"action": "search", "content": prompt}).encode()

        req = urllib.request.Request(
            f"{api_url}/api/memory/search",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=3) as resp:
            result = json.loads(resp.read())

        memories = []
        for r in result.get("results", []):
            score = r.get("score", r.get("relevance", 0.5))
            text = r.get("text", r.get("content", "")).strip()[:250]
            source = r.get("source", "qdrant")
            if text:
                memories.append(
                    {
                        "text": f"[{source}] {text}",
                        "score": float(score),
                        "source": "agent42-api",
                    }
                )
        return memories
    except (urllib.error.URLError, OSError, json.JSONDecodeError, Exception):
        return []


def try_qdrant_direct_search(keywords):
    """Query Qdrant REST API directly with keyword matching on payloads.

    When both the search service and dashboard are down, we can still query
    Qdrant's REST API directly. Since we don't have embeddings, we scroll
    through all points and do keyword matching on payload text. This works
    well when the collection is small (< 1000 points).
    """
    import urllib.error
    import urllib.request

    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    collections = ["agent42_memory", "agent42_history"]
    memories = []

    for collection in collections:
        try:
            # Scroll all points (fast for small collections)
            data = json.dumps(
                {
                    "limit": 100,
                    "with_payload": True,
                    "with_vector": False,
                }
            ).encode()

            req = urllib.request.Request(
                f"{qdrant_url}/collections/{collection}/points/scroll",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=3) as resp:
                result = json.loads(resp.read())

            points = result.get("result", {}).get("points", [])
            source = collection.replace("agent42_", "")

            for point in points:
                payload = point.get("payload", {})
                text = payload.get("text", payload.get("content", ""))
                section = payload.get("section", "")
                if not text:
                    continue

                # Score by keyword match density
                text_lower = text.lower()
                matches = sum(1 for kw in keywords if kw in text_lower)
                if matches < MIN_KEYWORD_MATCHES:
                    continue

                score = min(matches / max(len(keywords), 1), 1.0) * 0.75
                label = f"[{section}]" if section else f"[{source}]"
                display = text[:250].strip()
                if len(text) > 250:
                    display += "..."

                memories.append(
                    {
                        "text": f"{label} {display}",
                        "score": score,
                        "source": "qdrant-direct",
                    }
                )
        except (urllib.error.URLError, OSError, json.JSONDecodeError, Exception):
            continue

    return memories


def deduplicate(memories):
    """Remove near-duplicate memories by text prefix."""
    seen = set()
    unique = []
    for m in memories:
        key = m.get("text", "")[:80].lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(m)
    return unique


# ── Previous Session Context (Layer 0) ────────────────────────────────────

# Max age for session context to be surfaced (4 hours)
SESSION_CONTEXT_MAX_AGE_S = 4 * 3600
# Max chars for the session context block
SESSION_CONTEXT_MAX_CHARS = 3000
# Guard file to prevent re-surfacing within same session
SESSION_CONTEXT_GUARD = "context-surfaced.json"


def _context_guard_path(project_dir):
    """Return path to the context-surfaced guard file."""
    return os.path.join(project_dir, ".agent42", SESSION_CONTEXT_GUARD)


def is_context_already_surfaced(project_dir, session_id):
    """Check if previous session context was already surfaced this session."""

    guard_path = _context_guard_path(project_dir)
    if not os.path.exists(guard_path):
        return False
    try:
        with open(guard_path, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("session_id") == session_id
    except (json.JSONDecodeError, OSError):
        return False


def mark_context_surfaced(project_dir, session_id):
    """Write guard file to prevent re-surfacing."""
    guard_path = _context_guard_path(project_dir)
    try:
        os.makedirs(os.path.dirname(guard_path), exist_ok=True)
        with open(guard_path, "w", encoding="utf-8") as f:
            import time

            json.dump({"session_id": session_id, "ts": time.time()}, f)
    except OSError:
        pass


def load_previous_session_context(project_dir):
    """Load conversation_context from handoff.json if recent enough.

    Returns the context list and clears it from handoff.json to prevent
    stale re-surfacing on subsequent sessions.
    """

    handoff_path = os.path.join(project_dir, ".claude", "handoff.json")
    if not os.path.exists(handoff_path):
        return []

    try:
        with open(handoff_path, encoding="utf-8") as f:
            handoff = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    context = handoff.get("conversation_context", [])
    if not context:
        return []

    # Check age — only surface if handoff was updated recently
    updated = handoff.get("updated", "")
    if updated:
        try:
            from datetime import datetime

            updated_dt = datetime.fromisoformat(updated)
            if updated_dt.tzinfo is None:
                updated_dt = updated_dt.replace(tzinfo=UTC)
            age_s = (datetime.now(UTC) - updated_dt).total_seconds()
            if age_s > SESSION_CONTEXT_MAX_AGE_S:
                return []
        except (ValueError, TypeError):
            pass  # Can't parse — surface anyway

    return context


def format_session_context(context):
    """Format previous session's conversation context for stderr output."""
    if not context:
        return ""

    lines = [
        "[agent42-session-context] Previous session conversation (for continuity):",
        "---",
    ]

    for entry in context:
        role = entry.get("role", "?")
        content = entry.get("content", "").strip()
        entry_type = entry.get("type", "")

        if not content:
            continue

        if role == "user":
            lines.append(f"  USER: {content}")
        elif role == "assistant":
            if entry_type == "question":
                lines.append(f"  CLAUDE: {content}")
            elif entry_type == "planning":
                lines.append(f"  CLAUDE: {content}")
            elif entry_type == "delegation":
                lines.append(f"  CLAUDE: {content}")
            else:
                lines.append(f"  CLAUDE: {content}")

    lines.append("---")
    lines.append(
        "(This is your previous session's conversation. "
        "Use it to understand references like 'do option 1' or 'proceed with 3'.)"
    )

    output = "\n".join(lines)
    if len(output) > SESSION_CONTEXT_MAX_CHARS:
        output = output[:SESSION_CONTEXT_MAX_CHARS] + "\n  ... (truncated)"

    return output


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    project_dir = event.get("project_dir", ".")
    prompt = ""

    # Extract prompt text
    if "user_prompt" in event:
        prompt = event["user_prompt"]
    elif "messages" in event:
        for msg in reversed(event["messages"]):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    prompt = content
                elif isinstance(content, list):
                    prompt = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
                break

    # Skip short or slash-command prompts
    if not prompt or len(prompt.strip()) < MIN_PROMPT_LEN:
        sys.exit(0)
    if prompt.strip().startswith("/"):
        sys.exit(0)

    # ── Determine session ID for guard ────────────────────────────────────
    import hashlib

    session_id = event.get("session_id", "")
    if not session_id:
        session_id = hashlib.md5(f"{project_dir}-{os.getpid()}".encode()).hexdigest()[:16]

    # ── Layer 0: Previous session context ─────────────────────────────────
    # Surface once per session — gives Claude the previous conversation flow
    if not is_context_already_surfaced(project_dir, session_id):
        prev_context = load_previous_session_context(project_dir)
        if prev_context:
            context_output = format_session_context(prev_context)
            if context_output:
                print(context_output, file=sys.stderr)
        mark_context_surfaced(project_dir, session_id)

    # ── Locate memory directory ──────────────────────────────────────────
    memory_dir = Path(project_dir) / ".agent42" / "memory"
    if not memory_dir.exists():
        sys.exit(0)

    # ── Locate agent42 root (for imports) ────────────────────────────────
    agent42_root = os.environ.get("AGENT42_ROOT", "")
    if not agent42_root:
        hook_dir = Path(__file__).resolve().parent
        possible_root = hook_dir.parent.parent  # .claude/hooks/../../
        if (possible_root / "memory" / "store.py").exists():
            agent42_root = str(possible_root)

    # ── Search memories ──────────────────────────────────────────────────
    keywords = extract_keywords(prompt)
    if not keywords:
        sys.exit(0)

    # Check search cache before hitting any search layers
    search_key = _cache_key(keywords)
    cached_memories = _get_cached_search(search_key)
    if cached_memories is not None:
        memories = cached_memories
        search_source = "cache"
    else:
        memories = []
        search_source = None  # Track which layer provided results

        # Layer 1: Semantic search (best quality, requires embedding API + Qdrant)
        # Try dedicated search service first, then fall back to Agent42 API
        semantic_results = try_semantic_search(memory_dir, prompt, agent42_root)
        if semantic_results:
            search_source = "semantic"
        else:
            semantic_results = try_agent42_api_search(prompt)
            if semantic_results:
                search_source = "agent42-api"
        memories.extend(semantic_results)

        # Layer 1.5: Qdrant direct scroll + keyword match (when search service is down)
        if not semantic_results:
            qdrant_results = try_qdrant_direct_search(keywords)
            if qdrant_results:
                search_source = "qdrant"
            memories.extend(qdrant_results)

        # Layer 2: MEMORY.md keyword search
        memory_file = memory_dir / "MEMORY.md"
        if memory_file.exists():
            try:
                content = memory_file.read_text(encoding="utf-8")
                file_results = search_memory_sections(content, keywords)
                if file_results and not search_source:
                    search_source = "keyword"
                memories.extend(file_results)
            except Exception:
                pass

        # Layer 3: HISTORY.md keyword search
        history_file = memory_dir / "HISTORY.md"
        if history_file.exists():
            try:
                content = history_file.read_text(encoding="utf-8")
                file_results = search_history_entries(content, keywords)
                if file_results and not search_source:
                    search_source = "history"
                memories.extend(file_results)
            except Exception:
                pass

        # ── Rank, deduplicate, and cache ─────────────────────────────────
        memories = deduplicate(memories)
        memories = sorted(memories, key=lambda m: m.get("score", 0), reverse=True)
        memories = memories[:MAX_MEMORIES]
        _set_cached_search(search_key, memories)

    # ── Rank, deduplicate, and inject ────────────────────────────────────
    memories = memories[:MAX_MEMORIES]

    if not memories:
        sys.exit(0)

    source_label = f" via {search_source}" if search_source else ""
    lines = [f"[agent42-memory] Recall: {len(memories)} memories surfaced{source_label}"]
    for m in memories:
        score = m.get("score", 0)
        text = m.get("text", "").strip()
        if text:
            lines.append(f"  - [{score:.0%}] {text}")

    output = "\n".join(lines)
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n  ... (truncated)"

    print(output, file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
