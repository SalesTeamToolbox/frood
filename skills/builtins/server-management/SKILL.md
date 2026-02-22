---
name: server-management
description: Install, configure, and manage web servers, services, and infrastructure on Linux systems.
always: false
task_types: [coding, deployment]
requirements_bins: [ssh]
---

# Server Management Skill

You are managing Linux servers. Use the SSH tool to execute commands on remote hosts. Always verify before making destructive changes.

## LAMP Stack (Ubuntu/Debian)

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Apache + MySQL + PHP
sudo apt install -y apache2 mysql-server php php-mysql libapache2-mod-php php-cli php-curl php-gd php-mbstring php-xml php-zip

# Enable Apache modules
sudo a2enmod rewrite ssl headers
sudo systemctl restart apache2

# Secure MySQL
sudo mysql_secure_installation
```

## LEMP Stack (Ubuntu/Debian)

```bash
# Nginx + MySQL + PHP-FPM
sudo apt install -y nginx mysql-server php-fpm php-mysql php-cli php-curl php-gd php-mbstring php-xml php-zip

# Configure PHP-FPM socket in nginx
# /etc/nginx/sites-available/default:
#   location ~ \.php$ {
#       fastcgi_pass unix:/var/run/php/php-fpm.sock;
#       fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
#       include fastcgi_params;
#   }
```

## RHEL/CentOS/Rocky

```bash
sudo dnf install -y httpd mariadb-server php php-mysqlnd php-fpm
sudo systemctl enable --now httpd mariadb
sudo mysql_secure_installation
```

## Nginx Virtual Host

```nginx
server {
    listen 80;
    server_name example.com www.example.com;
    root /var/www/example.com/public;
    index index.php index.html;

    location / {
        try_files $uri $uri/ /index.php?$query_string;
    }

    location ~ \.php$ {
        fastcgi_pass unix:/var/run/php/php-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }

    location ~ /\.ht { deny all; }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/example.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## SSL with Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com -d www.example.com
# Auto-renewal is configured automatically via systemd timer
sudo certbot renew --dry-run  # Test renewal
```

## systemd Service Management

```bash
sudo systemctl start|stop|restart|enable|disable|status SERVICE
sudo journalctl -u SERVICE -f          # Live logs
sudo journalctl -u SERVICE --since "1 hour ago"
sudo systemctl daemon-reload           # After editing .service files
```

## Firewall (UFW)

```bash
sudo ufw allow 22/tcp        # SSH
sudo ufw allow 80/tcp        # HTTP
sudo ufw allow 443/tcp       # HTTPS
sudo ufw enable
sudo ufw status verbose
```

## Firewall (firewalld — RHEL/CentOS)

```bash
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
sudo firewall-cmd --list-all
```

## Security Hardening Checklist

1. **SSH**: Disable root login, use key-based auth only
   ```bash
   # /etc/ssh/sshd_config
   PermitRootLogin no
   PasswordAuthentication no
   ```
2. **fail2ban**: Install and configure for SSH brute force protection
   ```bash
   sudo apt install -y fail2ban
   sudo systemctl enable --now fail2ban
   ```
3. **Unattended upgrades**: Auto-install security patches
   ```bash
   sudo apt install -y unattended-upgrades
   sudo dpkg-reconfigure -plow unattended-upgrades
   ```
4. **Minimal packages**: Remove unused services
5. **File permissions**: Ensure web files owned by www-data, not world-writable

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Port already in use | `sudo lsof -i :PORT` or `sudo ss -tlnp \| grep PORT` |
| Permission denied | `ls -la` permissions, `namei -l /path`, SELinux (`getenforce`) |
| Service won't start | `journalctl -u SERVICE -n 50`, config syntax test |
| DNS not resolving | `dig example.com`, check `/etc/hosts`, DNS A/CNAME records |
| Disk full | `df -h`, `du -sh /var/log/*`, clear old logs |
| High CPU/memory | `htop`, `top`, identify runaway processes |

## Guidelines

- Always take a backup or snapshot before major changes
- Test config changes with syntax check before reloading (e.g., `nginx -t`, `apachectl configtest`)
- Use `screen` or `tmux` for long-running operations over SSH
- Document every change you make for the operator's reference
- Prefer package manager installations over compiling from source
