# Phase 9 Research: Error Handling and User Feedback

**Researched:** 2026-03-05
**Status:** Complete

## Research Questions

1. How to unify error handling across all API endpoints?
2. What's the best approach for loading indicators in a vanilla JS dashboard?
3. How to implement graceful timeout handling with user control?

## Technical Findings

### Error Handling Architecture

**Current state (fragmented):**
- `agents/iteration_engine.py` has `_is_*_error()` classifiers but they're internal
- `dashboard/server.py` endpoints return raw HTTPException messages
- No consistent error response format across API

**Implementation approach:**

1. **Create `core/error_codes.py`** with standardized error taxonomy:
```python
class ErrorCode(Enum):
    RATE_LIMITED = "rate_limited"
    AUTH_EXPIRED = "auth_expired"
    PAYMENT_REQUIRED = "payment_required"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"

ERROR_MESSAGES = {
    ErrorCode.RATE_LIMITED: {
        "message": "Too many requests. Slowing down...",
        "action": "Wait a moment and try again"
    },
    # ... etc
}
```

2. **Create FastAPI exception handler** in `dashboard/server.py`:
```python
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    error_code = classify_error(exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": error_code.value,
            "message": ERROR_MESSAGES[error_code]["message"],
            "action": ERROR_MESSAGES[error_code]["action"]
        }
    )
```

### Loading Indicator Patterns

**For vanilla JS dashboard (no framework):**

```javascript
// Safe DOM manipulation (no innerHTML)
class LoadingIndicator {
  constructor(element) {
    this.element = element;
    this.spinner = document.createElement('div');
    this.spinner.className = 'spinner';
  }

  show() { this.element.appendChild(this.spinner); }
  hide() { this.spinner.remove(); }
}

// Progress indicator using safe DOM APIs
class ProgressIndicator {
  constructor(element, steps) {
    this.element = element;
    this.totalSteps = steps;
    this.currentStep = 0;

    // Create elements safely
    this.bar = document.createElement('div');
    this.bar.className = 'progress-bar';
    this.label = document.createElement('span');

    this.element.appendChild(this.bar);
    this.element.appendChild(this.label);
  }

  update(step, message) {
    this.currentStep = step;
    const pct = (step / this.totalSteps * 100).toFixed(1);
    this.bar.style.width = pct + '%';
    this.label.textContent = `${message} (${step}/${this.totalSteps})`; // textContent is safe
  }
}
```

**CSS-only spinner:**
```css
.spinner {
  border: 3px solid #f3f3f3;
  border-top: 3px solid #3498db;
  border-radius: 50%;
  width: 24px;
  height: 24px;
  animation: spin 1s linear infinite;
}
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
```

### Timeout Handling Strategy

**Approach: Warning + User Action**

1. **API calls:**
   - 25s: Show "Taking longer than expected..." warning
   - 30s: Timeout, offer "Retry" or "Continue waiting"

2. **Agent tasks:**
   - WebSocket messages show progress
   - No timeout (agent runs until completion)
   - Show "Working for N minutes" timer

3. **Implementation:**
```javascript
class TimeoutManager {
  constructor(timeoutMs, warningMs) {
    this.timeoutMs = timeoutMs;
    this.warningMs = warningMs;
  }

  async execute(promise) {
    return Promise.race([
      promise,
      new Promise((_, reject) => {
        setTimeout(() => reject(new TimeoutError()), this.timeoutMs);
      })
    ]);
  }
}
```

## Dashboard Integration Points

**From jcodemunch analysis:**

| Component | Current State | Needs |
|-----------|--------------|-------|
| Task creation | No loading state | Spinner on button |
| Chat send | No visual feedback | Typing indicator |
| App build | Shows status but no progress | Progress bar |
| Login | Basic loading | Better error messages |

**API endpoints to update:**
- `POST /api/tasks` - Add loading state
- `POST /api/chat` - Add typing indicator trigger
- `POST /api/apps` - Add build progress updates
- All endpoints - Use unified error format

## Validation Architecture

### Backend Tests

- `test_error_code_classification()` - Verify error categorization
- `test_error_response_format()` - Verify JSON structure
- `test_rate_limit_error_exposed()` - Verify 429 returns proper code

### Frontend Tests

- `test_loading_indicator_shows()` - Spinner appears on API call
- `test_error_toast_displayed()` - Error shows toast notification
- `test_timeout_warning_shown()` - Warning at 25s

### E2E Tests

- Create task with slow network → loading state visible
- Trigger rate limit → user-friendly message shown
- Disconnect WebSocket → reconnection indicator appears

## Implementation Checklist

- [ ] Create `core/error_codes.py` with taxonomy
- [ ] Add FastAPI exception handler for unified responses
- [ ] Update all API endpoints to use error codes
- [ ] Create CSS spinner/loading components
- [ ] Add loading indicator JavaScript module
- [ ] Add timeout manager with warnings
- [ ] Implement toast notification system
- [ ] Add error display to all async operations
- [ ] Write error handling tests

## References

- FastAPI exception handlers: https://fastapi.tiangolo.com/tutorial/handling-errors/
- CSS spinners: https://loading.io/css/
- Toast notification patterns: https://web.dev/building-a-toast-component/
