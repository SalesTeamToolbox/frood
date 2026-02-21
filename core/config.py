"""
Centralized configuration loaded from environment variables.

All settings are validated at import time so failures surface early.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Immutable application settings derived from environment variables."""

    # API keys — providers (Phase 5)
    nvidia_api_key: str = ""
    groq_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    deepseek_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    vllm_api_key: str = ""

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

    # Security (Phase 1)
    sandbox_enabled: bool = True
    workspace_restrict: bool = True

    # Channels (Phase 2)
    discord_bot_token: str = ""
    discord_guild_ids: str = ""  # Comma-separated guild IDs
    slack_bot_token: str = ""
    slack_app_token: str = ""
    telegram_bot_token: str = ""
    email_imap_host: str = ""
    email_imap_port: int = 993
    email_imap_user: str = ""
    email_imap_password: str = ""
    email_smtp_host: str = ""
    email_smtp_port: int = 587
    email_smtp_user: str = ""
    email_smtp_password: str = ""

    # Skills (Phase 3)
    skills_dirs: str = ""  # Comma-separated extra skill directories

    # Tools (Phase 4)
    brave_api_key: str = ""
    mcp_servers_json: str = ""  # Path to MCP servers config file
    cron_jobs_path: str = "cron_jobs.json"

    # Memory (Phase 6)
    memory_dir: str = ".agent42/memory"
    sessions_dir: str = ".agent42/sessions"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            # Provider API keys
            nvidia_api_key=os.getenv("NVIDIA_API_KEY", ""),
            groq_api_key=os.getenv("GROQ_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            vllm_api_key=os.getenv("VLLM_API_KEY", ""),
            # Dashboard
            dashboard_username=os.getenv("DASHBOARD_USERNAME", "admin"),
            dashboard_password=os.getenv("DASHBOARD_PASSWORD", ""),
            dashboard_password_hash=os.getenv("DASHBOARD_PASSWORD_HASH", ""),
            jwt_secret=os.getenv("JWT_SECRET", "change-me-to-a-long-random-string"),
            # Orchestrator
            default_repo_path=os.getenv("DEFAULT_REPO_PATH", str(Path.cwd())),
            max_concurrent_agents=int(os.getenv("MAX_CONCURRENT_AGENTS", "3")),
            tasks_json_path=os.getenv("TASKS_JSON_PATH", "tasks.json"),
            # Endpoints
            nvidia_base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            groq_base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            # Security
            sandbox_enabled=os.getenv("SANDBOX_ENABLED", "true").lower() in ("true", "1", "yes"),
            workspace_restrict=os.getenv("WORKSPACE_RESTRICT", "true").lower() in ("true", "1", "yes"),
            # Channels
            discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", ""),
            discord_guild_ids=os.getenv("DISCORD_GUILD_IDS", ""),
            slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
            slack_app_token=os.getenv("SLACK_APP_TOKEN", ""),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            email_imap_host=os.getenv("EMAIL_IMAP_HOST", ""),
            email_imap_port=int(os.getenv("EMAIL_IMAP_PORT", "993")),
            email_imap_user=os.getenv("EMAIL_IMAP_USER", ""),
            email_imap_password=os.getenv("EMAIL_IMAP_PASSWORD", ""),
            email_smtp_host=os.getenv("EMAIL_SMTP_HOST", ""),
            email_smtp_port=int(os.getenv("EMAIL_SMTP_PORT", "587")),
            email_smtp_user=os.getenv("EMAIL_SMTP_USER", ""),
            email_smtp_password=os.getenv("EMAIL_SMTP_PASSWORD", ""),
            # Skills
            skills_dirs=os.getenv("SKILLS_DIRS", ""),
            # Tools
            brave_api_key=os.getenv("BRAVE_API_KEY", ""),
            mcp_servers_json=os.getenv("MCP_SERVERS_JSON", ""),
            cron_jobs_path=os.getenv("CRON_JOBS_PATH", "cron_jobs.json"),
            # Memory
            memory_dir=os.getenv("MEMORY_DIR", ".agent42/memory"),
            sessions_dir=os.getenv("SESSIONS_DIR", ".agent42/sessions"),
        )

    def get_discord_guild_ids(self) -> list[int]:
        """Parse comma-separated guild IDs."""
        if not self.discord_guild_ids:
            return []
        return [int(g.strip()) for g in self.discord_guild_ids.split(",") if g.strip()]

    def get_skills_dirs(self) -> list[str]:
        """Parse comma-separated extra skill directories."""
        if not self.skills_dirs:
            return []
        return [d.strip() for d in self.skills_dirs.split(",") if d.strip()]

    def get_mcp_servers(self) -> dict:
        """Load MCP server configurations from JSON file."""
        if not self.mcp_servers_json:
            return {}
        path = Path(self.mcp_servers_json)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}


# Singleton — import this everywhere
settings = Settings.from_env()
