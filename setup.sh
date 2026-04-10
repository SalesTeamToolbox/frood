#!/usr/bin/env bash
# setup.sh — Frood setup script
# Run once after cloning: bash setup.sh
# Use --quiet when called from install-server.sh (suppresses banners/prompts)
#
# Subcommands:
#   bash setup.sh              Full local setup (default)
#   bash setup.sh sync-auth    Sync CC credentials to remote VPS
#   bash setup.sh create-shortcut  Create desktop shortcut for Frood
#   bash setup.sh generate-claude-md  Generate CLAUDE.md with Frood conventions
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

# ── Platform detection ────────────────────────────────────────────────────
OS_TYPE="$(uname -s)"
case "$OS_TYPE" in
    MINGW*|MSYS*|CYGWIN*)
        VENV_ACTIVATE=".venv/Scripts/activate"
        PYTHON_CMD="python"
        ;;
    *)
        VENV_ACTIVATE=".venv/bin/activate"
        PYTHON_CMD="python3"
        ;;
esac

# ── Subcommand: sync-auth ──────────────────────────────────────────────────
if [ "$1" = "sync-auth" ]; then
    SSH_ALIAS="${2:-frood-prod}"
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
        ssh "$SSH_ALIAS" "claude auth status 2>&1" 2>/dev/null | $PYTHON_CMD -c "
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

            # Generate .ico if missing (Windows shortcuts require .ico, not .png)
            ICO_FILE="$PROJECT_DIR/dashboard/frontend/dist/assets/icons/frood.ico"
            if [ ! -f "$ICO_FILE" ]; then
                info "Generating .ico icon file..."
                $PYTHON_CMD "$PROJECT_DIR/scripts/generate-icons.py" --ico-only 2>/dev/null || \
                $PYTHON_CMD -c "
from PIL import Image
import struct, io
src = Image.open('$PROJECT_DIR/dashboard/frontend/dist/assets/icons/icon-512.png').convert('RGBA')
sizes = [16, 32, 48, 64, 128, 256]
entries = []
for s in sizes:
    buf = io.BytesIO()
    src.resize((s, s), Image.LANCZOS).save(buf, format='PNG')
    entries.append((s, buf.getvalue()))
header = struct.pack('<HHH', 0, 1, len(entries))
data_offset = 6 + 16 * len(entries)
dir_entries = image_data = b''
for s, png in entries:
    w = h = 0 if s >= 256 else s
    dir_entries += struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(png), data_offset + len(image_data))
    image_data += png
open('$ICO_FILE', 'wb').write(header + dir_entries + image_data)
" 2>/dev/null
                if [ -f "$ICO_FILE" ]; then
                    info "Generated frood.ico"
                else
                    warn "Could not generate .ico — shortcut will use default browser icon"
                fi
            fi

            ICON_PATH="$(cygpath -w "$ICO_FILE" 2>/dev/null || echo "${ICO_FILE//\//\\}")"
            BROWSER_WIN="$(cygpath -w "$BROWSER_PATH" 2>/dev/null || echo "$BROWSER_PATH")"
            WORKDIR_WIN="$(cygpath -w "$PROJECT_DIR" 2>/dev/null || echo "$PROJECT_DIR")"

            powershell.exe -NoProfile -Command "
  \$desktop = [Environment]::GetFolderPath('Desktop');
  \$lnkPath = Join-Path \$desktop 'Frood.lnk';
  if (Test-Path \$lnkPath) { Remove-Item \$lnkPath -Force };
  \$ws = New-Object -ComObject WScript.Shell;
  \$sc = \$ws.CreateShortcut(\$lnkPath);
  \$sc.TargetPath = '$BROWSER_WIN';
  \$sc.Arguments = '--app=http://localhost:8000';
  \$sc.IconLocation = '$ICON_PATH,0';
  \$sc.Description = 'Frood - AI Agent Platform';
  \$sc.WorkingDirectory = '$WORKDIR_WIN';
  \$sc.Save();
  attrib -U +P \$lnkPath 2>\$null
"
            info "Shortcut created! Find Frood on your Desktop."
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
            APP_DIR="$HOME/Applications/Frood.app/Contents/MacOS"
            mkdir -p "$APP_DIR"
            mkdir -p "$HOME/Applications/Frood.app/Contents/Resources"

            cp "$PROJECT_DIR/dashboard/frontend/dist/assets/icons/icon-512.png" \
               "$HOME/Applications/Frood.app/Contents/Resources/frood.png"

            cat > "$APP_DIR/Frood" << 'LAUNCHER'
#!/bin/bash
open -a "Google Chrome" --args --app=http://localhost:8000
LAUNCHER
            chmod +x "$APP_DIR/Frood"

            cat > "$HOME/Applications/Frood.app/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>Frood</string>
  <key>CFBundleDisplayName</key>
  <string>Frood</string>
  <key>CFBundleIdentifier</key>
  <string>com.frood.app</string>
  <key>CFBundleExecutable</key>
  <string>Frood</string>
  <key>CFBundleVersion</key>
  <string>1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
</dict>
</plist>
PLIST
            info "Shortcut created! Find Frood in ~/Applications/."
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

            cat > "$DESKTOP_DIR/frood.desktop" << DESKTOP
[Desktop Entry]
Name=Frood
Comment=AI Agent Platform — Don't Panic
Exec=$BROWSER_CMD --app=http://localhost:8000
Icon=$ICON_PATH
Type=Application
Categories=Development;
StartupWMClass=frood
DESKTOP
            chmod +x "$DESKTOP_DIR/frood.desktop"
            info "Shortcut created! Find Frood in your application launcher."
            ;;

        *)
            error "Unsupported platform: $OS. Supported: Windows (Git Bash/MSYS2), macOS, Linux."
            ;;
    esac

    exit 0
