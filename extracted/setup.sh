#!/usr/bin/env bash
# setup.sh — MultiClaw VPS setup script
# Run once after cloning: bash setup.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

info "🦞 MultiClaw Setup"
echo ""

# ── Check Python 3.11+ ──────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    error "Python 3 not found. Install Python 3.11+."
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python version: $PY_VERSION"

# ── Check Node.js ───────────────────────────────────────────────────────────
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

# ── Check git ───────────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    error "git not found. Install git."
fi
info "git version: $(git --version)"

# ── Python venv ─────────────────────────────────────────────────────────────
info "Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

info "Installing Python dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
info "✅ Python dependencies installed"

# ── .env setup ──────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn "Created .env from .env.example"
    warn "⚠️  EDIT .env BEFORE RUNNING: set your API keys and change the password!"
else
    info ".env already exists — skipping"
fi

# ── React frontend ──────────────────────────────────────────────────────────
info "Installing frontend dependencies..."
cd dashboard/frontend
npm install --silent
info "Building React frontend..."
npm run build
cd ../..
info "✅ Frontend built"

# ── Systemd service (optional) ──────────────────────────────────────────────
WORKING_DIR=$(pwd)
VENV_PYTHON="$WORKING_DIR/.venv/bin/python"
CURRENT_USER=$(whoami)

cat > /tmp/multiclaw.service << EOF
[Unit]
Description=MultiClaw Multi-Agent Orchestrator
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${WORKING_DIR}
ExecStart=${VENV_PYTHON} multiclaw.py
Restart=on-failure
RestartSec=5
StandardOutput=append:${WORKING_DIR}/multiclaw.log
StandardError=append:${WORKING_DIR}/multiclaw.log
EnvironmentFile=${WORKING_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

info "Systemd service file created at /tmp/multiclaw.service"
info "To install as a service (requires sudo):"
echo "  sudo cp /tmp/multiclaw.service /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable multiclaw"
echo "  sudo systemctl start multiclaw"

echo ""
info "✅ Setup complete!"
echo ""
echo "  1. Edit .env and set your API keys"
echo "  2. Set DEFAULT_REPO_PATH to your git project"
echo "  3. Run: source .venv/bin/activate && python multiclaw.py"
echo "  4. Open: http://localhost:8000"
echo ""
warn "Remember: your git repo must have a 'dev' branch before starting!"
info "  git checkout -b dev  (if you don't have one)"
