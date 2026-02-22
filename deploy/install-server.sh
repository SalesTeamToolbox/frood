#!/usr/bin/env bash
# install-server.sh — Deploy Agent42 on a server alongside an existing web app
#
# Usage:
#   scp -r agent42/ user@163.245.217.2:~/agent42
#   ssh user@163.245.217.2
#   cd ~/agent42
#   bash deploy/install-server.sh
#
# Prerequisites:
#   - Ubuntu/Debian server with Nginx already installed
#   - DNS A record: agent42.meatheadgear.com → 163.245.217.2
#   - sudo access

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

DOMAIN="agent42.meatheadgear.com"
AGENT42_DIR="$(cd "$(dirname "$0")/.." && pwd)"
AGENT42_PORT=8002

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   Agent42 Server Deployment              ║"
echo "  ║   Target: ${DOMAIN}       ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Pre-flight checks ────────────────────────────────────────────────────────
info "Running pre-flight checks..."

# Must not be root (we'll use sudo when needed)
if [ "$(id -u)" -eq 0 ]; then
    error "Do not run as root. Run as your normal user (sudo will be used when needed)."
fi

# Check sudo access
if ! sudo -n true 2>/dev/null; then
    warn "sudo requires a password — you'll be prompted during installation."
fi

# Check nginx is installed
if ! command -v nginx &>/dev/null; then
    error "Nginx not found. Install it first: sudo apt install nginx"
fi

# Check if port 8000 is free
if ss -tlnp 2>/dev/null | grep -q ":${AGENT42_PORT} "; then
    warn "Port ${AGENT42_PORT} is already in use."
    warn "If that's another app, edit AGENT42_PORT in this script and deploy/nginx-agent42.conf"
    warn "Or use: python agent42.py --port 8001"
    echo ""
    read -rp "Continue anyway? [y/N] " reply
    [ "$reply" = "y" ] || [ "$reply" = "Y" ] || exit 1
fi

info "Pre-flight checks passed"

# ── Step 1: Run the standard setup ───────────────────────────────────────────
info "Step 1/6: Running Agent42 setup..."
cd "$AGENT42_DIR"
bash setup.sh

# ── Step 2: Configure .env for production ─────────────────────────────────────
info "Step 2/6: Configuring .env for production..."

if [ ! -f "$AGENT42_DIR/.env" ]; then
    cp "$AGENT42_DIR/.env.example" "$AGENT42_DIR/.env"
fi

# Generate a JWT secret if not already set
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
if grep -q "^JWT_SECRET=$" "$AGENT42_DIR/.env"; then
    sed -i "s/^JWT_SECRET=$/JWT_SECRET=${JWT_SECRET}/" "$AGENT42_DIR/.env"
    info "Generated JWT_SECRET"
fi

# Ensure DASHBOARD_HOST is 127.0.0.1 (nginx will handle external access)
if grep -q "^DASHBOARD_HOST=0.0.0.0" "$AGENT42_DIR/.env"; then
    sed -i "s/^DASHBOARD_HOST=0.0.0.0/DASHBOARD_HOST=127.0.0.1/" "$AGENT42_DIR/.env"
    info "Set DASHBOARD_HOST=127.0.0.1 (nginx handles external access)"
fi

# Set CORS for the subdomain
if grep -q "^CORS_ALLOWED_ORIGINS=$" "$AGENT42_DIR/.env"; then
    sed -i "s|^CORS_ALLOWED_ORIGINS=$|CORS_ALLOWED_ORIGINS=https://${DOMAIN}|" "$AGENT42_DIR/.env"
    info "Set CORS_ALLOWED_ORIGINS=https://${DOMAIN}"
fi

echo ""
warn "ACTION REQUIRED: Edit .env to set these values:"
warn "  1. OPENROUTER_API_KEY  — get a free key at https://openrouter.ai/keys"
warn "  2. DASHBOARD_PASSWORD  — change from the default!"
warn "  3. DEFAULT_REPO_PATH   — path to your git project"
echo ""
read -rp "Press Enter to open .env in nano (or Ctrl+C to edit later)..." _
${EDITOR:-nano} "$AGENT42_DIR/.env"

# ── Step 3: Install Nginx config ─────────────────────────────────────────────
info "Step 3/6: Installing Nginx reverse proxy config..."

# Create symlink if it doesn't exist
if [ ! -L /etc/nginx/sites-enabled/agent42 ]; then
    sudo ln -s /etc/nginx/sites-available/agent42 /etc/nginx/sites-enabled/agent42
fi

