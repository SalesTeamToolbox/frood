#!/usr/bin/env bash
# install-server.sh — Deploy Agent42 on a production server
#
# Usage:
#   scp -r agent42/ user@server:~/agent42
#   ssh user@server
#   cd ~/agent42
#   bash deploy/install-server.sh
#
# What this script does:
#   1. Runs setup.sh (venv, deps, frontend)
#   2. Installs Redis and Qdrant as system services
#   3. Auto-configures .env for production
#   4. Sets up nginx reverse proxy + SSL
#   5. Installs Agent42 as a systemd service
#   6. Configures firewall
#
# After installation, open your browser to complete setup (password, API key).

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

AGENT42_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   Agent42 Server Deployment              ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── Prompt for domain and port ────────────────────────────────────────────────
read -rp "  Enter your domain name (e.g., agent42.example.com): " DOMAIN
[ -z "$DOMAIN" ] && error "Domain name is required."

read -rp "  Enter the backend port [8002]: " AGENT42_PORT
AGENT42_PORT=${AGENT42_PORT:-8002}

echo ""
info "Domain:  ${DOMAIN}"
info "Port:    ${AGENT42_PORT}"
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

# Check if port is free
if ss -tlnp 2>/dev/null | grep -q ":${AGENT42_PORT} "; then
    warn "Port ${AGENT42_PORT} is already in use."
    echo ""
    read -rp "Continue anyway? [y/N] " reply
    [ "$reply" = "y" ] || [ "$reply" = "Y" ] || exit 1
fi

info "Pre-flight checks passed"

# ── Step 1: Run the standard setup (quiet mode) ─────────────────────────────
info "Step 1/7: Running Agent42 setup..."
cd "$AGENT42_DIR"
bash setup.sh --quiet

# ── Step 2: Configure .env for production ────────────────────────────────────
info "Step 2/7: Configuring .env for production..."

if [ ! -f "$AGENT42_DIR/.env" ]; then
    cp "$AGENT42_DIR/.env.example" "$AGENT42_DIR/.env"
fi

# Generate a JWT secret if not already set
JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
if grep -q "^JWT_SECRET=$" "$AGENT42_DIR/.env" 2>/dev/null; then
    sed -i "s/^JWT_SECRET=$/JWT_SECRET=${JWT_SECRET}/" "$AGENT42_DIR/.env"
    info "Generated JWT_SECRET"
fi

# Ensure DASHBOARD_HOST is 127.0.0.1 (nginx handles external access)
sed -i "s/^DASHBOARD_HOST=0.0.0.0/DASHBOARD_HOST=127.0.0.1/" "$AGENT42_DIR/.env"

# Set CORS for the domain
if grep -q "^CORS_ALLOWED_ORIGINS=$" "$AGENT42_DIR/.env" 2>/dev/null; then
    sed -i "s|^CORS_ALLOWED_ORIGINS=$|CORS_ALLOWED_ORIGINS=https://${DOMAIN}|" "$AGENT42_DIR/.env"
    info "Set CORS_ALLOWED_ORIGINS=https://${DOMAIN}"
fi

