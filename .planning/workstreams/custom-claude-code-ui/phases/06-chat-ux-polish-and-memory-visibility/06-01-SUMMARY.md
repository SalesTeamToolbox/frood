---
phase: 06-chat-ux-polish-and-memory-visibility
plan: 01
status: complete
requirements_completed: [UX-01, UX-03]
---

# Summary: Fix Duplicate Answers + Suppress Init Noise

## What Was Built

**Backend (`dashboard/server.py`):**
- `has_streamed_text` flag added to `session_state` (initialized to `False`, set `True` on first `stream_event` text_delta, reset `False` on `result` event)
- `assistant` event fallback now guarded by `if not session_state.get("has_streamed_text")` — eliminates duplicate answers when PTY streaming is active
- `system.init` handler replaced: no longer emits one `status` envelope per MCP server; now emits a single `init_progress` envelope with `phase: "ready"` and server list
- `system.hook_started` handler changed from `status` to `init_progress` type

**Frontend (`dashboard/frontend/dist/app.js`):**
- `_lastTurnHash` property added to tab object (belt-and-suspenders dedup for reconnect edge cases)
- `turn_complete` handler computes `contentHash` and skips rendering if it matches `_lastTurnHash`; removes duplicate wrapper from DOM
- `text_delta` handler removes `.cc-init-chip` before creating assistant bubble (auto-dismiss on first real token)
- New `init_progress` message type handler: creates `.cc-init-chip` on first call; updates existing chip text on subsequent calls

**CSS (`dashboard/frontend/dist/style.css`):**
- `.cc-init-chip` — compact `inline-flex` pill with `border-radius: 1rem`
- `.cc-init-spinner` — spinning border animation via `@keyframes ccInitSpin`

## Acceptance Criteria: All Met

- `grep -c "has_streamed_text" dashboard/server.py` → 5 ✓
- `grep -c "init_progress" dashboard/server.py` → 4 ✓
- `grep -c "cc-init-chip" dashboard/frontend/dist/app.js` → 5 ✓
- `grep -c "_lastTurnHash" dashboard/frontend/dist/app.js` → 3 ✓
- `python -m pytest tests/test_cc_bridge.py tests/test_cc_pty.py -x -q` → 12 passed ✓
