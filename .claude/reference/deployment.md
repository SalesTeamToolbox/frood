# Deployment

## Development (Local)

```bash
git clone <repo> agent42 && cd agent42
bash setup.sh                    # Creates .venv, installs deps, builds frontend
source .venv/bin/activate
python agent42.py                # http://localhost:8000
# Open browser — setup wizard handles password, API key, and memory
```

## Production (Server)

```bash
scp -r agent42/ user@server:~/agent42
ssh user@server
cd ~/agent42
bash deploy/install-server.sh    # Prompts for domain, installs Redis + Qdrant + nginx + SSL + systemd
# Open https://yourdomain.com — setup wizard handles password and API key
```

The install script handles: setup.sh, Redis (apt), Qdrant (binary + systemd),
nginx reverse proxy (templated), Let's Encrypt SSL, Agent42 systemd service,
UFW firewall. Redis and Qdrant URLs are pre-configured in .env.

**Service commands:**
```bash
sudo systemctl start agent42     # Start
sudo systemctl restart agent42   # Restart
sudo systemctl status agent42    # Status
sudo journalctl -u agent42 -f   # Live logs
```

## Docker (Development Stack)

```bash
cp .env.example .env && nano .env
docker compose up -d             # Agent42 + Redis + Qdrant
docker compose logs -f agent42   # Logs
docker compose down              # Stop
```
