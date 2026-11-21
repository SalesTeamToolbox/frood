---
layout: default
title: Installation
permalink: /docs/installation/
---

# Installation — Frood

Install Frood from zero on a clean machine or container. These steps take you from a fresh clone to a running dashboard at `http://localhost:8000`.

## Prerequisites

- Python 3.11+
- `git`
- `docker` (optional, for the container install)

## 1. Clone the repo

```bash
git clone https://github.com/SalesTeamToolbox/frood.git
cd frood
```

## 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

## 3. Install dependencies

Production dependencies:

```bash
make install
```

Development dependencies (linting, testing, security):

```bash
make install-dev
```

## 4. Configure

```bash
cp .env.example .env
```

Open `.env` and replace the placeholder values with your own. At minimum set `JWT_SECRET` (for persistent dashboard sessions). All provider API keys are optional — Frood degrades gracefully when a key is missing.

Never commit real API keys, passwords, or tokens to the repository.

## 5. Verify (lint + test)

```bash
make lint
make test
make check
```

Note: the base tree may carry a small number of pre-existing ruff findings (documented in `ops/install-from-zero.md`). These are not introduced by these docs, and ruff does not lint markdown files.

## 6. Run

```bash
python frood.py                  # Dashboard at http://localhost:8000
python frood.py --no-dashboard   # Headless (services only)
python frood.py --port 8080      # Custom dashboard port
```

Open http://localhost:8000 in your browser. First run opens a setup wizard to set a dashboard password and (optionally) an OpenRouter API key.

## Optional: build and run the container

```bash
docker build -t frood .
docker run -p 8000:8000 frood
```

Then open http://localhost:8000.

## Next steps

- `docs/frood-st/docs/usage.md` — dashboard, router, memory, peer-mail basics
- `docs/frood-st/docs/api-reference.md` — HTTP API endpoints and MCP tools overview
- `ops/install-from-zero.md` — full install-from-zero procedure (incl. docker build)
