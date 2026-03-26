---
phase: quick
plan: 260325-uwr
type: execute
wave: 1
depends_on: []
files_modified:
  - .claude/hooks/memory-learn.py
  - .agent42/memory/HISTORY.md
  - .agent42/memory/MEMORY.md
  - memory/search_service.py
autonomous: true
---

<objective>
Fix four issues in Agent42's memory system: (1) Qdrant vectorization gap where hook-written history entries bypass Qdrant indexing, (2) duplicate sections in MEMORY.md, (3) noisy learned-patterns.json entries polluting HISTORY.md, (4) format inconsistency between old and new HISTORY.md entry styles.

Purpose: The memory system is Agent42's long-term knowledge store. With 60+ history entries but only 11 vectorized in Qdrant, semantic recall is severely degraded. Noisy entries and duplicates further dilute signal quality.

Output: Clean HISTORY.md and MEMORY.md files, working vectorization pipeline for hook-generated entries, and noise filtering in the hook.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.claude/hooks/memory-learn.py
@tools/memory_tool.py
@memory/store.py
@memory/search_service.py
@.agent42/memory/HISTORY.md
@.agent42/memory/MEMORY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix Qdrant vectorization gap and add noise filtering in memory-learn.py</name>
  <files>.claude/hooks/memory-learn.py, memory/search_service.py</files>
  <action>
Two root causes must be fixed:

**Root Cause A — Hook posts to non-existent endpoint:**
The hook at line 280-295 tries to POST to `{search_url}/index`, but `memory/search_service.py` only exposes `/search` and `/health` — there is no `/index` endpoint. The POST silently fails, so hook-generated entries are never vectorized.

Fix by adding an `/index` endpoint to `memory/search_service.py`:
- Accept POST with JSON body: `{"text": "...", "section": "session", "action": "index"}`
- Generate embedding using the already-loaded `_model`
- Upsert into Qdrant `agent42_history` collection with payload: `{"text": text, "event_type": section, "summary": text, "timestamp": time.time(), "source": "hook"}`
- Use a deterministic point ID (UUID5 from the text content) to avoid duplicates on retry
- Return 200 on success, 500 on failure
- Use the same vector dimensions as the existing collections (384 for all-MiniLM-L6-v2)
- If `_model` or `_qdrant_client` is None, return 503 with error message

**Root Cause B — Noise filtering:**
The hook logs every trivial `learned-patterns.json` modification. Lines 293-401 of HISTORY.md show dozens of entries like:
`[2026-03-20 12:22:34] Modified: .claude/learned-patterns.json | Changes: 1 file changed, 2 insertions(+), 2 deletions(-)`

Add a noise filter in `memory-learn.py` in the `_git_summary()` function or right after `extract_session_summary()` returns. Skip the entry if ALL of these are true:
- The summary is a "Modified:" type (from git diff fallback)
- The ONLY file modified is `.claude/learned-patterns.json` (no other files)
- The changes are trivial (e.g., "1 file changed, 2 insertions")

Implement this as a function `is_noise_entry(summary: str) -> bool` that returns True for entries where the only modified file is `learned-patterns.json`. Check this right after `extract_session_summary()` in `main()`, before the dedup check. If `is_noise_entry(summary)` returns True, `sys.exit(0)`.

Also add similar filtering for entries where the only modified files are exclusively from `.planning/` (config.json, active-workstream, etc.) with no code changes — these are GSD bookkeeping, not meaningful session history.
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && python -m pytest tests/test_memory_hooks.py -x -q 2>&1 | tail -5</automated>
  </verify>
  <done>
  - memory/search_service.py has a working /index endpoint that vectorizes entries into Qdrant
  - memory-learn.py has noise filtering that skips learned-patterns.json-only and .planning/-only entries
  - Existing tests still pass
  </done>
</task>

<task type="auto">
  <name>Task 2: Clean HISTORY.md and MEMORY.md — remove noise, deduplicate, standardize format</name>
  <files>.agent42/memory/HISTORY.md, .agent42/memory/MEMORY.md</files>
  <action>
**HISTORY.md cleanup (3 operations):**

1. **Remove noise entries** — Delete all entries that match the noise pattern:
   - Entries where the only file modified is `.claude/learned-patterns.json` (approximately 20+ entries from 2026-03-20, lines ~293-401)
   - Entries where the only files modified are `.planning/active-workstream`, `.planning/config.json` with no other code files
   - Keep entries that have multiple files including real code changes (e.g., `dashboard/server.py`, `.claude/hooks/*.py`)

2. **Remove duplicate entries** — Several entries appear 2-3x (duplicated during hook debugging on 2026-03-20). For example, lines 251-267 show the same "Modified: .claude/hooks/context-loader.py, .claude/hooks/memory-learn.py..." entry repeated 6 times. Keep only one of each unique entry.

3. **Standardize format** — All entries should use the original markdown format with `###` headings:
   - OLD (flat, post-2026-03-20): `[2026-03-20 11:00:19] Modified: ...`
   - NEW (standardized): `### [2026-03-20 11:00:19 UTC] session\nModified: ...\n\n---\n`
   - Convert all flat-format entries (starting from line 242) to the `### [timestamp] type` format with `---` separators
   - Use event_type "session" for Modified entries, "memory" for Summary entries, keep existing types for entries that already have them

