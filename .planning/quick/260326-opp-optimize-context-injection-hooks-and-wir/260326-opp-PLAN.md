---
phase: quick
plan: 260326-opp
type: execute
wave: 1
depends_on: []
files_modified:
  - .claude/hooks/context-loader.py
  - .claude/hooks/memory-recall.py
  - dashboard/server.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "Context-loader hook re-uses cached file content within a session instead of re-reading disk on every prompt"
    - "Memory-recall hook caches search results for identical/similar prompts within a short TTL"
    - "/api/stats/tokens endpoint returns real jcodemunch token savings data instead of zeros"
  artifacts:
    - path: ".claude/hooks/context-loader.py"
      provides: "Session-cached file reads for lessons.md and reference docs"
      contains: "_file_cache"
    - path: ".claude/hooks/memory-recall.py"
      provides: "TTL-based search result cache keyed on prompt keywords"
      contains: "_search_cache"
    - path: "dashboard/server.py"
      provides: "Token stats endpoint wired to jcodemunch-stats.json"
      contains: "jcodemunch-stats"
  key_links:
    - from: ".claude/hooks/context-loader.py"
      to: ".claude/reference/*.md"
      via: "mtime-checked file cache (skip read when mtime unchanged)"
      pattern: "_file_cache"
    - from: ".claude/hooks/memory-recall.py"
      to: "search service / Qdrant"
      via: "keyword-keyed result cache with 60s TTL"
      pattern: "_search_cache"
    - from: "dashboard/server.py"
      to: ".claude/.jcodemunch-stats.json"
      via: "async file read in get_token_stats endpoint"
      pattern: "jcodemunch-stats"
---

<objective>
Reduce token waste from context injection hooks and wire up the token usage dashboard endpoint.

Purpose: Every user prompt triggers full disk reads (context-loader) and HTTP searches (memory-recall) even when content hasn't changed. The token stats endpoint returns zeros despite real usage data existing in jcodemunch-stats.json.

Output: Optimized hooks with session caching, functioning token stats endpoint.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/hooks/context-loader.py
@.claude/hooks/memory-recall.py
@dashboard/server.py (lines 1040-1060, 1093-1284)
@.claude/hooks/jcodemunch-token-tracker.py (stats file format reference)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add mtime-based file cache to context-loader and TTL search cache to memory-recall</name>
  <files>.claude/hooks/context-loader.py, .claude/hooks/memory-recall.py</files>
  <action>
**context-loader.py** — Add module-level mtime-based file cache to avoid re-reading unchanged files:

1. Add a module-level dict `_file_cache: dict[str, tuple[float, str]] = {}` mapping file path to `(mtime, content)`.
2. Create helper `def _cached_read(path: str) -> str` that:
   - Calls `os.stat(path).st_mtime`
   - If path is in `_file_cache` and mtime matches, return cached content
   - Otherwise read file, store `(mtime, content)` in `_file_cache`, return content
   - On any OSError, return "" (same as current behavior)
3. Update `load_lessons()` (line 371) to use `_cached_read(lessons_path)` instead of `open(lessons_path)`.
4. Update `load_reference_files()` (line 419) to use `_cached_read(path)` instead of `open(path)`.

This avoids re-reading potentially large files like pitfalls-archive.md on every prompt. The mtime check costs one stat() syscall vs reading the entire file.

Note: Module-level state persists across invocations only if the hook is kept alive by the hook runner. If each invocation is a fresh process, the cache warms on first call and serves on subsequent calls within that process. This is still beneficial because Claude Code's hook runner may batch UserPromptSubmit hooks. Even if not, the pattern is correct and adds zero overhead.

**memory-recall.py** — Add TTL-based search result cache keyed on sorted keywords:

