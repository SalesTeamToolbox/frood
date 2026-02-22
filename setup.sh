#!/usr/bin/env bash
# setup.sh — Agent42 setup script
# Run once after cloning: bash setup.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

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

# ── Optional memory backends ────────────────────────────────────────────
echo ""
info "Optional: enhanced memory backends (Qdrant + Redis)"
echo "  These are NOT required — Agent42 works without them."
echo "  Install for faster semantic search and session caching:"
echo ""
echo "    pip install qdrant-client    # Vector DB for semantic search"
echo "    pip install redis[hiredis]   # Session cache + embedding cache"
echo ""
echo "  See .env.example for QDRANT_* and REDIS_* configuration."
echo ""

# ── .env setup ───────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn "Created .env from .env.example"
    warn "EDIT .env BEFORE RUNNING — set your API keys and change the password!"
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
    warn "No frontend found at dashboard/frontend — skipping frontend build"
fi

# ── Systemd service (optional) ───────────────────────────────────────────────
WORKING_DIR=$(pwd)
VENV_PYTHON="$WORKING_DIR/.venv/bin/python"
CURRENT_USER=$(whoami)

cat > /tmp/agent42.service << EOF
[Unit]
Description=Agent42 Multi-Agent Orchestrator
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${WORKING_DIR}
ExecStart=${VENV_PYTHON} agent42.py
Restart=on-failure
RestartSec=5
StandardOutput=append:${WORKING_DIR}/agent42.log
StandardError=append:${WORKING_DIR}/agent42.log
EnvironmentFile=${WORKING_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

info "Systemd service file created at /tmp/agent42.service"

echo ""
info "Setup complete!"
echo ""
echo "  1. Edit .env and set your API keys"
echo "  2. Set DEFAULT_REPO_PATH to your git project"
echo "  3. Run: source .venv/bin/activate && python agent42.py"
echo "  4. Open: http://localhost:8000"
echo ""
echo "  Optional — enhanced memory (Qdrant + Redis):"
echo "    pip install qdrant-client redis[hiredis]"
echo "    docker run -d -p 6333:6333 qdrant/qdrant"
echo "    docker run -d -p 6379:6379 redis:alpine"
echo "    # Then set QDRANT_URL and REDIS_URL in .env"
echo ""
echo "  Optional — install as a systemd service:"
echo "    sudo cp /tmp/agent42.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable agent42"
echo "    sudo systemctl start agent42"
echo ""
warn "Your git repo must have a 'dev' branch before starting!"
info "  git checkout -b dev  (if you don't have one)"
