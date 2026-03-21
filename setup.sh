#!/usr/bin/env bash
# setup.sh — Agent42 setup script
# Run once after cloning: bash setup.sh
# Use --quiet when called from install-server.sh (suppresses banners/prompts)
#
# Subcommands:
#   bash setup.sh              Full local setup (default)
#   bash setup.sh sync-auth    Sync CC credentials to remote VPS
#   bash setup.sh create-shortcut  Create desktop shortcut for Agent42
#   bash setup.sh --quiet      Quiet mode (for install-server.sh)

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ── Subcommand: sync-auth ──────────────────────────────────────────────────
if [ "$1" = "sync-auth" ]; then
    SSH_ALIAS="${2:-agent42-prod}"
    LOCAL_CREDS="$HOME/.claude/.credentials.json"

    if [ ! -f "$LOCAL_CREDS" ]; then
        error "No local CC credentials found at $LOCAL_CREDS. Run 'claude auth login' first."
    fi

    info "Checking remote CC auth status on $SSH_ALIAS..."
    REMOTE_STATUS=$(ssh -o ConnectTimeout=5 "$SSH_ALIAS" "claude auth status 2>&1" 2>/dev/null | grep -o '"loggedIn": *[a-z]*' | head -1 || echo "unknown")

    info "Syncing CC credentials to $SSH_ALIAS..."
    ssh "$SSH_ALIAS" "mkdir -p ~/.claude" 2>/dev/null
    scp -q "$LOCAL_CREDS" "$SSH_ALIAS:~/.claude/.credentials.json"

    # Verify
    NEW_STATUS=$(ssh -o ConnectTimeout=5 "$SSH_ALIAS" "claude auth status 2>&1" 2>/dev/null | grep -o '"loggedIn": *[a-z]*' | head -1 || echo "unknown")
    if echo "$NEW_STATUS" | grep -q "true"; then
        info "CC credentials synced successfully!"
        ssh "$SSH_ALIAS" "claude auth status 2>&1" 2>/dev/null | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(f'  Auth: {d.get(\"authMethod\",\"?\")} | Subscription: {d.get(\"subscriptionType\",\"?\")}')
except: pass
" 2>/dev/null || true
    else
        warn "Credentials copied but auth status unclear. Run 'claude auth status' on VPS to verify."
    fi
    exit 0
fi

# ── Subcommand: create-shortcut ───────────────────────────────────────────────
if [ "$1" = "create-shortcut" ]; then
    OS="$(uname -s)"
    BROWSER_PATH=""
    BROWSER_NAME=""
    BROWSER_CMD=""

    # ── Detect platform and browser ──────────────────────────────────────────
    case "$OS" in
        MINGW*|MSYS*|CYGWIN*)
            # Windows via Git Bash / MSYS2 / Cygwin
            if [ -f "/c/Program Files/Google/Chrome/Application/chrome.exe" ]; then
                BROWSER_PATH="/c/Program Files/Google/Chrome/Application/chrome.exe"
                BROWSER_NAME="Google Chrome"
            elif [ -f "/c/Program Files (x86)/Google/Chrome/Application/chrome.exe" ]; then
                BROWSER_PATH="/c/Program Files (x86)/Google/Chrome/Application/chrome.exe"
                BROWSER_NAME="Google Chrome"
            elif [ -f "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" ]; then
                BROWSER_PATH="/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
                BROWSER_NAME="Microsoft Edge"
            else
                error "No Chromium-based browser found. Install Google Chrome: https://www.google.com/chrome/"
            fi

            info "Using browser: $BROWSER_NAME"
            ICON_PATH="$(cygpath -w "$PROJECT_DIR/dashboard/frontend/dist/assets/icons/icon-512.png" 2>/dev/null || echo "$PROJECT_DIR\\dashboard\\frontend\\dist\\assets\\icons\\icon-512.png")"
            BROWSER_WIN="$(cygpath -w "$BROWSER_PATH" 2>/dev/null || echo "$BROWSER_PATH")"

            powershell.exe -NoProfile -Command "
  \$desktop = [Environment]::GetFolderPath('Desktop');
  \$ws = New-Object -ComObject WScript.Shell;
  \$sc = \$ws.CreateShortcut(\"\$desktop\\Agent42.lnk\");
  \$sc.TargetPath = '$BROWSER_WIN';
  \$sc.Arguments = '--app=http://localhost:8000';
  \$sc.IconLocation = '$ICON_PATH';
  \$sc.Description = 'Agent42 - AI Agent Platform';
  \$sc.Save()
"
            info "Shortcut created! Find Agent42 on your Desktop."
            ;;

        Darwin)
            # macOS
            if [ -f "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
                BROWSER_NAME="Google Chrome"
            else
                warn "Safari does not support the --app flag required for chromeless mode."
                warn "Install Google Chrome for the best experience: https://www.google.com/chrome/"
                error "No Chromium-based browser found. Install Google Chrome: https://www.google.com/chrome/"
            fi

            info "Using browser: $BROWSER_NAME"
            APP_DIR="$HOME/Applications/Agent42.app/Contents/MacOS"
            mkdir -p "$APP_DIR"
            mkdir -p "$HOME/Applications/Agent42.app/Contents/Resources"

            cp "$PROJECT_DIR/dashboard/frontend/dist/assets/icons/icon-512.png" \
               "$HOME/Applications/Agent42.app/Contents/Resources/agent42.png"

            cat > "$APP_DIR/Agent42" << 'LAUNCHER'
#!/bin/bash
open -a "Google Chrome" --args --app=http://localhost:8000
LAUNCHER
            chmod +x "$APP_DIR/Agent42"

            cat > "$HOME/Applications/Agent42.app/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Agent42</string>
  <key>CFBundleDisplayName</key>
  <string>Agent42</string>
  <key>CFBundleIdentifier</key>
  <string>com.agent42.app</string>
  <key>CFBundleExecutable</key>
  <string>Agent42</string>
  <key>CFBundleVersion</key>
  <string>1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
</dict>
</plist>
PLIST
            info "Shortcut created! Find Agent42 in ~/Applications/."
            ;;

        Linux)
            # Linux — detect available Chromium-based browser
            if command -v google-chrome &>/dev/null; then
                BROWSER_CMD="google-chrome"
            elif command -v google-chrome-stable &>/dev/null; then
                BROWSER_CMD="google-chrome-stable"
            elif command -v chromium-browser &>/dev/null; then
                BROWSER_CMD="chromium-browser"
            elif command -v chromium &>/dev/null; then
                BROWSER_CMD="chromium"
            else
                error "No Chromium-based browser found. Install Google Chrome: https://www.google.com/chrome/"
            fi

            info "Using browser: $BROWSER_CMD"
            DESKTOP_DIR="$HOME/.local/share/applications"
            mkdir -p "$DESKTOP_DIR"
            ICON_PATH="$PROJECT_DIR/dashboard/frontend/dist/assets/icons/icon-512.png"

            cat > "$DESKTOP_DIR/agent42.desktop" << DESKTOP
