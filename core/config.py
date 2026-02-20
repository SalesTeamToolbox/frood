"""
Centralized configuration loaded from environment variables.

All settings are validated at import time so failures surface early.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Immutable application settings derived from environment variables."""

    # API keys
    nvidia_api_key: str = ""
    groq_api_key: str = ""

    # Dashboard auth
    dashboard_username: str = "admin"
    dashboard_password: str = ""
    dashboard_password_hash: str = ""
    jwt_secret: str = "change-me-to-a-long-random-string"

    # Orchestrator
    default_repo_path: str = "."
    max_concurrent_agents: int = 3
    tasks_json_path: str = "tasks.json"

    # Model endpoints
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            nvidia_api_key=os.getenv("NVIDIA_API_KEY", ""),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            dashboard_username=os.getenv("DASHBOARD_USERNAME", "admin"),
            dashboard_password=os.getenv("DASHBOARD_PASSWORD", ""),
            dashboard_password_hash=os.getenv("DASHBOARD_PASSWORD_HASH", ""),
            jwt_secret=os.getenv(
                "JWT_SECRET", "change-me-to-a-long-random-string"
            ),
            default_repo_path=os.getenv("DEFAULT_REPO_PATH", str(Path.cwd())),
            max_concurrent_agents=int(os.getenv("MAX_CONCURRENT_AGENTS", "3")),
            tasks_json_path=os.getenv("TASKS_JSON_PATH", "tasks.json"),
            nvidia_base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ),
            groq_base_url=os.getenv(
                "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
            ),
        )


# Singleton — import this everywhere
settings = Settings.from_env()
