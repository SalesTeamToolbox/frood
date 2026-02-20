# Agent42

**The answer to life, the universe, and all your tasks.**

A multi-agent orchestrator platform. Free models handle the iterative work;
Claude Code (or human review) gates the final output before anything ships.

Not just for coding — Agent42 handles marketing, email, research, documentation,
and any task you throw at it.

## Architecture

```
Free Model (NVIDIA/Groq)  ->  Iteration Loop  ->  Critic Pass  ->  REVIEW.md  ->  You + Claude Code  ->  Ship
```

- **Primary models**: Qwen2.5-Coder-32B (coding), DeepSeek-R1 (debugging), Llama-3.1-405B (research)
- **Critic models**: Independent second-opinion pass using the best model for each task type
- **Review gate**: Human + Claude Code final review before any code touches your server
- **Zero API cost**: All agent work runs on free NVIDIA and Groq tiers

## Quick Start

```bash
git clone <this-repo> agent42
cd agent42
bash setup.sh
# Edit .env — set NVIDIA_API_KEY, GROQ_API_KEY, DASHBOARD_PASSWORD
source .venv/bin/activate
python agent42.py --repo /path/to/your/project
```

Open `http://localhost:8000` in your browser.

## Requirements

- Python 3.11+
- Node.js 18+ (for frontend build)
- git with a repo that has a `dev` branch
- [NVIDIA build account](https://build.nvidia.com) (free)
- [Groq account](https://console.groq.com) (free)

## Configuration

All config lives in `.env`. See `.env.example` for all options.

| Variable | Default | Description |
|---|---|---|
| `NVIDIA_API_KEY` | — | NVIDIA build API key |
| `GROQ_API_KEY` | — | Groq API key |
| `MAX_CONCURRENT_AGENTS` | `3` | Max parallel agents (2-3 for 6GB VPS) |
| `DEFAULT_REPO_PATH` | `.` | Git repo for worktrees |
| `DASHBOARD_USERNAME` | `admin` | Dashboard login |
| `DASHBOARD_PASSWORD` | `changeme` | Dashboard password |

## Usage

### Via Dashboard
Open `http://localhost:8000`, log in, fill out the task form.

### Via tasks.json
Drop tasks into `tasks.json` (see `tasks.json.example`). The orchestrator polls
for changes every 30 seconds, or restart to load immediately.

### Via CLI
```bash
python agent42.py --repo /path/to/project --port 8000 --max-agents 2
```

## Model Routing

| Task Type | Primary | Critic | Max Iterations |
|---|---|---|---|
| coding | Qwen2.5-Coder-32B | DeepSeek-R1 | 8 |
| debugging | DeepSeek-R1 | Qwen2.5-Coder-32B | 10 |
| research | Llama-3.1-405B | Mistral-Large | 5 |
| refactoring | Qwen2.5-Coder-32B | DeepSeek-R1 | 8 |
| documentation | Llama-3.3-70B | Mixtral-8x7B | 4 |
| marketing | Llama-3.1-405B | Mixtral-8x7B | 6 |
| email | Mistral-Large | None | 3 |

## Review Gate

When a task completes, the dashboard shows a **READY** badge.
The agent commits a `REVIEW.md` to the worktree containing:
- Full iteration history
- Lint/test results from every cycle
- Independent critic notes
- Complete `git diff dev` embedded
- A pre-written Claude Code review prompt

```bash
cd /tmp/agent42/<task-id>
claude  # Opens Claude Code with full context in REVIEW.md
```

## Approval Gates

These operations pause the agent and show an approval modal in the dashboard:
- `gmail_send` — sending email
- `git_push` — pushing code
- `file_delete` — deleting files
- `external_api` — calling external services

## Project Structure

```
agent42/
├── agent42.py                 # Main entry point
├── core/
│   ├── config.py              # Centralized settings from .env
│   ├── task_queue.py          # Task state machine + JSON persistence
│   ├── worktree_manager.py    # Git worktree lifecycle
│   └── approval_gate.py       # Protected operation intercept
├── agents/
│   ├── agent.py               # Per-task agent orchestration
│   ├── model_router.py        # Task-type -> model mapping
│   └── iteration_engine.py    # Primary -> Critic -> Revise loop
├── dashboard/
│   ├── server.py              # FastAPI + WebSocket server
│   ├── auth.py                # JWT authentication
│   ├── websocket_manager.py   # Real-time broadcast
│   └── frontend/              # React dashboard (Vite)
├── .env.example
├── requirements.txt
├── tasks.json.example
└── setup.sh
```

## Running as a Service

```bash
sudo cp /tmp/agent42.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable agent42
sudo systemctl start agent42
sudo journalctl -u agent42 -f
```

## Security Notes

- Change `DASHBOARD_PASSWORD` before exposing to the internet
- Use `DASHBOARD_PASSWORD_HASH` (bcrypt) instead of plaintext for production
- Put nginx in front with HTTPS before making public
- `JWT_SECRET` should be a 64-char random string
- Approval gates protect sensitive operations (email, push, delete)
