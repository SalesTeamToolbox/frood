# Installation

Install Frood from source and run the dashboard locally.

## 1. Clone the repo

```bash
git clone https://github.com/SalesTeamToolbox/frood.git
cd frood
```

## 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows (PowerShell):

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

## 3. Install development dependencies

```bash
make install-dev
```

This installs `requirements.txt` plus `requirements-dev.txt` (pytest, ruff) and sets up the pre-commit hook.

## 4. Configure

Copy the example environment file and fill in the values you need:

```bash
cp .env.example .env
```

API keys are optional — Frood degrades gracefully without them. Never commit real keys; only `.env.example` is public.

## 5. Run

```bash
make run
```

Dashboard at http://localhost:8000. For headless (no dashboard):

```bash
make run-headless
```

## Verify

```bash
make lint
make test
```
