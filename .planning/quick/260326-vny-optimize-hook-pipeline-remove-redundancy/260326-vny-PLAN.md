# Quick Task 260326-vny: Optimize hook pipeline

## Tasks

### Task 1: Strip context-loader to high-value injections only
Remove lessons.md injection and full reference file loading. Keep only filtered
pitfalls + jcodemunch guidance + GSD nudge + memory nudge.

### Task 2: Consolidate memory-recall
Remove keyword MEMORY.md/HISTORY.md search (layers 2-3). Keep Qdrant semantic
search + session context handoff. Claude Code auto-memory makes keyword search redundant.

### Task 3: Demote proactive-inject
Remove from settings.json. Hook file kept for reference but no longer executed.
Low ROI — requires Agent42 API running, fires once per session.

### Task 4: Verify and measure
Test full pipeline, measure per-prompt token cost across all work types.