**MEMORY.md cleanup (deduplication):**

Remove duplicate sections and entries. Specifically:
- **Auth Patterns** section: has JWT_SECRET and bcrypt entries each duplicated (lines 68-72). Keep one of each.
- **Auth Lessons** section: bcrypt entry appears twice (lines 90-92). Keep one. This section overlaps with Auth Patterns and Authentication — merge into a single "Authentication" section combining unique entries from Auth Patterns + Auth Lessons + Authentication.
- **Deployment** section: has 4 entries, 2 of which overlap conceptually (deploy workflow + ssh deploy). Keep all 4 since they cover different aspects.
- Remove the empty duplicate lines between entries (extra blank lines after bullet points).

Do NOT remove or modify the YAML frontmatter at the top of MEMORY.md (lines 1-4).
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && python -c "
h = open('.agent42/memory/HISTORY.md').read()
noise = h.count('learned-patterns.json | Changes: 1 file changed, 2 insertions')
dupes = [l for l in h.split('---') if 'learned-patterns.json' in l and '1 file changed, 2' in l]
print(f'Noise entries remaining: {noise}')
print(f'Total entries: {len([e for e in h.split(chr(10)+\"---\"+chr(10)) if e.strip()])}')
assert noise == 0, f'Still have {noise} noise entries'

m = open('.agent42/memory/MEMORY.md').read()
auth_sections = m.count('## Auth Patterns') + m.count('## Auth Lessons')
print(f'Auth Patterns + Auth Lessons sections: {auth_sections} (should be 0, merged into Authentication)')
print('PASS')
"</automated>
  </verify>
  <done>
  - HISTORY.md has zero learned-patterns.json-only noise entries
  - HISTORY.md has no duplicate entries (each unique event appears once)
  - HISTORY.md uses consistent ### [timestamp] type format throughout
  - MEMORY.md has no duplicate sections (Auth Patterns, Auth Lessons merged into Authentication)
  - MEMORY.md has no duplicate bullet points within sections
  </done>
</task>

<task type="auto">
  <name>Task 3: Backfill unvectorized HISTORY.md entries into Qdrant</name>
  <files></files>
  <action>
After Tasks 1 and 2 are complete (clean HISTORY.md + working /index endpoint), backfill the cleaned history entries into Qdrant's `agent42_history` collection.

Write a one-time Python script (do NOT commit it — add to .gitignore or delete after) that:

1. Reads the cleaned `.agent42/memory/HISTORY.md`
2. Parses all entries (split by `\n---\n`)
3. For each entry, extracts: timestamp, event_type, summary text
4. Connects to Qdrant at localhost:6333
5. Checks `agent42_history` collection — for each entry, generates a deterministic UUID5 point_id from the summary text (same namespace as search_service.py uses)
6. Skips entries already in Qdrant (by point_id)
7. For new entries: generates embedding using ONNX embedder from `memory/embeddings.py` (`_find_onnx_model_dir()` + `_OnnxEmbedder`)
8. Upserts into `agent42_history` with payload: `{"text": summary, "event_type": type, "summary": summary, "timestamp": parsed_timestamp, "source": "backfill"}`
9. Prints progress: "Vectorized N new entries, skipped M existing"

Run the script and verify the point count increased. Before running, confirm Qdrant is available:
```bash
curl -s http://localhost:6333/collections/agent42_history | python -m json.tool
```

After the script runs successfully, delete it and verify the new point count:
```bash
curl -s http://localhost:6333/collections/agent42_history | python -c "import json,sys; d=json.load(sys.stdin); print(f'Points: {d[\"result\"][\"points_count\"]}')"
```

Expected: point count should increase from 11 to roughly 25-35 (the number of meaningful entries after cleanup).
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && python -c "
import urllib.request, json
resp = urllib.request.urlopen('http://localhost:6333/collections/agent42_history')
data = json.loads(resp.read())
count = data['result']['points_count']
print(f'agent42_history points: {count}')
assert count > 15, f'Expected >15 vectorized entries, got {count}'
print('PASS')
"</automated>
  </verify>
  <done>
  - agent42_history collection has >15 points (up from 11)
  - All meaningful history entries from the cleaned HISTORY.md are vectorized
  - No temporary scripts remain in the repo
  </done>
</task>

</tasks>

<verification>
1. `python -m pytest tests/test_memory_hooks.py -x -q` passes (hook changes are safe)
2. HISTORY.md has zero noise entries (learned-patterns.json-only)
3. HISTORY.md uses consistent format throughout
4. MEMORY.md has no duplicate sections
5. Qdrant agent42_history collection has >15 points
6. New hook-generated entries will be vectorized via the /index endpoint (when search service is running)
</verification>

<success_criteria>
- Memory system produces clean, deduplicated records
- Hook-generated history entries reach Qdrant via search service /index endpoint
- Historical entries backfilled into Qdrant for semantic recall
- Noise filtering prevents future pollution of history log
</success_criteria>

<output>
After completion, create `.planning/quick/260325-uwr-fix-agent42-memory-system-4-issues-vecto/260325-uwr-SUMMARY.md`
</output>
