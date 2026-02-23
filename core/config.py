"""
Centralized configuration loaded from environment variables.

All settings are validated at import time so failures surface early.
"""

import json
import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("agent42.config")


def _resolve_repo_path(raw: str) -> str | None:
    """Return the repo path if it exists and is a git repo, else None."""
    if not raw or not raw.strip():
        return None
    p = Path(raw).resolve()
    if p.exists() and (p / ".git").exists():
        return str(p)
    logger.info(
        "DEFAULT_REPO_PATH=%s is not a valid git repo — configure repos via the dashboard.",
        raw,
    )
    return None


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
    default_repo_path: str | None = None
    max_concurrent_agents: int = 3
    tasks_json_path: str = "tasks.json"

    # Security (Phase 1)
    sandbox_enabled: bool = True
    workspace_restrict: bool = True

    # Command filter: "deny" (default deny-list) or "allowlist" (strict production mode)
    command_filter_mode: str = "deny"
    command_filter_allowlist: str = ""  # Comma-separated regex patterns (allowlist mode)

    # Approval gate
    approval_log_path: str = ".agent42/approvals.jsonl"

    # Rate limiting
    login_rate_limit: int = 5  # Max login attempts per minute per IP
    max_websocket_connections: int = 50
    tool_rate_limiting_enabled: bool = True
    tool_rate_limit_overrides: str = (
        ""  # JSON: {"shell": {"max_calls": 500, "window_seconds": 3600}}
    )

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

    # URL policy (OpenClaw security fix)
    url_allowlist: str = ""  # Comma-separated glob patterns, e.g. "*.github.com,api.openai.com"
    url_denylist: str = ""  # Comma-separated glob patterns to always block
    max_url_requests_per_agent: int = 100  # 0 = unlimited

    # Browser control security (OpenClaw CVE fix)
    browser_gateway_token: str = ""  # Auto-generated if empty

    # Context safeguards (OpenClaw feature)
    max_context_tokens: int = 128000
    context_overflow_strategy: str = "truncate_oldest"  # truncate_oldest | summarize | error

    # Webhook notifications (OpenClaw feature)
    webhook_urls: str = ""  # Comma-separated webhook endpoints
    webhook_events: str = "task_failed,task_review,approval_requested,agent_stalled"
    notification_email_recipients: str = ""  # Comma-separated emails for critical alerts

    # Tools (Phase 4)
    brave_api_key: str = ""
    mcp_servers_json: str = ""  # Path to MCP servers config file
    cron_jobs_path: str = "cron_jobs.json"
    custom_tools_dir: str = ""  # Path to directory with custom Tool .py files

    # Dynamic model routing
    model_routing_file: str = "data/dynamic_routing.json"
    model_catalog_refresh_hours: float = 24.0  # How often to sync OpenRouter catalog
    model_trial_percentage: int = 10  # % of tasks to assign unproven models (0-100)
    model_min_trials: int = 5  # Min task completions before model gets ranked
    model_research_enabled: bool = True  # Enable web benchmark research
    model_research_interval_hours: float = 168.0  # How often to research benchmarks (168h = weekly)

    # Memory (Phase 6)
    memory_dir: str = ".agent42/memory"
    sessions_dir: str = ".agent42/sessions"

    # Qdrant vector database (optional — enhances semantic search)
    qdrant_url: str = ""  # e.g. "http://localhost:6333" for Docker, or empty for embedded
    qdrant_api_key: str = ""  # API key for Qdrant Cloud or authenticated instances
    qdrant_collection_prefix: str = "agent42"  # Prefix for collection names
    qdrant_enabled: bool = False  # Set true to enable Qdrant (auto-enabled if qdrant_url is set)
    qdrant_local_path: str = ".agent42/qdrant"  # Path for embedded Qdrant storage

    # Redis (optional — fast session cache + embedding cache)
    redis_url: str = ""  # e.g. "redis://localhost:6379/0"
    redis_password: str = ""
    session_ttl_days: int = 7  # TTL for session data in Redis
    embedding_cache_ttl_hours: int = 24  # TTL for cached embeddings in Redis

    # Non-code outputs (Phase 8)
    outputs_dir: str = ".agent42/outputs"
    templates_dir: str = ".agent42/templates"

    # Media generation (Phase 9)
    replicate_api_token: str = ""
    luma_api_key: str = ""
    images_dir: str = ".agent42/images"

    # Device gateway auth (Phase 10)
    devices_file: str = ".agent42/devices.jsonl"

    # SSH remote shell
    ssh_enabled: bool = False
    ssh_allowed_hosts: str = (
        ""  # Comma-separated host patterns (e.g., "*.mycompany.com,192.168.1.*")
    )
    ssh_default_key_path: str = ""  # Path to default SSH private key
    ssh_max_upload_mb: int = 50  # Max file transfer size in MB
    ssh_command_timeout: int = 120  # Per-command timeout in seconds

    # Tunnel manager
    tunnel_enabled: bool = False
    tunnel_provider: str = "auto"  # auto|cloudflared|serveo|localhost.run
    tunnel_allowed_ports: str = ""  # Comma-separated ports (e.g., "8000,3000,80,443")
    tunnel_ttl_minutes: int = 60  # Auto-shutdown tunnels after this duration

    # Knowledge base / RAG
    knowledge_dir: str = ".agent42/knowledge"
    knowledge_chunk_size: int = 500  # Tokens per chunk
    knowledge_chunk_overlap: int = 50  # Overlap tokens between chunks
    knowledge_max_results: int = 10  # Max results per query

    # Vision / image analysis
    vision_max_image_mb: int = 10
    vision_model: str = ""  # Override model for vision tasks (empty = auto-detect)

    # Apps platform
    apps_enabled: bool = True
    apps_dir: str = "apps"
    apps_port_range_start: int = 9100
    apps_port_range_end: int = 9199
    apps_max_running: int = 5
    apps_auto_restart: bool = True
    apps_default_runtime: str = "python"
    apps_git_enabled_default: bool = False  # Default git_enabled for new apps
    apps_github_token: str = ""  # GitHub PAT for repo creation and push

    # Security scanning (scheduled)
    security_scan_enabled: bool = True
    security_scan_interval: str = "8h"  # e.g. "8h", "6h", "12h"
    security_scan_min_severity: str = "medium"  # low, medium, high, critical
    security_scan_github_issues: bool = True

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

        # Auto-generate browser gateway token if not set
        browser_gateway_token = os.getenv("BROWSER_GATEWAY_TOKEN", "")
        if not browser_gateway_token:
            browser_gateway_token = secrets.token_hex(16)
            logger.warning(
                "BROWSER_GATEWAY_TOKEN not set — generated a random token. "
                "Set BROWSER_GATEWAY_TOKEN in .env for persistent browser sessions."
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
            default_repo_path=_resolve_repo_path(os.getenv("DEFAULT_REPO_PATH", "")),
            max_concurrent_agents=int(os.getenv("MAX_CONCURRENT_AGENTS", "3")),
            tasks_json_path=os.getenv("TASKS_JSON_PATH", "tasks.json"),
            # Security
            sandbox_enabled=os.getenv("SANDBOX_ENABLED", "true").lower() in ("true", "1", "yes"),
            workspace_restrict=os.getenv("WORKSPACE_RESTRICT", "true").lower()
            in ("true", "1", "yes"),
            command_filter_mode=os.getenv("COMMAND_FILTER_MODE", "deny"),
            command_filter_allowlist=os.getenv("COMMAND_FILTER_ALLOWLIST", ""),
            approval_log_path=os.getenv("APPROVAL_LOG_PATH", ".agent42/approvals.jsonl"),
            login_rate_limit=int(os.getenv("LOGIN_RATE_LIMIT", "5")),
            max_websocket_connections=int(os.getenv("MAX_WEBSOCKET_CONNECTIONS", "50")),
            tool_rate_limiting_enabled=os.getenv("TOOL_RATE_LIMITING_ENABLED", "true").lower()
            in ("true", "1", "yes"),
            tool_rate_limit_overrides=os.getenv("TOOL_RATE_LIMIT_OVERRIDES", ""),
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
            # URL policy
            url_allowlist=os.getenv("URL_ALLOWLIST", ""),
            url_denylist=os.getenv("URL_DENYLIST", ""),
            max_url_requests_per_agent=int(os.getenv("MAX_URL_REQUESTS_PER_AGENT", "100")),
            # Browser control security
            browser_gateway_token=browser_gateway_token,
            # Context safeguards
            max_context_tokens=int(os.getenv("MAX_CONTEXT_TOKENS", "128000")),
            context_overflow_strategy=os.getenv("CONTEXT_OVERFLOW_STRATEGY", "truncate_oldest"),
            # Webhook notifications
            webhook_urls=os.getenv("WEBHOOK_URLS", ""),
            webhook_events=os.getenv(
                "WEBHOOK_EVENTS", "task_failed,task_review,approval_requested,agent_stalled"
            ),
            notification_email_recipients=os.getenv("NOTIFICATION_EMAIL_RECIPIENTS", ""),
            # Skills
            skills_dirs=os.getenv("SKILLS_DIRS", ""),
            # Tools
            brave_api_key=os.getenv("BRAVE_API_KEY", ""),
            mcp_servers_json=os.getenv("MCP_SERVERS_JSON", ""),
            cron_jobs_path=os.getenv("CRON_JOBS_PATH", "cron_jobs.json"),
            custom_tools_dir=os.getenv("CUSTOM_TOOLS_DIR", ""),
            # Dynamic model routing
            model_routing_file=os.getenv("MODEL_ROUTING_FILE", "data/dynamic_routing.json"),
            model_catalog_refresh_hours=float(os.getenv("MODEL_CATALOG_REFRESH_HOURS", "24")),
            model_trial_percentage=int(os.getenv("MODEL_TRIAL_PERCENTAGE", "10")),
            model_min_trials=int(os.getenv("MODEL_MIN_TRIALS", "5")),
            model_research_enabled=os.getenv("MODEL_RESEARCH_ENABLED", "true").lower()
            in ("true", "1", "yes"),
            model_research_interval_hours=float(os.getenv("MODEL_RESEARCH_INTERVAL_HOURS", "168")),
            # Memory
            memory_dir=os.getenv("MEMORY_DIR", ".agent42/memory"),
            sessions_dir=os.getenv("SESSIONS_DIR", ".agent42/sessions"),
            # Qdrant
            qdrant_url=os.getenv("QDRANT_URL", ""),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            qdrant_collection_prefix=os.getenv("QDRANT_COLLECTION_PREFIX", "agent42"),
            qdrant_enabled=os.getenv("QDRANT_ENABLED", "").lower() in ("true", "1", "yes")
            or bool(os.getenv("QDRANT_URL", "")),
            qdrant_local_path=os.getenv("QDRANT_LOCAL_PATH", ".agent42/qdrant"),
            # Redis
            redis_url=os.getenv("REDIS_URL", ""),
            redis_password=os.getenv("REDIS_PASSWORD", ""),
            session_ttl_days=int(os.getenv("SESSION_TTL_DAYS", "7")),
            embedding_cache_ttl_hours=int(os.getenv("EMBEDDING_CACHE_TTL_HOURS", "24")),
            # Non-code outputs
            outputs_dir=os.getenv("OUTPUTS_DIR", ".agent42/outputs"),
            templates_dir=os.getenv("TEMPLATES_DIR", ".agent42/templates"),
            # Media generation
            replicate_api_token=os.getenv("REPLICATE_API_TOKEN", ""),
            luma_api_key=os.getenv("LUMA_API_KEY", ""),
            images_dir=os.getenv("IMAGES_DIR", ".agent42/images"),
            # Device gateway auth
            devices_file=os.getenv("DEVICES_FILE", ".agent42/devices.jsonl"),
            # Security scanning
            security_scan_enabled=os.getenv("SECURITY_SCAN_ENABLED", "true").lower()
            in ("true", "1", "yes"),
            security_scan_interval=os.getenv("SECURITY_SCAN_INTERVAL", "8h"),
            security_scan_min_severity=os.getenv("SECURITY_SCAN_MIN_SEVERITY", "medium"),
            security_scan_github_issues=os.getenv("SECURITY_SCAN_GITHUB_ISSUES", "true").lower()
            in ("true", "1", "yes"),
            # SSH remote shell
            ssh_enabled=os.getenv("SSH_ENABLED", "false").lower() in ("true", "1", "yes"),
            ssh_allowed_hosts=os.getenv("SSH_ALLOWED_HOSTS", ""),
            ssh_default_key_path=os.getenv("SSH_DEFAULT_KEY_PATH", ""),
            ssh_max_upload_mb=int(os.getenv("SSH_MAX_UPLOAD_MB", "50")),
            ssh_command_timeout=int(os.getenv("SSH_COMMAND_TIMEOUT", "120")),
            # Tunnel manager
            tunnel_enabled=os.getenv("TUNNEL_ENABLED", "false").lower() in ("true", "1", "yes"),
            tunnel_provider=os.getenv("TUNNEL_PROVIDER", "auto"),
            tunnel_allowed_ports=os.getenv("TUNNEL_ALLOWED_PORTS", ""),
            tunnel_ttl_minutes=int(os.getenv("TUNNEL_TTL_MINUTES", "60")),
            # Knowledge base / RAG
            knowledge_dir=os.getenv("KNOWLEDGE_DIR", ".agent42/knowledge"),
            knowledge_chunk_size=int(os.getenv("KNOWLEDGE_CHUNK_SIZE", "500")),
            knowledge_chunk_overlap=int(os.getenv("KNOWLEDGE_CHUNK_OVERLAP", "50")),
            knowledge_max_results=int(os.getenv("KNOWLEDGE_MAX_RESULTS", "10")),
            # Vision / image analysis
            vision_max_image_mb=int(os.getenv("VISION_MAX_IMAGE_MB", "10")),
            vision_model=os.getenv("VISION_MODEL", ""),
            # Apps platform
            apps_enabled=os.getenv("APPS_ENABLED", "true").lower() in ("true", "1", "yes"),
            apps_dir=os.getenv("APPS_DIR", "apps"),
            apps_port_range_start=int(os.getenv("APPS_PORT_RANGE_START", "9100")),
            apps_port_range_end=int(os.getenv("APPS_PORT_RANGE_END", "9199")),
            apps_max_running=int(os.getenv("APPS_MAX_RUNNING", "5")),
            apps_auto_restart=os.getenv("APPS_AUTO_RESTART", "true").lower()
            in ("true", "1", "yes"),
            apps_default_runtime=os.getenv("APPS_DEFAULT_RUNTIME", "python"),
            apps_git_enabled_default=os.getenv("APPS_GIT_ENABLED_DEFAULT", "false").lower()
            in ("true", "1", "yes"),
            apps_github_token=os.getenv("APPS_GITHUB_TOKEN", ""),
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

    def get_url_allowlist(self) -> list[str]:
        """Parse comma-separated URL allowlist patterns."""
        if not self.url_allowlist:
            return []
        return [p.strip() for p in self.url_allowlist.split(",") if p.strip()]

    def get_url_denylist(self) -> list[str]:
        """Parse comma-separated URL denylist patterns."""
        if not self.url_denylist:
            return []
        return [p.strip() for p in self.url_denylist.split(",") if p.strip()]

    def get_webhook_urls(self) -> list[str]:
        """Parse comma-separated webhook URLs."""
        if not self.webhook_urls:
            return []
        return [u.strip() for u in self.webhook_urls.split(",") if u.strip()]

    def get_webhook_events(self) -> list[str]:
        """Parse comma-separated webhook event types."""
        if not self.webhook_events:
            return []
        return [e.strip() for e in self.webhook_events.split(",") if e.strip()]

    def get_notification_email_recipients(self) -> list[str]:
        """Parse comma-separated email recipients."""
        if not self.notification_email_recipients:
            return []
        return [e.strip() for e in self.notification_email_recipients.split(",") if e.strip()]

    def get_ssh_allowed_hosts(self) -> list[str]:
        """Parse comma-separated SSH allowed host patterns."""
        if not self.ssh_allowed_hosts:
            return []
        return [h.strip() for h in self.ssh_allowed_hosts.split(",") if h.strip()]

    def get_tunnel_allowed_ports(self) -> list[int]:
        """Parse comma-separated tunnel allowed ports."""
        if not self.tunnel_allowed_ports:
            return []
        return [int(p.strip()) for p in self.tunnel_allowed_ports.split(",") if p.strip()]

    def get_security_scan_interval_seconds(self) -> float:
        """Parse security scan interval string to seconds (e.g. '8h' -> 28800)."""
        s = self.security_scan_interval.strip().lower()
        try:
            if s.endswith("h"):
                return float(s[:-1]) * 3600
            elif s.endswith("m"):
                return float(s[:-1]) * 60
            elif s.endswith("d"):
                return float(s[:-1]) * 86400
            elif s.endswith("s"):
                return float(s[:-1])
            return float(s)
        except ValueError:
            return 28800.0  # Default: 8 hours

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
                'for production. Generate: python -c "from passlib.context import '
                "CryptContext; print(CryptContext(['bcrypt']).hash('yourpassword'))\""
            )
        # Diagnostic info (never log the actual password)
        if self.dashboard_password:
            pw = self.dashboard_password
            masked = pw[0] + "*" * (len(pw) - 2) + pw[-1] if len(pw) > 2 else "***"
            warnings.append(
                f"Auth config: username='{self.dashboard_username}', "
                f"password={masked} (len={len(pw)}), hash={'set' if self.dashboard_password_hash else 'not set'}"
            )
        elif self.dashboard_password_hash:
            warnings.append(
                f"Auth config: username='{self.dashboard_username}', "
                f"password=not set, hash=set (bcrypt)"
            )
        return warnings

    @classmethod
    def reload_from_env(cls) -> None:
        """Hot-reload the global settings singleton from environment variables.

        Uses object.__setattr__ to update the frozen dataclass in-place,
        ensuring all modules that imported ``settings`` by name see the
        new values without needing to re-import.
        """
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).parent.parent / ".env", override=True)
        new = cls.from_env()
        for field_name in cls.__dataclass_fields__:
            object.__setattr__(settings, field_name, getattr(new, field_name))


# Singleton — import this everywhere
settings = Settings.from_env()