1. Add module-level `_search_cache: dict[str, tuple[float, list]] = {}` and `_SEARCH_CACHE_TTL = 60` (seconds).
2. Create helper `def _cache_key(keywords: list[str]) -> str` that returns `"|".join(sorted(keywords))`.
3. Create helper `def _get_cached_search(key: str) -> list | None` that returns cached results if key exists and `time.time() - timestamp < _SEARCH_CACHE_TTL`, else returns None.
4. Create helper `def _set_cached_search(key: str, results: list) -> None` that stores `(time.time(), results)` in `_search_cache`.
5. In `main()`, after extracting keywords (line 591), compute `cache_key = _cache_key(keywords)`.
6. Before the search layers (line 595), check `cached = _get_cached_search(cache_key)`. If cached, use it directly and skip all search layers.
7. After the search layers complete and deduplication/sorting (around line 643), call `_set_cached_search(cache_key, memories)`.
8. Add `import time` at the top (already partially imported via other paths but make it explicit).

This prevents redundant HTTP calls to the search service / Qdrant when consecutive prompts have similar keywords (common during iterative work).
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && python -c "
import json, sys
# Verify context-loader has cache
with open('.claude/hooks/context-loader.py') as f:
    src = f.read()
assert '_file_cache' in src, 'Missing _file_cache'
assert '_cached_read' in src, 'Missing _cached_read'
assert 'st_mtime' in src, 'Missing mtime check'

# Verify memory-recall has cache
with open('.claude/hooks/memory-recall.py') as f:
    src = f.read()
assert '_search_cache' in src, 'Missing _search_cache'
assert '_SEARCH_CACHE_TTL' in src, 'Missing TTL constant'
assert '_cache_key' in src, 'Missing _cache_key helper'

# Verify both still parse correctly
import py_compile
py_compile.compile('.claude/hooks/context-loader.py', doraise=True)
py_compile.compile('.claude/hooks/memory-recall.py', doraise=True)

# Smoke test: context-loader with empty stdin
import subprocess
r = subprocess.run([sys.executable, '.claude/hooks/context-loader.py'], input='{}', capture_output=True, text=True, timeout=5)
assert r.returncode == 0, f'context-loader exit {r.returncode}: {r.stderr}'

# Smoke test: memory-recall with empty stdin
r = subprocess.run([sys.executable, '.claude/hooks/memory-recall.py'], input='{}', capture_output=True, text=True, timeout=5)
assert r.returncode == 0, f'memory-recall exit {r.returncode}: {r.stderr}'

print('All checks passed')
"
    </automated>
  </verify>
  <done>
    - context-loader.py uses mtime-cached file reads; `_file_cache` dict and `_cached_read()` helper exist
    - memory-recall.py has `_search_cache` with 60s TTL; identical keyword sets skip HTTP calls
    - Both hooks still pass smoke test (exit 0 on empty input, no import errors)
  </done>
</task>

<task type="auto">
  <name>Task 2: Wire /api/stats/tokens to read jcodemunch-stats.json</name>
  <files>dashboard/server.py</files>
  <action>
Update the `get_token_stats` endpoint (line 1044-1059) to read real data from the jcodemunch stats file.

Since v2.0/v3.0, Agent42 no longer makes LLM calls directly — it orchestrates Claude Code agents. The real token usage data lives in `.claude/.jcodemunch-stats.json` (written by the jcodemunch-token-tracker.py hook). The stats file has this schema (from jcodemunch-token-tracker.py):

```python
{
    "session_start": float,
    "last_updated": float,
    "calls": int,
    "tokens_used": int,
    "tokens_avoided": int,
    "tokens_saved": int,
    "files_targeted": int,
    "tool_breakdown": {
        "tool_name": {"calls": int, "saved": int}
    }
}
```

Implementation:

1. At the top of the `get_token_stats` function body, build the stats file path:
   ```python
   import aiofiles
   stats_path = os.path.join(settings.workspace_dir or ".", ".claude", ".jcodemunch-stats.json")
   ```
   Use `settings.workspace_dir` if available, otherwise fall back to checking `os.environ.get("AGENT42_WORKSPACE", ".")`. Check what `settings` fields are available for workspace path — look at `core/config.py` Settings class.

