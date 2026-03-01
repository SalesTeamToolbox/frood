---
name: qa-team
description: Multi-agent QA team for comprehensive application testing with tester, developer, and reviewer roles.
always: false
task_types: [app_create, app_update]
---

# QA Team

When an application needs thorough testing beyond a single agent's pass, use the team tool to orchestrate a multi-agent QA workflow. This is most useful for complex apps with multiple pages, APIs, and user flows.

## When to Use QA Team

- App has 3+ pages or routes
- App has a backend API with multiple endpoints
- App handles user input (forms, uploads, authentication)
- App was built by a different agent and needs independent verification
- User explicitly requests thorough testing

## Team Workflow

Use the `team` tool with `fan_out_fan_in` workflow:

```
team fan_out_fan_in --objective "QA test the application <app_name> (app_id: <id>, port: <port>)" --roles [
  {
    "name": "QA Tester",
    "task": "Run comprehensive QA testing on the app at http://localhost:<port>. Steps: 1) app_test smoke_test --app_id <id>, 2) Test all major user flows with app_test test_flow, 3) app_test check_logs --app_id <id>, 4) Visual check each page with app_test visual_check, 5) Test API endpoints if applicable. Document all findings."
  },
  {
    "name": "Developer",
    "task": "Review the QA Tester's findings. For each bug or issue: 1) Read the relevant source code, 2) Identify the root cause, 3) Fix the code, 4) Restart the app: app restart --app_id <id>, 5) Verify the fix with app_test health_check. Document all changes made."
  },
  {
    "name": "Reviewer",
    "task": "Final verification after Developer fixes. 1) Run app_test smoke_test --app_id <id> to confirm fixes, 2) Visual check the main pages for professional quality, 3) Check logs are clean, 4) app_test generate_report for the final QA summary. Rate the app's readiness for deployment on a scale of 1-5."
  }
]
```

## Role Responsibilities

### QA Tester
- Runs the full testing suite (smoke, flows, logs, visual)
- Documents bugs with severity levels
- Tests edge cases (empty inputs, long strings, special characters)
- Verifies mobile responsiveness if applicable

### Developer
- Receives QA findings and triages by severity
- Fixes critical and error-level issues
- Documents each fix and its rationale
- Restarts the app after changes

### Reviewer
- Performs final verification after fixes
- Runs a clean smoke test
- Generates the final QA report
- Provides a deployment readiness score

## Output

The team produces a final QA report with:
- Overall pass/fail status
- List of issues found and their resolution
- Remaining known issues (if any)
- Deployment readiness score (1-5)
- Improvement suggestions for future iterations