# Pre-configure Redis and Qdrant URLs (services installed in next steps)
_set_env() {
    local key="$1" value="$2" file="$AGENT42_DIR/.env"
    if grep -q "^#\?\s*${key}=" "$file" 2>/dev/null; then
        sed -i "s|^#\?\s*${key}=.*|${key}=${value}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

_set_env "QDRANT_URL" "http://localhost:6333"
_set_env "QDRANT_ENABLED" "true"
_set_env "REDIS_URL" "redis://localhost:6379/0"
info "Configured Redis + Qdrant URLs in .env"

# ── Step 3: Install Redis ────────────────────────────────────────────────────
info "Step 3/7: Setting up Redis..."

if ! command -v redis-server &>/dev/null; then
    info "Installing Redis..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq redis-server
    info "Redis installed"
else
    info "Redis already installed"
fi

sudo systemctl enable redis-server 2>/dev/null || true
sudo systemctl start redis-server 2>/dev/null || true
touch "$AGENT42_DIR/.agent42-installed-redis"
info "Redis is running"

# ── Step 4: Install Qdrant ───────────────────────────────────────────────────
info "Step 4/7: Setting up Qdrant..."

QDRANT_VERSION="1.13.2"

if ! systemctl is-active --quiet qdrant 2>/dev/null; then
    if [ ! -f /usr/local/bin/qdrant ]; then
        info "Downloading Qdrant v${QDRANT_VERSION}..."
        curl -sSL "https://github.com/qdrant/qdrant/releases/download/v${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-musl.tar.gz" \
            -o /tmp/qdrant.tar.gz
        sudo tar -xzf /tmp/qdrant.tar.gz -C /usr/local/bin/
        rm -f /tmp/qdrant.tar.gz
        sudo chmod +x /usr/local/bin/qdrant
        info "Qdrant binary installed"
    fi

    sudo mkdir -p /var/lib/qdrant/storage

    sudo tee /etc/systemd/system/qdrant.service > /dev/null << 'QDRANT_UNIT'
[Unit]
Description=Qdrant Vector Database
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/qdrant --storage-path /var/lib/qdrant/storage
Restart=on-failure
RestartSec=5
User=nobody
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
QDRANT_UNIT

    sudo systemctl daemon-reload
    sudo systemctl enable qdrant
    sudo systemctl start qdrant
    info "Qdrant service installed and started"
else
    info "Qdrant is already running"
fi

touch "$AGENT42_DIR/.agent42-installed-qdrant"

# ── Step 5: Install Nginx config ─────────────────────────────────────────────
info "Step 5/7: Installing Nginx reverse proxy config..."

# Create symlink if it doesn't exist
if [ ! -L /etc/nginx/sites-enabled/agent42 ]; then
    sudo ln -sf /etc/nginx/sites-available/agent42 /etc/nginx/sites-enabled/agent42
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

# ── Step 6: SSL with Let's Encrypt ───────────────────────────────────────────
info "Step 6/7: Setting up SSL with Let's Encrypt..."

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
    sed -e "s/__DOMAIN__/${DOMAIN}/g" -e "s/__PORT__/${AGENT42_PORT}/g" \
        "$AGENT42_DIR/deploy/nginx-agent42.conf" | sudo tee /etc/nginx/sites-available/agent42 > /dev/null
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
    warn "  sed -e 's/__DOMAIN__/${DOMAIN}/g' -e 's/__PORT__/${AGENT42_PORT}/g' \\"
    warn "      ${AGENT42_DIR}/deploy/nginx-agent42.conf | sudo tee /etc/nginx/sites-available/agent42"
    warn "  sudo nginx -t && sudo systemctl reload nginx"
fi

# ── Step 7: Install systemd service + firewall ───────────────────────────────
info "Step 7/7: Installing systemd service and firewall rules..."

VENV_PYTHON="$AGENT42_DIR/.venv/bin/python"
CURRENT_USER=$(whoami)

sudo tee /etc/systemd/system/agent42.service > /dev/null << EOF
[Unit]
Description=Agent42 Multi-Agent Orchestrator
After=network.target redis-server.service qdrant.service

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${AGENT42_DIR}
ExecStart=${VENV_PYTHON} agent42.py --port ${AGENT42_PORT}
Restart=always
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

# Configure firewall
if command -v ufw &>/dev/null; then
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
info "Then open your browser to complete setup:"
echo ""
echo "    https://${DOMAIN}"
echo ""
info "The setup wizard will guide you through:"
echo "    - Setting your dashboard password"
echo "    - Adding your API key (free at https://openrouter.ai/keys)"
echo "    - Configuring memory backend"
echo ""
info "Useful commands:"
echo "    sudo systemctl restart agent42    # Restart"
echo "    sudo systemctl stop agent42       # Stop"
echo "    sudo systemctl status agent42     # Status"
echo "    sudo journalctl -u agent42 -f     # Live logs"
echo "    sudo certbot renew --dry-run      # Test cert renewal"
echo ""
