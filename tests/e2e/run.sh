#!/usr/bin/env bash
# Agent42 E2E Test Runner
#
# Usage:
#   ./tests/e2e/run.sh                    # run all suites
#   ./tests/e2e/run.sh --suite ui         # run one suite
#   ./tests/e2e/run.sh --discover         # show codebase manifest
#   ./tests/e2e/run.sh --coverage         # show coverage gaps
#   ./tests/e2e/run.sh --headed           # run with visible browser
#   ./tests/e2e/run.sh --url http://x:80  # custom base URL
#
# Prerequisites:
#   - Agent42 server running (python agent42.py)
#   - playwright-cli installed globally (npm install -g @playwright/cli@latest)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

# Load .env if present
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

python -m tests.e2e "$@"
