# Deployment

## Development (Local)

```bash
git clone <repo> frood && cd frood
bash setup.sh                    # Creates .venv, installs deps, builds frontend
source .venv/bin/activate
python frood.py                # http://localhost:8000
# Open browser — setup wizard handles password, API key, and memory
```

## Production (Server)

```bash
scp -r frood/ user@server:~/frood
ssh user@server
cd ~/frood
bash deploy/install-server.sh    # Prompts for domain, installs Redis + Qdrant + nginx + SSL + systemd
# Open https://yourdomain.com — setup wizard handles password and API key
```

The install script handles: setup.sh, Redis (apt), Qdrant (binary + systemd),
nginx reverse proxy (templated), Let's Encrypt SSL, Frood systemd service,
UFW firewall. Redis and Qdrant URLs are pre-configured in .env.

**Service commands:**
```bash
sudo systemctl start frood     # Start
sudo systemctl restart frood   # Restart
sudo systemctl status frood    # Status
sudo journalctl -u frood -f   # Live logs
```

## Docker (Development Stack)

```bash
cp .env.example .env && nano .env
docker compose up -d             # Frood + Redis + Qdrant
docker compose logs -f frood   # Logs
docker compose down              # Stop
```