2. Read the file with `aiofiles` (per project rules — all I/O async):
   ```python
   jcm_stats = {}
   try:
       async with aiofiles.open(stats_path, mode='r') as f:
           jcm_stats = json.loads(await f.read())
   except (OSError, json.JSONDecodeError):
       pass
   ```

3. Populate the response with jcodemunch data:
   ```python
   total_tokens = jcm_stats.get("tokens_used", 0)
   tokens_saved = jcm_stats.get("tokens_saved", 0)
   total_calls = jcm_stats.get("calls", 0)
   by_tool = jcm_stats.get("tool_breakdown", {})

   return {
       "total_tokens": total_tokens,
       "total_prompt_tokens": 0,  # jcodemunch doesn't distinguish prompt/completion
       "total_completion_tokens": 0,
       "by_model": {},  # No per-model breakdown from jcodemunch
       "daily_spend_usd": 0.0,
       "daily_tokens": total_tokens,
       "jcodemunch": {
           "tokens_used": total_tokens,
           "tokens_saved": tokens_saved,
           "tokens_avoided": jcm_stats.get("tokens_avoided", 0),
           "calls": total_calls,
           "files_targeted": jcm_stats.get("files_targeted", 0),
           "by_tool": by_tool,
           "session_start": jcm_stats.get("session_start"),
           "last_updated": jcm_stats.get("last_updated"),
       },
   }
   ```

4. Ensure `aiofiles` is imported at top of server.py (check if already imported — it likely is since the project uses it everywhere). Also ensure `os` and `json` are imported (they almost certainly are).

Do NOT modify `_build_reports()` — it has its own token aggregation path for the reports page. This change only affects the lightweight `/api/stats/tokens` endpoint.
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && python -c "
import json, sys

# Verify server.py has jcodemunch stats reading
with open('dashboard/server.py') as f:
    src = f.read()
assert 'jcodemunch-stats' in src or 'jcodemunch_stats' in src or 'jcm_stats' in src, 'Missing jcodemunch stats reading'
assert 'aiofiles' in src, 'Missing aiofiles import'

# Verify it still parses
import py_compile
py_compile.compile('dashboard/server.py', doraise=True)

print('All checks passed')
"
    </automated>
  </verify>
  <done>
    - `/api/stats/tokens` reads `.claude/.jcodemunch-stats.json` via aiofiles
    - Response includes `jcodemunch` sub-object with tokens_used, tokens_saved, calls, by_tool breakdown
    - Gracefully returns zeros when stats file doesn't exist
    - server.py compiles without errors
  </done>
</task>

</tasks>

<verification>
1. Both hooks compile: `python -m py_compile .claude/hooks/context-loader.py .claude/hooks/memory-recall.py`
2. Both hooks exit 0 on empty JSON input: `echo '{}' | python .claude/hooks/context-loader.py && echo '{}' | python .claude/hooks/memory-recall.py`
3. Dashboard server compiles: `python -m py_compile dashboard/server.py`
4. Integration: start Agent42 (`python agent42.py`), hit `/api/stats/tokens` — should return jcodemunch data if stats file exists, zeros if not
</verification>

<success_criteria>
- context-loader.py avoids re-reading files when mtime is unchanged (mtime-based cache)
- memory-recall.py skips HTTP search calls when keywords match a cached result within 60s
- /api/stats/tokens returns real jcodemunch token savings data instead of hardcoded zeros
- All three files compile and pass smoke tests
- No behavioral regression: hooks still detect work types, surface memories, and exit 0 on edge cases
</success_criteria>

<output>
After completion, create `.planning/quick/260326-opp-optimize-context-injection-hooks-and-wir/260326-opp-SUMMARY.md`
</output>
