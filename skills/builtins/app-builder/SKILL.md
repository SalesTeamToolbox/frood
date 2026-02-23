---
name: app-builder
description: Build complete, working web applications from user descriptions.
always: false
task_types: [app_create, app_update]
---

# App Builder

You are building a complete, working web application that the user can access immediately. Your goal is not just to write code — it is to deliver a **running, usable app** the user can open in their browser.

## Workflow

### Phase 1: Plan

1. **Understand the request.** What does the user want? What are the core features?
2. **Determine the app mode:**
   - `internal` — A system tool that extends Agent42 (monitoring dashboard, trading bot, analytics panel). Lives inside Agent42, no separate auth needed. Agent42 can operate it via `app_api`.
   - `external` — An app being developed for public release. Will eventually be deployed independently. May need its own auth, designed for end users.
3. **Choose the runtime.** Pick the simplest runtime that meets the requirements:
   - `static` — Pure HTML/CSS/JS. Best for: calculators, timers, dashboards, trackers, games, forms, single-page tools. No backend needed.
   - `python` — Flask or FastAPI + SQLite. Best for: CRUD apps, apps with user accounts, apps needing a database, multi-page apps with server logic.
   - `node` — Express + SQLite. Best for: REST APIs, real-time apps (WebSocket), apps where the user specifically wants Node.
   - `docker` — Only for multi-service apps (e.g., app + database + cache). Rarely needed.
4. **Plan the structure.** Decide on pages, data model, and features. Keep it focused — build the core well rather than spreading thin.

### Phase 2: Create

1. **Create the app** using the `app` tool:
   ```
   app create --name "App Name" --runtime python --app_description "What it does" --tags "tag1,tag2" --git_enabled true --app_mode internal
   ```
   Set `--app_mode internal` for Agent42 system apps, or `--app_mode external` for apps being developed for public release.
2. Note the **app ID** and **path** from the response. All files go into that path.

### Phase 3: Build

Write the complete application code using filesystem tools (`write_file`, `edit_file`).

**Critical rules:**
- Write ALL files needed for the app to work. Do not leave placeholders.
- The app must start and serve on the PORT and HOST environment variables.
- Use modern, clean styling (Tailwind CSS via CDN is recommended).
- Include basic error handling.
- For Python apps: the entry point must call `app.run(host=host, port=int(port))`.
- For Node apps: `package.json` must have a `start` script.

### Phase 4: Test & Verify

1. If the runtime supports it, install dependencies:
   ```
   app install_deps --app_id <id>
   ```
2. Review your code for obvious errors before launching.

### Phase 5: Launch

1. Mark the app as ready (auto-commits if git is enabled):
   ```
   app mark_ready --app_id <id> --version "1.0.0"
   ```
2. Start the app:
   ```
   app start --app_id <id>
   ```
3. Report the URL to the user.

### Phase 6 (Optional): GitHub Integration

If the user wants the app on GitHub, or if sharing/collaboration is needed:

1. **Set up the GitHub repo:**
   ```
   app github_setup --app_id <id> --repo_name "my-app" --private true --push_on_build true
   ```
   This creates the repo, pushes initial code, and optionally auto-pushes on future builds.

2. **Manual push at any time:**
   ```
   app github_push --app_id <id>
   ```

3. **Other git operations:**
   ```
   app git_commit --app_id <id> --message "Add new feature"
   app git_status --app_id <id>
   app git_log --app_id <id>
   ```

---

## Runtime Templates

### Static App (HTML/CSS/JS)

Write to the `public/` directory. Entry point: `public/index.html`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>App Name</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 min-h-screen">
    <div id="app" class="max-w-4xl mx-auto p-6">
        <!-- App content here -->
    </div>
    <script src="js/app.js"></script>
</body>
</html>
```

Use `localStorage` for data persistence. Use vanilla JS or Alpine.js for interactivity.

### Python App (Flask + SQLite)

Write to `src/`. Entry point: `src/app.py`. Dependencies: `requirements.txt`.

```python
import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3

