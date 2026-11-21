# Install from Zero — Frood

Install Frood from zero on a clean machine or container, and verify it is running locally.

This procedure is the reference install for the public release. It is safe to follow on a fresh checkout; it touches only dependency installation and local configuration, never existing source code.

## Prerequisites

- Python 3.11+
- `git`
- `docker` (optional, for the container install)

## Procedure

### 1. Clone the repo

```bash
git clone https://github.com/SalesTeamToolbox/frood.git
cd frood
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

Production dependencies:

```bash
make install
```

Development dependencies (linting, testing, security):

```bash
make install-dev
```

### 4. Configure

```bash
cp .env.example .env
```

Open `.env` and replace placeholder values with your own. At minimum set `JWT_SECRET` (for persistent dashboard sessions). All provider API keys are optional — Frood degrades gracefully when a key is missing.

Never commit real API keys, passwords, or tokens.

### 5. Verify (lint + test)

```bash
make lint
make test
make check
```

### 6. Run

```bash
python frood.py                  # Dashboard at http://localhost:8000
```

Open http://localhost:8000 in your browser. First run opens a setup wizard to set a dashboard password and (optionally) an OpenRouter API key.

Headless (services only):

```bash
python frood.py --no-dashboard
```

### 7. Optional: build and run the container

```bash
docker build -t frood .
docker run -p 8000:8000 frood
```

Then open http://localhost:8000.

## Notes

- `make lint` may report pre-existing ruff findings in the base tree (see M8 release-gates report). These are pre-existing and are not introduced by this procedure; ruff does not lint markdown or `.md` docs.
- `make test` runs the full pytest suite.
- `make check` runs lint + tests together.
- Frood has no public deploy target — deploy truth is a stated gap (see M8 release-gates report).
- `ops/progress.sh` prints a one-line ANSI progress bar for a repo's verify/train state (usage: `ops/progress.sh <repo>`).
