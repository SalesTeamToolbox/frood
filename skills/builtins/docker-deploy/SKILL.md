---
name: docker-deploy
description: Build, deploy, and manage applications using Docker containers and Docker Compose.
always: false
task_types: [coding, deployment]
requirements_bins: [docker]
---

# Docker Deployment Skill

You are deploying applications using Docker. Focus on production-ready configurations with security and reliability.

## Dockerfile Best Practices

```dockerfile
# Multi-stage build — keeps final image small
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .
RUN npm run build

FROM node:20-alpine AS runtime
# Run as non-root user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
USER appuser
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost:3000/health || exit 1
CMD ["node", "dist/index.js"]
```

### Python Dockerfile

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
RUN useradd -m -r appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY . .
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD curl -f http://localhost:8000/health || exit 1
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "app:app"]
```

## Docker Compose — Common Stacks

### Web App + Database + Redis

```yaml
version: "3.8"

services:
  app:
    build: .
    ports:
      - "3000:3000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/myapp
      - REDIS_URL=redis://redis:6379
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  db:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U user -d myapp"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    restart: unless-stopped

volumes:
  pgdata:
  redisdata:
```

### WordPress + MySQL + nginx

```yaml
version: "3.8"

services:
  wordpress:
    image: wordpress:php8.2-fpm
    volumes:
      - wp_data:/var/www/html
    environment:
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: ${WP_DB_PASSWORD}
      WORDPRESS_DB_NAME: wordpress
    depends_on:
      db:
        condition: service_healthy
    restart: unless-stopped

  db:
    image: mysql:8.0
    volumes:
      - db_data:/var/lib/mysql
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_ROOT_PASSWORD}
      MYSQL_DATABASE: wordpress
      MYSQL_USER: wordpress
      MYSQL_PASSWORD: ${WP_DB_PASSWORD}
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf
      - wp_data:/var/www/html
      - certs:/etc/letsencrypt
    depends_on:
      - wordpress
    restart: unless-stopped

volumes:
  wp_data:
  db_data:
  certs:
```

## Container Networking

```bash
# Create a custom network
docker network create myapp-net

# Connect containers
docker network connect myapp-net container1
docker network connect myapp-net container2

# Inspect network
docker network inspect myapp-net
```

## Deployment Workflow

```bash
# Build and push
docker build -t myapp:latest .
docker tag myapp:latest registry.example.com/myapp:v1.2.3
docker push registry.example.com/myapp:v1.2.3

# Deploy with Compose
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f app

# Rolling update
docker compose up -d --no-deps --build app

# Rollback
docker compose down
docker tag registry.example.com/myapp:v1.2.2 myapp:latest
docker compose up -d
```

## Monitoring & Logs

```bash
docker compose logs -f --tail=100 SERVICE   # Follow logs
docker stats                                  # Resource usage
docker system df                              # Disk usage
docker system prune -af                       # Clean up (DESTRUCTIVE)
```

## Image Registry

```bash
# Docker Hub
docker login
docker push username/myapp:latest

# GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
docker tag myapp ghcr.io/USERNAME/myapp:latest
docker push ghcr.io/USERNAME/myapp:latest
```

## Security

- Always use specific version tags, never `latest` in production
- Run containers as non-root users (`USER` in Dockerfile)
- Use multi-stage builds to minimize image size and attack surface
- Scan images for vulnerabilities: `docker scout cves myapp:latest`
- Never store secrets in images — use environment variables or Docker secrets
- Use `--no-new-privileges` security option
- Set resource limits: `mem_limit`, `cpus` in compose

## Guidelines

- Use `.dockerignore` to exclude unnecessary files (node_modules, .git, etc.)
- Pin base image versions (e.g., `node:20.11-alpine` not `node:latest`)
- One process per container
- Use health checks for all services
- Store persistent data in named volumes, never in containers
- Use `docker compose` (v2) instead of `docker-compose` (v1)