# SSL certs don't exist yet — start with HTTP-only config so certbot can run
info "Installing temporary HTTP-only config (certbot will add SSL next)..."
sudo tee /etc/nginx/sites-available/agent42 > /dev/null << NGINX_TEMP
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:${AGENT42_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /ws {
        proxy_pass http://127.0.0.1:${AGENT42_PORT};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
NGINX_TEMP

if sudo nginx -t 2>&1; then
    sudo systemctl reload nginx
    info "Nginx configured (HTTP only for now)"
else
    error "Nginx config test failed — check /etc/nginx/sites-available/agent42"
fi

# ── Step 4: SSL with Let's Encrypt ───────────────────────────────────────────
info "Step 4/6: Setting up SSL with Let's Encrypt..."

if ! command -v certbot &>/dev/null; then
    info "Installing certbot..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq certbot python3-certbot-nginx
fi

echo ""
info "Running certbot for ${DOMAIN}..."
info "Make sure your DNS A record points to this server first!"
echo ""
read -rp "DNS is configured and ready? [y/N] " dns_ready
if [ "$dns_ready" = "y" ] || [ "$dns_ready" = "Y" ]; then
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --redirect \
        --email "admin@${DOMAIN#*.}" || {
        warn "certbot failed — you can run it manually later:"
        warn "  sudo certbot --nginx -d ${DOMAIN}"
    }

    # certbot succeeded — install the full nginx config with rate limiting,
    # security headers, and WebSocket tuning
    info "Installing full Nginx config with SSL..."
    sudo cp "$AGENT42_DIR/deploy/nginx-agent42.conf" /etc/nginx/sites-available/agent42
    if sudo nginx -t 2>&1; then
        sudo systemctl reload nginx
        info "Full Nginx config installed"
    else
        warn "Full config failed nginx -t — certbot's auto-generated config is still active"
        warn "Check /etc/nginx/sites-available/agent42 and fix manually"
    fi
else
    warn "Skipping certbot. Run it manually when DNS is ready:"
    warn "  sudo certbot --nginx -d ${DOMAIN}"
    warn "Then install the full config:"
    warn "  sudo cp ${AGENT42_DIR}/deploy/nginx-agent42.conf /etc/nginx/sites-available/agent42"
    warn "  sudo nginx -t && sudo systemctl reload nginx"
fi

# ── Step 5: Install systemd service ──────────────────────────────────────────
info "Step 5/6: Installing systemd service..."

VENV_PYTHON="$AGENT42_DIR/.venv/bin/python"
CURRENT_USER=$(whoami)

sudo tee /etc/systemd/system/agent42.service > /dev/null << EOF
[Unit]
Description=Agent42 Multi-Agent Orchestrator
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${AGENT42_DIR}
ExecStart=${VENV_PYTHON} agent42.py --port ${AGENT42_PORT}
Restart=on-failure
RestartSec=5
StandardOutput=append:${AGENT42_DIR}/agent42.log
StandardError=append:${AGENT42_DIR}/agent42.log
EnvironmentFile=${AGENT42_DIR}/.env

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable agent42
info "Systemd service installed and enabled"

# ── Step 6: Configure firewall ───────────────────────────────────────────────
info "Step 6/6: Configuring firewall..."

if command -v ufw &>/dev/null; then
    # Allow HTTP and HTTPS through the firewall (nginx serves both)
    sudo ufw allow 'Nginx Full' 2>/dev/null || {
        sudo ufw allow 80/tcp
        sudo ufw allow 443/tcp
    }
    # Block direct access to Agent42 port from outside (nginx proxies it)
    sudo ufw deny "${AGENT42_PORT}/tcp" 2>/dev/null || true
    info "UFW firewall configured"
else
    warn "UFW not found — make sure ports 80/443 are open and port ${AGENT42_PORT} is blocked externally"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║   Installation complete!                             ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo ""
info "Start Agent42:"
echo "    sudo systemctl start agent42"
echo ""
info "Check status:"
echo "    sudo systemctl status agent42"
echo "    tail -f ${AGENT42_DIR}/agent42.log"
echo ""
info "Access dashboard:"
echo "    https://${DOMAIN}"
echo ""
info "Useful commands:"
echo "    sudo systemctl restart agent42    # Restart"
echo "    sudo systemctl stop agent42       # Stop"
echo "    sudo journalctl -u agent42 -f     # Live logs"
echo "    sudo certbot renew --dry-run      # Test cert renewal"
echo ""
warn "Reminders:"
warn "  - Make sure .env has your OPENROUTER_API_KEY and a strong DASHBOARD_PASSWORD"
warn "  - Your target git repo needs a 'dev' branch: git checkout -b dev"
warn "  - Certbot auto-renews via systemd timer (check: systemctl list-timers)"
echo ""
