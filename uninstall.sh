#!/usr/bin/env bash
# uninstall.sh — Frood uninstall script
# Removes Frood and all associated data, services, and configuration.
# Run from the frood directory: bash uninstall.sh

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

FROOD_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  _____                    _ "
echo " |  ___| __ ___   ___   __| |"
echo " | |_ | '__/ _ \ / _ \ / _\` |"
echo " |  _|| | | (_) | (_) | (_| |"
echo " |_|  |_|  \___/ \___/ \__,_|"
echo "                              "
echo ""
warn "Frood Uninstaller"
echo ""

# ── Detect what's installed ─────────────────────────────────────────────────
HAS_SYSTEMD=false
HAS_NGINX=false
HAS_DOCKER=false
HAS_STANDALONE_CONTAINERS=false
HAS_VENV=false
HAS_DATA=false
HAS_ENV=false

if systemctl list-unit-files frood.service &>/dev/null 2>&1 && \
   [ -f /etc/systemd/system/frood.service ]; then
    HAS_SYSTEMD=true
fi

if [ -f /etc/nginx/sites-available/frood ] || \
   [ -L /etc/nginx/sites-enabled/frood ]; then
    HAS_NGINX=true
fi

if [ -f "$FROOD_DIR/docker-compose.yml" ] && command -v docker &>/dev/null; then
    if docker compose ps --quiet 2>/dev/null | grep -q .; then
        HAS_DOCKER=true
    fi
fi

if command -v docker &>/dev/null; then
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qE '^(qdrant|redis)$'; then
        HAS_STANDALONE_CONTAINERS=true
    fi
fi

HAS_SYSTEM_QDRANT=false
HAS_SYSTEM_REDIS=false
[ -f "$FROOD_DIR/.frood-installed-qdrant" ] && HAS_SYSTEM_QDRANT=true
[ -f "$FROOD_DIR/.frood-installed-redis" ] && HAS_SYSTEM_REDIS=true

[ -d "$FROOD_DIR/.venv" ] && HAS_VENV=true
[ -d "$FROOD_DIR/.frood" ] || [ -d "$FROOD_DIR/data" ] || [ -d "$FROOD_DIR/apps" ] && HAS_DATA=true
[ -f "$FROOD_DIR/.env" ] && HAS_ENV=true

# ── Show what was detected ──────────────────────────────────────────────────
info "Detected installation components:"
echo ""
$HAS_VENV && echo "  - Python virtual environment (.venv/)"
$HAS_ENV && echo "  - Configuration file (.env)"
$HAS_DATA && echo "  - Runtime data (.frood/, data/, apps/)"
$HAS_SYSTEMD && echo "  - Systemd service (frood.service)"
$HAS_NGINX && echo "  - Nginx reverse proxy configuration"
$HAS_DOCKER && echo "  - Docker Compose stack (running)"
$HAS_STANDALONE_CONTAINERS && echo "  - Standalone Docker containers (qdrant, redis)"
$HAS_SYSTEM_QDRANT && echo "  - Qdrant system service (installed by Frood)"
$HAS_SYSTEM_REDIS && echo "  - Redis system service (installed by Frood)"
[ -f /tmp/frood.service ] && echo "  - Systemd service template (/tmp/frood.service)"
[ -f "$FROOD_DIR/frood.log" ] && echo "  - Log file (frood.log)"
echo ""

# ── Confirm ─────────────────────────────────────────────────────────────────
warn "This will permanently remove Frood and all its data."
echo ""
read -rp "  Are you sure you want to continue? [y/N] " confirm
echo ""
[ "$confirm" = "y" ] || [ "$confirm" = "Y" ] || { info "Uninstall cancelled."; exit 0; }

# ── Back up .env ────────────────────────────────────────────────────────────
if $HAS_ENV; then
    read -rp "  Back up .env to ~/.frood-env-backup before removing? [Y/n] " backup_env
    backup_env=${backup_env:-Y}
    if [ "$backup_env" = "Y" ] || [ "$backup_env" = "y" ]; then
        cp "$FROOD_DIR/.env" "$HOME/.frood-env-backup"
        info "Backed up .env to ~/.frood-env-backup"
    fi
    echo ""
fi

# ── Step 1: Stop Docker Compose stack ───────────────────────────────────────
if $HAS_DOCKER; then
    info "Stopping Docker Compose stack..."
    cd "$FROOD_DIR"
    docker compose down -v
    info "Docker stack stopped and volumes removed"

    read -rp "  Remove Docker images too? [y/N] " rm_images
    if [ "$rm_images" = "y" ] || [ "$rm_images" = "Y" ]; then
        docker rmi $(docker compose config --images 2>/dev/null) 2>/dev/null || true
        info "Docker images removed"
    fi
    echo ""
fi