[Desktop Entry]
Name=Agent42
Comment=AI Agent Platform — Don't Panic
Exec=$BROWSER_CMD --app=http://localhost:8000
Icon=$ICON_PATH
Type=Application
Categories=Development;
StartupWMClass=agent42
DESKTOP
            chmod +x "$DESKTOP_DIR/agent42.desktop"
            info "Shortcut created! Find Agent42 in your application launcher."
            ;;

        *)
            error "Unsupported platform: $OS. Supported: Windows (Git Bash/MSYS2), macOS, Linux."
            ;;
    esac

    exit 0
fi

QUIET=false
[ "$1" = "--quiet" ] && QUIET=true

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

# ── SSH alias for remote node ─────────────────────────────────────────────────
SSH_ALIAS=""
if ! $QUIET; then
    echo ""
    read -rp "  SSH alias for remote node (leave blank to skip): " SSH_ALIAS
fi

# ── MCP configuration ────────────────────────────────────────────────────────
info "Configuring MCP servers..."
if [ -n "$SSH_ALIAS" ]; then
    python3 scripts/setup_helpers.py mcp-config "$PROJECT_DIR" "$SSH_ALIAS"
else
    python3 scripts/setup_helpers.py mcp-config "$PROJECT_DIR"
fi
info "MCP configuration complete"

# ── Hook registration ────────────────────────────────────────────────────────
info "Registering Claude Code hooks..."
python3 scripts/setup_helpers.py register-hooks "$PROJECT_DIR"
info "Hooks registered"

# ── CLAUDE.md memory section ─────────────────────────────────────────────────
info "Generating CLAUDE.md memory section..."
python3 scripts/setup_helpers.py claude-md "$PROJECT_DIR"
info "CLAUDE.md memory section updated"

# ── jcodemunch indexing ───────────────────────────────────────────────────────
info "Indexing project with jcodemunch..."
if ! python3 scripts/jcodemunch_index.py "$PROJECT_DIR" --timeout=120; then
    warn "jcodemunch indexing failed — run manually: uvx jcodemunch-mcp"
fi

# ── Health report ─────────────────────────────────────────────────────────────
if ! $QUIET; then
    echo ""
    info "Running health checks..."
    python3 scripts/setup_helpers.py health "$PROJECT_DIR"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
if ! $QUIET; then
    echo ""
    info "Setup complete!"
    echo ""
    echo "  1. Start Agent42:  source .venv/bin/activate && python agent42.py"
    echo "  2. Open http://localhost:8000 to complete setup in your browser"
    echo "  3. MCP config:     .mcp.json (configured for Claude Code)"
    echo "  4. Hooks:          .claude/settings.json (auto-registered)"
    echo ""
    warn "Your git repo needs a 'dev' branch for coding/debugging/refactoring tasks."
    info "  git checkout -b dev  (if you don't have one)"
    info "  Non-code tasks (marketing, content, design, etc.) work without it."
    echo ""
fi
