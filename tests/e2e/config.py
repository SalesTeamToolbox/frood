"""
E2E test configuration for Agent42 playwright-cli tests.

Reads from environment or .env file, with sensible defaults.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

AGENT42_ROOT = Path(__file__).resolve().parents[2]

# Load .env from agent42 root if present
_env_file = AGENT42_ROOT / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)
    except ImportError:
        # Manual .env loading as fallback
        with open(_env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key and key not in os.environ:
                        os.environ[key] = val


@dataclass
class E2EConfig:
    base_url: str = ""
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    session_name: str = "agent42-e2e"
    headed: bool = False
    output_dir: str = ""
    # Auto-discovery paths
    agent42_root: Path = field(default_factory=lambda: AGENT42_ROOT)

    def __post_init__(self):
        self.host = self.host or os.getenv("DASHBOARD_HOST", "127.0.0.1")
        self.port = self.port or int(os.getenv("DASHBOARD_PORT", "8000"))
        self.base_url = self.base_url or f"http://{self.host}:{self.port}"
        self.username = self.username or os.getenv("DASHBOARD_USERNAME", "admin")
        self.password = self.password or os.getenv("E2E_PASSWORD", "") or os.getenv("DASHBOARD_PASSWORD", "")
        self.output_dir = self.output_dir or str(
            AGENT42_ROOT / ".agent42" / "e2e-results"
        )
        os.makedirs(self.output_dir, exist_ok=True)


config = E2EConfig()