# ── Step 2: Stop standalone containers ──────────────────────────────────────
if $HAS_STANDALONE_CONTAINERS; then
    info "Found standalone qdrant/redis containers."
    read -rp "  Stop and remove them? [y/N] " rm_containers
    if [ "$rm_containers" = "y" ] || [ "$rm_containers" = "Y" ]; then
        docker stop qdrant redis 2>/dev/null || true
        docker rm qdrant redis 2>/dev/null || true
        info "Standalone containers removed"
    fi
    echo ""
fi

# ── Step 2b: Remove system Qdrant if installed by Frood ───────────────────
if $HAS_SYSTEM_QDRANT; then
    info "Found Qdrant system service installed by Frood."
    read -rp "  Stop and remove Qdrant service? [y/N] " rm_qdrant
    if [ "$rm_qdrant" = "y" ] || [ "$rm_qdrant" = "Y" ]; then
        sudo systemctl stop qdrant 2>/dev/null || true
        sudo systemctl disable qdrant 2>/dev/null || true
        sudo rm -f /etc/systemd/system/qdrant.service
        sudo rm -f /usr/local/bin/qdrant
        sudo rm -rf /var/lib/qdrant
        sudo systemctl daemon-reload
        info "Qdrant service removed"
    fi
    echo ""
fi

# ── Step 2c: Remove system Redis if installed by Frood ────────────────────
if $HAS_SYSTEM_REDIS; then
    info "Found Redis installed by Frood."
    read -rp "  Stop and remove Redis? [y/N] " rm_redis
    if [ "$rm_redis" = "y" ] || [ "$rm_redis" = "Y" ]; then
        sudo systemctl stop redis-server 2>/dev/null || true
        sudo apt-get remove -y redis-server 2>/dev/null || true
        info "Redis service removed"
    fi
    echo ""
fi

# ── Step 3: Stop and remove systemd service ─────────────────────────────────
if $HAS_SYSTEMD; then
    info "Removing systemd service..."
    sudo systemctl stop frood 2>/dev/null || true
    sudo systemctl disable frood 2>/dev/null || true
    sudo rm -f /etc/systemd/system/frood.service
    sudo systemctl daemon-reload
    info "Systemd service removed"
    echo ""
fi

# ── Step 4: Remove nginx configuration ──────────────────────────────────────
if $HAS_NGINX; then
    info "Removing nginx configuration..."
    sudo rm -f /etc/nginx/sites-enabled/frood
    sudo rm -f /etc/nginx/sites-available/frood
    if sudo nginx -t 2>&1; then
        sudo systemctl reload nginx
        info "Nginx configuration removed and reloaded"
    else
        warn "Nginx config test failed after removal — check your nginx configuration"
    fi

    # Offer to remove SSL certs
    if command -v certbot &>/dev/null; then
        echo ""
        read -rp "  Remove Let's Encrypt SSL certificates for Frood? [y/N] " rm_certs
        if [ "$rm_certs" = "y" ] || [ "$rm_certs" = "Y" ]; then
            read -rp "  Enter the domain (e.g., frood.example.com): " cert_domain
            if [ -n "$cert_domain" ]; then
                sudo certbot delete --cert-name "$cert_domain" || \
                    warn "Could not remove certificate for $cert_domain"
            fi
        fi
    fi
    echo ""
fi

# ── Step 5: Remove firewall rules ───────────────────────────────────────────
if $HAS_SYSTEMD && command -v ufw &>/dev/null; then
    # Remove any Frood-related deny rules (check common ports)
    for port in 8000 8001 8002; do
        if sudo ufw status 2>/dev/null | grep -q "${port}.*DENY"; then
            info "Removing UFW firewall rule for port ${port}..."
            sudo ufw delete deny "${port}/tcp" 2>/dev/null || true
            info "Firewall rule removed for port ${port}"
        fi
    done
fi

# ── Step 6: Remove Frood files ──────────────────────────────────────────────
info "Removing Frood files..."

# Remove runtime data
rm -rf "$FROOD_DIR/.venv"
rm -rf "$FROOD_DIR/.frood"
rm -rf "$FROOD_DIR/data"
rm -rf "$FROOD_DIR/apps"
rm -f "$FROOD_DIR/.env"
rm -f "$FROOD_DIR/frood.log"
rm -f "$FROOD_DIR/.frood-installed-redis"
rm -f "$FROOD_DIR/.frood-installed-qdrant"
rm -f /tmp/frood.service
info "Frood files removed"

# ── Step 7: Remove the directory itself ─────────────────────────────────────
echo ""
read -rp "  Delete the entire Frood directory ($FROOD_DIR)? [y/N] " rm_dir
if [ "$rm_dir" = "y" ] || [ "$rm_dir" = "Y" ]; then
    cd "$HOME"
    rm -rf "$FROOD_DIR"
    info "Frood directory removed"
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║   Frood has been uninstalled.                         ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo ""
if [ -f "$HOME/.frood-env-backup" ]; then
    info "Your .env backup is at: ~/.frood-env-backup"
fi
info "To reinstall, clone the repository and run: bash setup.sh"
echo ""
