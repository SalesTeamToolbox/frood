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
info "Enhanced Memory (optional)"
echo "  Agent42 works fully without these. Add them for semantic search + session caching."
echo ""
echo "  1) Skip (default — file-based memory)"
echo "  2) Qdrant Embedded (no Docker needed, stores vectors locally)"
echo "  3) Qdrant + Redis (Docker required, full power)"
echo ""
read -rp "  Choose [1/2/3]: " memory_choice
memory_choice=${memory_choice:-1}

case "$memory_choice" in
  2)
    info "Installing qdrant-client..."
    pip install --quiet qdrant-client
    info "Qdrant client installed. Embedded mode will be enabled in .env."
    _SETUP_MEMORY="qdrant_embedded"
    ;;
  3)
    info "Installing qdrant-client and redis..."
    pip install --quiet qdrant-client "redis[hiredis]"
    info "Client libraries installed."
    warn "You need to start Docker services before running Agent42:"
    echo "    docker run -d --name qdrant -p 6333:6333 qdrant/qdrant"
    echo "    docker run -d --name redis -p 6379:6379 redis:alpine"
    _SETUP_MEMORY="qdrant_redis"
    ;;
  *)
    info "Skipping enhanced memory — you can add it later."
    _SETUP_MEMORY="skip"
    ;;
esac
echo ""

# ── .env setup ───────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn "Created .env from .env.example"
    warn "EDIT .env BEFORE RUNNING — set your API keys and change the password!"
else
    info ".env already exists — skipping"
fi

# Apply memory backend selection to .env
if [ "$_SETUP_MEMORY" = "qdrant_embedded" ]; then
    sed -i 's/^#\?\s*QDRANT_ENABLED=.*/QDRANT_ENABLED=true/' .env
    sed -i 's/^#\?\s*QDRANT_LOCAL_PATH=.*/QDRANT_LOCAL_PATH=.agent42\/qdrant/' .env
    # Add if not present
    grep -q "^QDRANT_ENABLED=" .env || echo "QDRANT_ENABLED=true" >> .env
    info "Qdrant embedded mode enabled in .env"
elif [ "$_SETUP_MEMORY" = "qdrant_redis" ]; then
    sed -i 's/^#\?\s*QDRANT_URL=.*/QDRANT_URL=http:\/\/localhost:6333/' .env
    sed -i 's/^#\?\s*QDRANT_ENABLED=.*/QDRANT_ENABLED=true/' .env
    sed -i 's/^#\?\s*REDIS_URL=.*/REDIS_URL=redis:\/\/localhost:6379\/0/' .env
    grep -q "^QDRANT_URL=" .env || echo "QDRANT_URL=http://localhost:6333" >> .env
    grep -q "^QDRANT_ENABLED=" .env || echo "QDRANT_ENABLED=true" >> .env
    grep -q "^REDIS_URL=" .env || echo "REDIS_URL=redis://localhost:6379/0" >> .env
    info "Qdrant + Redis configured in .env"
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
if [ "$_SETUP_MEMORY" = "qdrant_redis" ]; then
    warn "Remember to start Docker services before running Agent42:"
    echo "    docker run -d --name qdrant -p 6333:6333 qdrant/qdrant"
    echo "    docker run -d --name redis -p 6379:6379 redis:alpine"
    echo ""
fi
echo "  Optional — install as a systemd service:"
echo "    sudo cp /tmp/agent42.service /etc/systemd/system/"
echo "    sudo systemctl daemon-reload"
echo "    sudo systemctl enable agent42"
echo "    sudo systemctl start agent42"
echo ""
warn "Your git repo needs a 'dev' branch for coding/debugging/refactoring tasks."
info "  git checkout -b dev  (if you don't have one)"
info "  Non-code tasks (marketing, content, design, etc.) work without it."
