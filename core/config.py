"""
Centralized configuration loaded from environment variables.

All settings are validated at import time so failures surface early.
"""

import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("agent42.config")

# Known-insecure JWT secrets that must never be used in production
_INSECURE_JWT_SECRETS = {
    "change-me-to-a-long-random-string",
    "change-me-to-a-long-random-string-at-least-32-chars",
    "",
}


@dataclass(frozen=True)
class Settings:
    """Immutable application settings derived from environment variables."""

    # API keys — providers (Phase 5)
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
    jwt_secret: str = ""
    dashboard_host: str = "127.0.0.1"
    cors_allowed_origins: str = ""  # Comma-separated origins, empty = same-origin only

    # Orchestrator
    default_repo_path: str = "."
    max_concurrent_agents: int = 3
    tasks_json_path: str = "tasks.json"

    # Security (Phase 1)
    sandbox_enabled: bool = True
    workspace_restrict: bool = True

    # Rate limiting
    login_rate_limit: int = 5  # Max login attempts per minute per IP
    max_websocket_connections: int = 50

    # Spending limits
    max_daily_api_spend_usd: float = 0.0  # 0 = unlimited

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

    # Non-code outputs (Phase 8)
    outputs_dir: str = ".agent42/outputs"
    templates_dir: str = ".agent42/templates"

    # Media generation (Phase 9)
    replicate_api_token: str = ""
    luma_api_key: str = ""
    images_dir: str = ".agent42/images"

    @classmethod
    def from_env(cls) -> "Settings":
        # Enforce secure JWT secret
        jwt_secret = os.getenv("JWT_SECRET", "")
        if jwt_secret in _INSECURE_JWT_SECRETS:
            jwt_secret = secrets.token_hex(32)
            logger.warning(
                "JWT_SECRET not set or insecure — generated a random secret. "
                "Set JWT_SECRET in .env for persistent sessions across restarts."
            )

        return cls(
            # Provider API keys
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
            jwt_secret=jwt_secret,
            dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
            cors_allowed_origins=os.getenv("CORS_ALLOWED_ORIGINS", ""),
            # Orchestrator
            default_repo_path=os.getenv("DEFAULT_REPO_PATH", str(Path.cwd())),
            max_concurrent_agents=int(os.getenv("MAX_CONCURRENT_AGENTS", "3")),
            tasks_json_path=os.getenv("TASKS_JSON_PATH", "tasks.json"),
            # Security
            sandbox_enabled=os.getenv("SANDBOX_ENABLED", "true").lower() in ("true", "1", "yes"),
            workspace_restrict=os.getenv("WORKSPACE_RESTRICT", "true").lower() in ("true", "1", "yes"),
            login_rate_limit=int(os.getenv("LOGIN_RATE_LIMIT", "5")),
            max_websocket_connections=int(os.getenv("MAX_WEBSOCKET_CONNECTIONS", "50")),
            max_daily_api_spend_usd=float(os.getenv("MAX_DAILY_API_SPEND_USD", "0")),
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
            # Non-code outputs
            outputs_dir=os.getenv("OUTPUTS_DIR", ".agent42/outputs"),
            templates_dir=os.getenv("TEMPLATES_DIR", ".agent42/templates"),
            # Media generation
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN", ""),
            luma_api_key=os.getenv("LUMA_API_KEY", ""),
            images_dir=os.getenv("IMAGES_DIR", ".agent42/images"),
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

    def get_cors_origins(self) -> list[str]:
        """Parse comma-separated CORS allowed origins."""
        if not self.cors_allowed_origins:
            return []
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    def validate_dashboard_auth(self) -> list[str]:
        """Validate dashboard auth configuration. Returns list of warnings."""
        warnings = []
        if not self.dashboard_password and not self.dashboard_password_hash:
            warnings.append(
                "No dashboard password configured (DASHBOARD_PASSWORD or "
                "DASHBOARD_PASSWORD_HASH). Dashboard login will be disabled."
            )
        if self.dashboard_password and not self.dashboard_password_hash:
            warnings.append(
                "Using plaintext DASHBOARD_PASSWORD. Set DASHBOARD_PASSWORD_HASH "
                "for production. Generate: python -c \"from passlib.context import "
                "CryptContext; print(CryptContext(['bcrypt']).hash('yourpassword'))\""
            )
        return warnings


# Singleton — import this everywhere
settings = Settings.from_env()
