---
name: cms-deploy
description: Deploy and configure content management systems including Ghost, Strapi, and general CMS patterns.
always: false
task_types: [coding, deployment]
---

# CMS Deployment Skill

You are deploying content management systems. Each CMS has specific requirements — follow the patterns below for reliable installations.

## Ghost CMS

### Docker Deployment (Recommended)

```yaml
version: "3.8"
services:
  ghost:
    image: ghost:5-alpine
    ports:
      - "2368:2368"
    environment:
      url: https://blog.example.com
      database__client: mysql
      database__connection__host: db
      database__connection__user: ghost
      database__connection__password: ${GHOST_DB_PASSWORD}
      database__connection__database: ghost
      mail__transport: SMTP
      mail__options__host: smtp.example.com
      mail__options__port: 587
      mail__options__auth__user: ${SMTP_USER}
      mail__options__auth__pass: ${SMTP_PASS}
    volumes:
      - ghost_content:/var/lib/ghost/content
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  db:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: ghost
      MYSQL_USER: ghost
      MYSQL_PASSWORD: ${GHOST_DB_PASSWORD}
    volumes:
      - ghost_db:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      retries: 5
    restart: unless-stopped

volumes:
  ghost_content:
  ghost_db:
```

### Manual Installation

```bash
# Install Node.js 18 LTS
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs

# Install Ghost CLI
sudo npm install -g ghost-cli

# Create directory and install
sudo mkdir -p /var/www/ghost
sudo chown $USER:$USER /var/www/ghost
cd /var/www/ghost
ghost install
```

## Strapi Headless CMS

### Docker Deployment

```yaml
version: "3.8"
services:
  strapi:
    image: strapi/strapi:latest
    environment:
      DATABASE_CLIENT: postgres
      DATABASE_HOST: db
      DATABASE_PORT: 5432
      DATABASE_NAME: strapi
      DATABASE_USERNAME: strapi
      DATABASE_PASSWORD: ${STRAPI_DB_PASSWORD}
      JWT_SECRET: ${STRAPI_JWT_SECRET}
      ADMIN_JWT_SECRET: ${STRAPI_ADMIN_JWT_SECRET}
      APP_KEYS: ${STRAPI_APP_KEYS}
    ports:
      - "1337:1337"
    volumes:
      - strapi_data:/srv/app
    depends_on:
      - db
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: strapi
      POSTGRES_USER: strapi
      POSTGRES_PASSWORD: ${STRAPI_DB_PASSWORD}
    volumes:
      - strapi_db:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  strapi_data:
  strapi_db:
```

### Local Development

```bash
npx create-strapi-app@latest my-project --quickstart
cd my-project
npm run develop
```

## General CMS Deployment Patterns

### Database Setup

```bash
# PostgreSQL
sudo -u postgres createuser cmsuser -P
sudo -u postgres createdb cmsdb -O cmsuser

# MySQL
sudo mysql -e "CREATE DATABASE cmsdb CHARACTER SET utf8mb4;"
sudo mysql -e "CREATE USER 'cmsuser'@'localhost' IDENTIFIED BY 'password';"
sudo mysql -e "GRANT ALL ON cmsdb.* TO 'cmsuser'@'localhost';"
```

### Media Storage

For production CMS deployments, consider:
1. **Local disk**: Simple but doesn't scale. Use named Docker volumes.
2. **S3-compatible**: MinIO (self-hosted) or AWS S3 for scalable media storage.
3. **CDN**: CloudFlare or CloudFront in front of media storage.

### Reverse Proxy (nginx)

```nginx
server {
    listen 80;
    server_name cms.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name cms.example.com;

    ssl_certificate /etc/letsencrypt/live/cms.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cms.example.com/privkey.pem;

    client_max_body_size 50M;  # Allow large file uploads

    location / {
        proxy_pass http://localhost:PORT;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (for live-editing features)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Domain & DNS Configuration

```
# A Records
@     A     YOUR_SERVER_IP
www   A     YOUR_SERVER_IP

# Or use CNAME for www
www   CNAME example.com.

# For subdomains
blog  A     YOUR_SERVER_IP
cms   A     YOUR_SERVER_IP
```

After DNS propagation (check with `dig example.com`):
```bash
sudo certbot --nginx -d cms.example.com
```

## SSL Certificate Patterns

1. **Let's Encrypt** (free, auto-renewal): `certbot --nginx -d domain.com`
2. **Cloudflare** (proxy + free SSL): Set DNS to proxy mode, use Full (Strict) SSL
3. **Self-signed** (dev only): `openssl req -x509 -nodes -days 365 -newkey rsa:2048 ...`

## Guidelines

- Always use environment variables for secrets (DB passwords, API keys, JWT secrets)
- Set up automated backups for both database and uploaded media
- Use a reverse proxy (nginx) in front of CMS applications
- Configure `client_max_body_size` in nginx for file uploads
- Enable HTTPS before going live
- Set proper CORS headers if using headless CMS with a separate frontend
- Monitor disk usage — CMS media uploads can grow quickly
