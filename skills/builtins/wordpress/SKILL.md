---
name: wordpress
description: Install, configure, manage, and optimize WordPress sites including themes, plugins, and WP-CLI.
always: false
task_types: [coding, deployment]
requirements_bins: [ssh]
---

# WordPress Deployment Skill

You are deploying and managing WordPress. Use the SSH tool for remote server operations. Always back up before making changes.

## Prerequisites

Ensure the server has a working LAMP or LEMP stack (see server-management skill).

## WordPress Installation (WP-CLI — Recommended)

```bash
# Install WP-CLI
curl -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar
chmod +x wp-cli.phar
sudo mv wp-cli.phar /usr/local/bin/wp

# Create database
sudo mysql -e "CREATE DATABASE wordpress DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
sudo mysql -e "CREATE USER 'wpuser'@'localhost' IDENTIFIED BY 'STRONG_PASSWORD_HERE';"
sudo mysql -e "GRANT ALL PRIVILEGES ON wordpress.* TO 'wpuser'@'localhost';"
sudo mysql -e "FLUSH PRIVILEGES;"

# Download and install WordPress
cd /var/www/example.com
sudo -u www-data wp core download
sudo -u www-data wp config create \
    --dbname=wordpress \
    --dbuser=wpuser \
    --dbpass='STRONG_PASSWORD_HERE' \
    --dbhost=localhost \
    --dbprefix=wp_

sudo -u www-data wp core install \
    --url="https://example.com" \
    --title="Site Title" \
    --admin_user=admin \
    --admin_password='ADMIN_PASSWORD' \
    --admin_email=admin@example.com

# Set permissions
sudo chown -R www-data:www-data /var/www/example.com
sudo find /var/www/example.com -type d -exec chmod 755 {} \;
sudo find /var/www/example.com -type f -exec chmod 644 {} \;
```

## Manual Installation (Without WP-CLI)

```bash
cd /tmp
wget https://wordpress.org/latest.tar.gz
tar xzf latest.tar.gz
sudo mv wordpress/* /var/www/example.com/
sudo chown -R www-data:www-data /var/www/example.com
```

Then visit `https://example.com` to run the web installer.

## wp-config.php Essentials

```php
// Database settings (set during install)
define('DB_NAME', 'wordpress');
define('DB_USER', 'wpuser');
define('DB_PASSWORD', 'STRONG_PASSWORD');
define('DB_HOST', 'localhost');
define('DB_CHARSET', 'utf8mb4');

// Security salts — generate from https://api.wordpress.org/secret-key/1.1/salt/
// Or: wp config shuffle-salts

// Debug mode (disable in production!)
define('WP_DEBUG', false);
define('WP_DEBUG_LOG', false);
define('WP_DEBUG_DISPLAY', false);

// Force HTTPS
define('FORCE_SSL_ADMIN', true);

// Disable file editing in admin
define('DISALLOW_FILE_EDIT', true);

// Limit post revisions
define('WP_POST_REVISIONS', 5);

// Auto-save interval (seconds)
define('AUTOSAVE_INTERVAL', 120);
```

## Theme & Plugin Management (WP-CLI)

```bash
# Themes
wp theme install flavor flavor --activate
wp theme list
wp theme update --all

# Plugins
wp plugin install wordfence --activate
wp plugin install w3-total-cache --activate
wp plugin install updraftplus --activate
wp plugin list
wp plugin update --all

# Recommended security plugins
wp plugin install wordfence --activate      # Firewall + malware scan
wp plugin install sucuri-scanner --activate  # Security auditing

# Recommended performance plugins
wp plugin install w3-total-cache --activate  # Caching
wp plugin install autoptimize --activate     # CSS/JS optimization
```

## WordPress Multisite

```bash
# Enable multisite in wp-config.php (before "That's all, stop editing!")
define('WP_ALLOW_MULTISITE', true);

# After enabling in Network Setup admin page:
define('MULTISITE', true);
define('SUBDOMAIN_INSTALL', false);
define('DOMAIN_CURRENT_SITE', 'example.com');
define('PATH_CURRENT_SITE', '/');
define('SITE_ID_CURRENT_SITE', 1);
define('BLOG_ID_CURRENT_SITE', 1);
```

## Backup & Restore

```bash
# Database backup
wp db export backup.sql

# Full backup (files + database)
tar czf wp-backup-$(date +%Y%m%d).tar.gz /var/www/example.com
wp db export /var/www/example.com/db-backup.sql

# Restore database
wp db import backup.sql

# Automated backups with UpdraftPlus
wp plugin install updraftplus --activate
```

## Performance Optimization

1. **Caching**: Install W3 Total Cache or WP Super Cache
2. **PHP-FPM tuning**:
   ```ini
   ; /etc/php/8.x/fpm/pool.d/www.conf
   pm = dynamic
   pm.max_children = 25
   pm.start_servers = 5
   pm.min_spare_servers = 3
   pm.max_spare_servers = 10
   ```
3. **MySQL tuning**: Increase `innodb_buffer_pool_size` to ~70% of available RAM
4. **CDN**: Configure CloudFlare or other CDN
5. **Image optimization**: Install Imagify or ShortPixel plugin

## Security Hardening

1. Change default admin username (never use "admin")
2. Set strong passwords for all users
3. Install Wordfence or Sucuri security plugin
4. Disable XML-RPC if not needed: `wp plugin install disable-xml-rpc --activate`
5. Set file permissions correctly (755 dirs, 644 files)
6. Restrict wp-admin access by IP if possible
7. Keep WordPress, themes, and plugins updated
8. Remove unused themes and plugins

## Nginx Configuration for WordPress

```nginx
server {
    listen 80;
    server_name example.com www.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name example.com www.example.com;
    root /var/www/example.com;
    index index.php;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location / {
        try_files $uri $uri/ /index.php?$args;
    }

    location ~ \.php$ {
        fastcgi_pass unix:/var/run/php/php-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }

    # Block access to sensitive files
    location ~ /\.(ht|git|svn) { deny all; }
    location ~* /wp-config\.php { deny all; }
    location ~* /readme\.html { deny all; }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

## Guidelines

- Always generate unique security salts for each installation
- Never use "admin" as the admin username
- Keep WP core, themes, and plugins updated
- Use strong, unique database passwords
- Disable file editing in wp-admin (DISALLOW_FILE_EDIT)
- Take a full backup before any major update or plugin change
- Test changes on a staging site before production when possible