app = Flask(__name__, template_folder="templates", static_folder="static")
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "app.db")

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    # Create tables here
    db.close()

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    init_db()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    app.run(host=host, port=port, debug=False)
```

**requirements.txt:**
```
flask>=3.0
```

Templates go in `src/templates/`, static files in `src/static/`.

### Python App (FastAPI + HTMX)

For more modern interactive apps:

```python
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host=host, port=port)
```

**requirements.txt:**
```
fastapi>=0.110
uvicorn>=0.29
jinja2>=3.1
python-multipart>=0.0.9
```

Include `<script src="https://unpkg.com/htmx.org@1.9.10"></script>` in templates for interactivity without writing JavaScript.

---

## Design Guidelines

1. **Look professional.** Use Tailwind CSS. Include proper spacing, colors, and typography.
2. **Be responsive.** Apps should work on mobile and desktop.
3. **Include navigation.** Multi-page apps need a nav bar or sidebar.
4. **Show feedback.** Loading states, success/error messages, empty states.
5. **Use good defaults.** Pre-fill forms, set sensible defaults, include sample data where helpful.
6. **Keep it fast.** Minimize dependencies. SQLite over PostgreSQL. CDN over npm.

## Data Persistence

- **Static apps:** Use `localStorage` or `IndexedDB`.
- **Python/Node apps:** Use SQLite. Create tables in an `init_db()` function called at startup.
- **Docker apps:** Use named volumes for database files.

## What NOT to Do

- Do not leave TODO comments or placeholder functions.
- Do not use external APIs that require keys (unless the user specifies).
- Do not over-engineer. A workout tracker does not need microservices.
- Do not forget the PORT/HOST environment variables.
- Do not use `app.run(debug=True)` in the final code.
- Do not write a README instead of actual code. Build the app.

## App Updates (APP_UPDATE tasks)

When updating an existing app:
1. Read the existing app files to understand the current state.
2. Make targeted changes — do not rewrite the entire app.
3. Preserve existing data structures and functionality.
4. Bump the version number.
5. If git is enabled, commit the changes:
   ```
   app git_commit --app_id <id> --message "Description of changes"
   ```
6. Mark ready (triggers auto-push if GitHub is configured):
   ```
   app mark_ready --app_id <id> --version "1.1.0"
   ```
7. Restart the app after changes.

---

## Designing Internal Apps for Agent Interaction

Internal apps are not just dashboards for humans — they can be **operated by Agent42 autonomously**. When building an internal app that Agent42 will interact with, design it as an API-first application.

### API Design Pattern

Every internal app that Agent42 will operate should expose a JSON API alongside its UI:

```python
# Example: Crypto trading app with agent-operable API

@app.route("/api/portfolio")
def get_portfolio():
    """Agent42 calls this to check current holdings."""
    holdings = get_all_holdings()
    return jsonify({"holdings": holdings, "total_value_usd": sum(h["value"] for h in holdings)})

@app.route("/api/trade", methods=["POST"])
def execute_trade():
    """Agent42 calls this to execute a trade."""
    data = request.get_json()
    result = process_trade(data["action"], data["symbol"], data["amount"])
    return jsonify(result)

@app.route("/api/signals")
def get_signals():
    """Agent42 calls this to read current trading signals."""
    return jsonify({"signals": compute_signals()})
```

### How Agent42 Interacts with Apps

Agent42 uses the `app_api` action to call a running app's HTTP endpoints directly:

```
app app_api --app_id <id> --method GET --endpoint "/api/portfolio"
app app_api --app_id <id> --method POST --endpoint "/api/trade" --body '{"action": "buy", "symbol": "BTC", "amount": 0.1}'
```

This bypasses the dashboard proxy — it calls the app on localhost directly, so no authentication is needed for internal apps.

### Best Practices for Agent-Operable Apps

1. **Return JSON from all API endpoints.** Agent42 parses JSON responses to understand results.
2. **Use clear, descriptive endpoint names.** `/api/portfolio`, `/api/trade`, `/api/signals` — not `/api/do`.
3. **Include status and error messages in responses.** Return `{"success": true, "message": "..."}` or `{"error": "..."}`.
4. **Keep endpoints idempotent where possible.** GET requests should never change state.
5. **Validate inputs server-side.** Even though Agent42 is the caller, protect against malformed requests.
6. **Return pagination for large datasets.** Use `?page=1&per_page=50` to avoid oversized responses.
7. **Include a health/status endpoint.** `GET /api/status` lets Agent42 check if the app is responsive.

### Access Control Settings

Use these commands to manage app access:

```
app set_mode --app_id <id> --app_mode internal      # System tool (Agent42 operated)
app set_mode --app_id <id> --app_mode external       # For public release
app set_visibility --app_id <id> --visibility private  # Dashboard-only access
app set_visibility --app_id <id> --visibility unlisted # Anyone with URL can access
app set_visibility --app_id <id> --visibility public   # Listed publicly
app set_auth --app_id <id> --require_auth true        # Require dashboard login
app set_auth --app_id <id> --require_auth false       # Open access (default for internal)
```

### Multi-Agent App Operation

Multiple agents can interact with the same running app concurrently. When building apps that multiple agents may access:

- Use database transactions or locks for write operations
- Return timestamps in responses so agents can track data freshness
- Design for concurrent access — avoid in-memory-only state for important data
