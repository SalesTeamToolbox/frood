#!/usr/bin/env bash
# setup.sh — Agent42 setup script
# Run once after cloning: bash setup.sh
# Use --quiet when called from install-server.sh (suppresses banners/prompts)

set -e

QUIET=false
[ "$1" = "--quiet" ] && QUIET=true

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

if ! $QUIET; then
    echo ""
    echo "  ___                    _   _ _ ____  "
    echo " / _ \  __ _  ___ _ __ | |_| | |___ \ "
    echo "| |_| |/ _\` |/ _ \ '_ \| __| | | __) |"
    echo "| | | | (_| |  __/ | | | |_|_| |/ __/ "
    echo "|_| |_|\__, |\___|_| |_|\__(_)_|_____|"
    echo "       |___/                           "
    echo ""
    info "The answer to all your tasks."
    echo ""
fi

# ── Check Python 3.11+ ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    error "Python 3 not found. Install Python 3.11+."
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    error "Python 3.11+ required. Found: $PY_VERSION"
fi

info "Python version: $PY_VERSION"

# ── Check Node.js ────────────────────────────────────────────────────────────
if ! command -v node &>/dev/null; then
    warn "Node.js not found. Installing via nvm..."
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    nvm install 20
    nvm use 20
else
    info "Node.js version: $(node --version)"
fi

# ── Check git ────────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    error "git not found. Install git."
fi
info "git version: $(git --version)"

# ── Python venv ──────────────────────────────────────────────────────────────
info "Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

info "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
info "Python dependencies installed"

# ── .env setup ───────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    info "Created .env from .env.example"
else
    info ".env already exists — skipping"
fi

# ── React frontend ───────────────────────────────────────────────────────────
if [ -d "dashboard/frontend" ] && [ -f "dashboard/frontend/package.json" ]; then
    info "Installing frontend dependencies..."
    cd dashboard/frontend
    npm install --silent
    info "Building React frontend..."
    npm run build
    cd ../..
    info "Frontend built"
else
    $QUIET || warn "No frontend found at dashboard/frontend — skipping frontend build"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
if ! $QUIET; then
    echo ""
    info "Setup complete!"
    echo ""
    echo "  1. Start Agent42:  source .venv/bin/activate && python agent42.py"
    echo "  2. Open http://localhost:8000 to complete setup in your browser"
    echo ""
    warn "Your git repo needs a 'dev' branch for coding/debugging/refactoring tasks."
    info "  git checkout -b dev  (if you don't have one)"
    info "  Non-code tasks (marketing, content, design, etc.) work without it."
    echo ""
fi
