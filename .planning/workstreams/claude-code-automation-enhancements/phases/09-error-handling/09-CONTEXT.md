---
gathered: 2026-03-05
status: Ready for planning
source: Codebase analysis via jcodemunch
---

# Phase 9: Error Handling and User Feedback - Context

## Phase Boundary

Add comprehensive error messaging and loading indicators throughout the application. Expose backend error classification to users with actionable feedback and visual progress indicators.

## Implementation Decisions (Locked)

### Error Classification Exposure
- Backend error categories (`payment_error`, `auth_error`, `rate_limited`) must be exposed via API responses
- All API errors must include: `error_code`, `message` (human readable), `action` (what user should do)
- Error codes must be consistent across backend and frontend

### Loading States
- Every async operation must show visual feedback within 200ms
- Tasks: spinner while agent is working, progress indicator for multi-step tasks
- Chat: typing indicator during response generation
- API calls: loading state on buttons during submission

### Error Display Patterns
- Toast notifications for transient errors (auto-dismiss 5s)
- Inline error messages for form validation
- Persistent banners for connection issues
- Modal for critical errors requiring action

### Timeout Handling
- API calls: 30s timeout with countdown warning at 25s
- Agent tasks: timeout shown in UI with extend option
- WebSocket: reconnect indicator after 5s disconnection

## Claude's Discretion

- Specific toast/notification UI library (vanilla vs lightweight component)
- Spinner animation style (CSS vs Lottie)
- Error message copy/tone (formal vs conversational)
- Color scheme for error states (red variations)
- Position of loading indicators (inline vs overlay vs corner)

## Specific Ideas

### From Codebase Analysis (jcodemunch)

**Existing error handling backend:**
```python
# agents/iteration_engine.py lines 228-255
_is_auth_error()   - Returns True for 401/auth errors
_is_payment_error() - Returns True for 402 payment errors
_is_rate_limited()  - Returns True for 429 rate-limit errors
```

**Gap:** These categorize errors for retry logic but don't expose them to users.

**Pattern to follow:**
```python
# core/app_manager.py line 733
mark_error(app_id, error)  # Already exposes app errors
```

**Requirements from v1.1-ROADMAP.md:**
- ERR-01: All API errors display user-friendly messages with actionable steps
- ERR-02: Loading states are shown during long operations
- ERR-03: Timeout handling works correctly for all network requests
- FEED-01: Tasks show progress indicators (not just spinning)
- FEED-02: Chat shows "Agent is thinking..." during response generation

## Deferred Ideas

- Error telemetry/analytics (collect error patterns)
- User-triggered retry with exponential backoff
- Offline mode with operation queueing
- Optimistic UI updates with rollback on error

---

*Phase: 09-error-handling*
*Context gathered: 2026-03-05 via jcodemunch analysis*
