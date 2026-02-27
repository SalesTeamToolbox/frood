"""
Diagnostic: check which OpenRouter API key Agent42 will use, then test it.

Run from the agent42 directory:
    python scripts/check_openrouter_key.py

Or on the production server as the deploy user:
    cd ~/agent42
    python scripts/check_openrouter_key.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# --- 1. Load .env (same as agent42.py does at startup) ----------------------
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path, override=True)
    print(f"[dotenv] .env file: {'found' if env_path.exists() else 'NOT found'}")
except ImportError:
    print("[dotenv] python-dotenv not installed — skipping .env load")

# --- 2. Check settings.json (KeyStore) ----------------------------------------
settings_path = Path(__file__).parent.parent / ".agent42" / "settings.json"
print(f"\n[KeyStore] settings.json: {'found' if settings_path.exists() else 'NOT found'}")
if settings_path.exists():
    try:
        data = json.loads(settings_path.read_text())
        admin_key = data.get("api_keys", {}).get("OPENROUTER_API_KEY", "")
        if admin_key:
            masked = admin_key[:8] + "..." + admin_key[-6:] if len(admin_key) > 14 else "****"
            print(f"[KeyStore] OPENROUTER_API_KEY in settings.json: {masked}")
            # Inject into environ (same as inject_into_environ)
            os.environ["OPENROUTER_API_KEY"] = admin_key
            print("[KeyStore] Injected into os.environ")
        else:
            print("[KeyStore] OPENROUTER_API_KEY not in settings.json")
    except Exception as e:
        print(f"[KeyStore] Error reading: {e}")

# --- 3. What os.environ has now -----------------------------------------------
env_key = os.environ.get("OPENROUTER_API_KEY", "")
if env_key:
    masked = env_key[:8] + "..." + env_key[-6:] if len(env_key) > 14 else "****"
    print(f"\n[os.environ] OPENROUTER_API_KEY = {masked}")
else:
    print("\n[os.environ] OPENROUTER_API_KEY is NOT SET — agent will fail with ValueError")
    sys.exit(1)

# --- 4. Test the key against OpenRouter ---------------------------------------
print("\n[test] Testing key against OpenRouter /models endpoint...")
try:
    import httpx

    async def test_key():
        url = "https://openrouter.ai/api/v1/models"
        headers = {"Authorization": f"Bearer {env_key}"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200:
            models = resp.json().get("data", [])
            print(f"[test] SUCCESS — key is valid, {len(models)} models available")
        elif resp.status_code == 401:
            print(f"[test] FAIL 401 — OpenRouter says: {resp.text[:300]}")
            print("\n>>> The key itself is the problem. Regenerate it on OpenRouter:")
            print("    https://openrouter.ai/settings/keys")
        else:
            print(f"[test] HTTP {resp.status_code}: {resp.text[:300]}")

    asyncio.run(test_key())
except ImportError:
    print("[test] httpx not installed — testing with urllib instead")
    import urllib.request, urllib.error

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/models",
        headers={"Authorization": f"Bearer {env_key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
            print(f"[test] SUCCESS — {len(data.get('data', []))} models")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        print(f"[test] FAIL HTTP {e.code}: {body}")
        if e.code == 401:
            print("\n>>> The key itself is the problem. Regenerate it on OpenRouter:")
            print("    https://openrouter.ai/settings/keys")
