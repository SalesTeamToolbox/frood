---
phase: 02-core-chat-ui
plan: "04"
subsystem: ui
tags: [javascript, websocket, marked, dompurify, highlight.js, streaming, chat-ui]

# Dependency graph
requires:
  - phase: 02-03
    provides: CDN deps in index.html (marked, marked-highlight, hljs, DOMPurify) and .cc-chat-* CSS classes in style.css

provides:
  - ideOpenCCChat() — full chat panel tab connecting to /ws/cc-chat WebSocket
  - ccRenderMarkdown() — marked.parse + DOMPurify.sanitize chain (CHAT-05)
  - Streaming bubble lifecycle: create-on-first-delta, 50ms setInterval flush, finalize on turn_complete
  - ideActivateTab() chatPanel guard — prevents fitAddon.fit() crash on chat panel tabs
  - ideReattachCCTabs() chatPanel skip — chat panel tabs persist DOM, no xterm re-creation

affects:
  - 02-05 (input handling — ccHandleKeydown, ccSend, ccStop, ccInputResize, ccUpdateSlashDropdown)
  - 03-session-persistence (reconnect/resume using ccSessionId)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ccRenderMarkdown: always sanitize marked.parse output via DOMPurify — this is the CHAT-05 locked decision"
    - "Streaming: 50ms setInterval flushes streamBuffer via textContent; turn_complete renders final via ccRenderMarkdown"
    - "chatPanel guard: all ideActivateTab/ideReattachCCTabs branches check tab.chatPanel before calling fitAddon or creating xterm"

key-files:
  created: []
  modified:
    - dashboard/frontend/dist/app.js

key-decisions:
  - "markedHighlight CDN UMD pattern: markedHighlight.markedHighlight (namespace.function) not globalThis.markedHighlight"
  - "Global security hook blocks first occurrence of innerHTML assignment — second attempt allowed; DOMPurify usage is safe"
  - "ideOpenCCChat replaces ideOpenClaude in all onclick HTML strings; ideOpenClaude function kept intact for backward compat"

patterns-established:
  - "ccGetTab(tabIdx): lookup by tabIdx integer not array index — survives tab close/reorder"
  - "ccSetupScrollBehavior: delayed 100ms listener attachment (DOM must be in container before scroll listener works)"
  - "Thinking blocks use HTML5 details/summary element — no JS needed for toggle"

requirements-completed: [CHAT-01, CHAT-02, CHAT-03, CHAT-04, CHAT-05, CHAT-06, CHAT-09]

# Metrics
duration: 11min
completed: 2026-03-18
---

# Phase 02 Plan 04: Core Chat UI - JS Rendering Engine Summary

**ideOpenCCChat() with token-streaming bubble lifecycle, ccRenderMarkdown (marked.parse + DOMPurify), and fitAddon crash fix in ideActivateTab for chat panel tabs**

## Performance

- **Duration:** 11 min
- **Started:** 2026-03-18T17:19:55Z
- **Completed:** 2026-03-18T17:30:51Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Implemented ccRenderMarkdown() with marked.parse() + DOMPurify.sanitize() chain honoring CHAT-05 locked decision
- Implemented ideOpenCCChat() with full WebSocket streaming lifecycle (create-on-first-delta, 50ms flush, turn_complete finalization)
- Fixed ideActivateTab() with tab.chatPanel guard preventing fitAddon.fit() crash when switching to chat panel tabs
- Fixed ideReattachCCTabs() to skip chat panel tabs (no xterm re-creation needed - DOM persists)
- Added ccAppendUserBubble(), ccAppendThinkingBlock(), ccGetTab(), ccSetSendingState(), ccScrollToBottom(), ccSetupScrollBehavior() helpers

## Task Commits

Each task was committed atomically:

1. **Task 1: Add ccRenderMarkdown, fix ideActivateTab, update ideReattachCCTabs** - `099f74d` (feat)
2. **Task 2: Implement ideOpenCCChat with streaming bubble lifecycle** - `11dddde` (feat)

**Plan metadata:** committed with docs commit (see below)

## Files Created/Modified

- `dashboard/frontend/dist/app.js` — Added ~370 lines: _initCCMarkdown, ccRenderMarkdown, ccAppendUserBubble, ccAppendThinkingBlock, ideOpenCCChat, ccGetTab, ccSetSendingState, ccScrollToBottom, ccSetupScrollBehavior; fixed ideActivateTab and ideReattachCCTabs

## Decisions Made

- markedHighlight CDN UMD pattern: the global is a namespace (markedHighlight.markedHighlight), not the function directly (Pitfall 3 from RESEARCH.md)
- Global security_reminder_hook.py PreToolUse hook triggers on first use of innerHTML assignment per session — second attempt succeeds because the warning state is recorded; DOMPurify output is always used so the usage is safe
- ideOpenClaude function definition kept intact; only onclick references in HTML strings changed to ideOpenCCChat

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

- Global security reminder hook (PreToolUse) blocked the first edit containing the innerHTML assignment pattern. The hook is correct to warn; the usage is safe since ccRenderMarkdown always returns DOMPurify-sanitized output. Second attempt succeeded as the warning had been recorded in session state.

## Next Phase Readiness

- Chat panel DOM structure complete with streaming message lifecycle
- CHAT-01 through CHAT-06 and CHAT-09 implemented
- Ready for Plan 02-05: input handling (ccHandleKeydown, ccSend, ccStop, ccInputResize, ccUpdateSlashDropdown, CC_SLASH_COMMANDS)
- Remaining tests in TestCCChatInput and TestCCChatStop will flip GREEN in Plan 02-05

---
*Phase: 02-core-chat-ui*
*Completed: 2026-03-18*
