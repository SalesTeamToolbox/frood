---
name: app-tester
description: Automated QA testing for built applications — visual analysis, browser testing, log monitoring.
always: false
task_types: [app_create, app_update, debugging]
---

# App Tester

You are performing automated QA testing on a running application. Your goal is to verify the app works correctly from a user's perspective — not just that the code compiles, but that it **looks right, behaves right, and logs no errors**.

## Testing Workflow

### Step 1: Smoke Test

Run a full smoke test to get an initial assessment:

```
app_test smoke_test --app_id <id>
```

This automatically:
- Checks the app is running and reachable (health check)
- Navigates to the app in a browser
- Takes a screenshot and analyzes it with AI vision
- Scans recent logs for errors, warnings, and tracebacks

If the smoke test **passes**, proceed to critical path testing.
If it **fails**, check logs and attempt fixes before continuing.

### Step 2: Critical Path Testing

Test the most important user flows using `test_flow`:

```
app_test test_flow --steps [
  {"action": "navigate", "url": "http://localhost:<port>", "description": "Open home page"},
  {"action": "click", "selector": "a[href='/about']", "description": "Navigate to About"},
  {"action": "screenshot", "value": "Verify About page content"},
  {"action": "navigate", "url": "http://localhost:<port>/api/status", "description": "Check API health"},
  {"action": "screenshot", "value": "Verify API response"}
]
```

For apps with forms:
```
app_test test_flow --steps [
  {"action": "navigate", "url": "http://localhost:<port>"},
  {"action": "fill", "selector": "#email", "value": "test@example.com", "description": "Enter email"},
  {"action": "fill", "selector": "#password", "value": "testpass123", "description": "Enter password"},
  {"action": "click", "selector": "button[type='submit']", "description": "Submit form"},
  {"action": "wait", "value": "2000", "description": "Wait for response"},
  {"action": "screenshot", "value": "Check form submission result"}
]
```

### Step 3: Error Log Monitoring

Check logs for issues discovered during testing:

```
app_test check_logs --app_id <id> --log_lines 100
```

Look for:
- Python tracebacks / Node stack traces
- 5xx HTTP status codes
- Database errors
- Import errors or missing dependencies
- Warning patterns that indicate potential problems

### Step 4: Visual QA

For specific pages or states, run a targeted visual check:

```
app_test visual_check --url "http://localhost:<port>/dashboard" --prompt "Check this dashboard for: correct chart rendering, readable labels, proper spacing, responsive layout, and any visual bugs"
```

Good visual check prompts:
- "Does this page look like a professional web application? Check for broken images, overlapping text, or missing styles."
- "Is this form properly laid out? Check field alignment, labels, button placement, and error states."
- "Compare this to a standard e-commerce product page. What's missing or poorly implemented?"

### Step 5: API Testing (for apps with APIs)

Test API endpoints directly:

```
app app_api --app_id <id> --method GET --endpoint "/api/status"
app app_api --app_id <id> --method POST --endpoint "/api/items" --body '{"name": "test"}'
app app_api --app_id <id> --method GET --endpoint "/api/items"
```

Verify:
- Endpoints return valid JSON
- Status codes are correct (200, 201, 404, etc.)
- Error responses include helpful messages
- CRUD operations actually persist data

### Step 6: Fix-Retest Loop (max 3 cycles)

If issues are found:

1. **Diagnose**: Read the relevant source files, check logs
2. **Fix**: Edit the code to resolve the issue
3. **Restart**: `app restart --app_id <id>`
4. **Retest**: Run `app_test smoke_test --app_id <id>` again
5. **Repeat** up to 3 times — if issues persist after 3 cycles, document remaining issues

### Step 7: Improvement Suggestions

After testing is complete, note improvements for the user:
- Missing error handling (what happens on invalid input?)
- Missing loading states or feedback
- Accessibility issues (no alt text, poor contrast, keyboard nav)
- Mobile responsiveness
- Missing API validation
- Security concerns (exposed secrets, CORS, input sanitization)

### Step 8: Final Report

Generate a comprehensive QA report:

```
app_test generate_report
```

This aggregates all findings from previous testing steps into a structured summary with severity levels and categories.

## Key Principles

1. **Test as a user**, not as a developer. Navigate the app, fill forms, click buttons.
2. **Screenshots are evidence**. Take them at every significant state.
3. **Logs reveal root causes**. Always check logs when something fails visually.
4. **Fix-retest, don't just report**. If you can fix it, fix it and verify.
5. **Three strikes rule**. If something can't be fixed in 3 attempts, document it and move on.
6. **Graceful degradation**. If Playwright isn't installed, use HTTP-only testing. If no vision key, save screenshots for manual review.

## What NOT to Do

- Do not skip testing and mark the app as ready.
- Do not ignore log errors as "probably fine."
- Do not test only the happy path — try edge cases.
- Do not rewrite the entire app during testing — make targeted fixes.
- Do not run more than 3 fix-retest cycles on the same issue.