fi

# ── Subcommand: generate-claude-md ───────────────────────────────────────────
if [ "$1" = "generate-claude-md" ]; then
    info "Generating CLAUDE.md with Frood conventions..."
    $PYTHON_CMD scripts/setup_helpers.py generate-claude-md "$PROJECT_DIR"
    info "Done! Review CLAUDE.md for your project."
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
if ! command -v $PYTHON_CMD &>/dev/null; then
    error "Python 3 not found. Install Python 3.11+."
fi

PY_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")

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
$PYTHON_CMD -m venv .venv
source "$VENV_ACTIVATE"

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
    $PYTHON_CMD scripts/setup_helpers.py mcp-config "$PROJECT_DIR" "$SSH_ALIAS"
else
    $PYTHON_CMD scripts/setup_helpers.py mcp-config "$PROJECT_DIR"
fi
info "MCP configuration complete"

# ── Hook registration ────────────────────────────────────────────────────────
info "Registering Claude Code hooks..."
$PYTHON_CMD scripts/setup_helpers.py register-hooks "$PROJECT_DIR"
info "Hooks registered"

# ── CLAUDE.md memory section ─────────────────────────────────────────────────
info "Generating CLAUDE.md memory section..."
$PYTHON_CMD scripts/setup_helpers.py claude-md "$PROJECT_DIR"
info "CLAUDE.md memory section updated"

# ── jcodemunch indexing ───────────────────────────────────────────────────────
info "Indexing project with jcodemunch..."
if ! $PYTHON_CMD scripts/jcodemunch_index.py "$PROJECT_DIR" --timeout=120; then
    warn "jcodemunch indexing failed — run manually: uvx jcodemunch-mcp"
fi

# ── Health report ─────────────────────────────────────────────────────────────
if ! $QUIET; then
    echo ""
    info "Running health checks..."
    $PYTHON_CMD scripts/setup_helpers.py health "$PROJECT_DIR"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
if ! $QUIET; then
    echo ""
    info "Setup complete!"
    echo ""
    echo "  1. Start Frood:    source $VENV_ACTIVATE && python frood.py"
    echo "  2. Open http://localhost:8000 to complete setup in your browser"
    echo "  3. MCP config:     .mcp.json (configured for Claude Code)"
    echo "  4. Hooks:          .claude/settings.json (auto-registered)"
    echo ""
    warn "Your git repo needs a 'dev' branch for coding/debugging/refactoring tasks."
    info "  git checkout -b dev  (if you don't have one)"
    info "  Non-code tasks (marketing, content, design, etc.) work without it."
    echo ""
fi
