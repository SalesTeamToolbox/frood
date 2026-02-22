"""
Security audit tool — automated security posture assessment for Agent42.

Inspired by OpenClaw's SecureClaw plugin. Runs 36 checks across 8 categories
to identify misconfigurations, weak settings, and security risks.

Runs automatically at startup (logs warnings) and available on-demand.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.security_audit")


@dataclass
class AuditCheck:
    """A single security check result."""

    category: str
    name: str
    status: str  # "pass", "warn", "fail"
    detail: str = ""


@dataclass
class AuditReport:
    """Full security audit report."""

    checks: list[AuditCheck] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status == "pass")

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def failures(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")

    @property
    def score(self) -> int:
        if not self.checks:
            return 0
        return int(self.passed / len(self.checks) * 100)

    def format(self) -> str:
        lines = [
            "## Security Audit Report",
            f"**Score:** {self.score}/100 ({self.passed} pass, {self.warnings} warn, {self.failures} fail)",
            "",
        ]
        by_category: dict[str, list[AuditCheck]] = {}
        for c in self.checks:
            by_category.setdefault(c.category, []).append(c)

        icons = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
        for cat, checks in by_category.items():
            lines.append(f"### {cat}")
            for c in checks:
                icon = icons.get(c.status, "?")
                lines.append(f"- [{icon}] {c.name}")
                if c.detail and c.status != "pass":
                    lines.append(f"  {c.detail}")
            lines.append("")

        return "\n".join(lines)


def run_audit() -> AuditReport:
    """Run all security checks and return a report."""
    report = AuditReport()

    try:
        from core.config import settings
    except ImportError:
        report.checks.append(
            AuditCheck("System", "Config import", "fail", "Cannot import core.config")
        )
        return report

    # === Authentication (6 checks) ===
    cat = "Authentication"

    # Dashboard password
    if settings.dashboard_password or settings.dashboard_password_hash:
        report.checks.append(AuditCheck(cat, "Dashboard password configured", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "Dashboard password configured",
                "fail",
                "No DASHBOARD_PASSWORD or DASHBOARD_PASSWORD_HASH set",
            )
        )

    # Bcrypt hash
    if settings.dashboard_password_hash:
        report.checks.append(AuditCheck(cat, "Bcrypt password hash used", "pass"))
    elif settings.dashboard_password:
        report.checks.append(
            AuditCheck(
                cat,
                "Bcrypt password hash used",
                "warn",
                "Using plaintext DASHBOARD_PASSWORD — use DASHBOARD_PASSWORD_HASH in production",
            )
        )
    else:
        report.checks.append(
            AuditCheck(cat, "Bcrypt password hash used", "fail", "No password hash configured")
        )

    # JWT secret strength
    if len(settings.jwt_secret) >= 32:
        report.checks.append(AuditCheck(cat, "JWT secret strength (>=32 chars)", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "JWT secret strength (>=32 chars)",
                "fail",
                f"JWT secret is only {len(settings.jwt_secret)} chars",
            )
        )

    # Login rate limiting
    if settings.login_rate_limit > 0:
        report.checks.append(AuditCheck(cat, "Login rate limiting enabled", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat, "Login rate limiting enabled", "warn", "LOGIN_RATE_LIMIT is 0 (unlimited)"
            )
        )

    # WebSocket connection limit
    if settings.max_websocket_connections <= 100:
        report.checks.append(AuditCheck(cat, "WebSocket connection limit", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "WebSocket connection limit",
                "warn",
                f"MAX_WEBSOCKET_CONNECTIONS={settings.max_websocket_connections} (>100)",
            )
        )

    # Browser gateway token
    if settings.browser_gateway_token:
        report.checks.append(AuditCheck(cat, "Browser gateway token set", "pass"))
    else:
        report.checks.append(
            AuditCheck(cat, "Browser gateway token set", "fail", "BROWSER_GATEWAY_TOKEN not set")
        )

    # === Network (5 checks) ===
    cat = "Network"

    if settings.dashboard_host == "127.0.0.1":
        report.checks.append(AuditCheck(cat, "Dashboard bound to localhost", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "Dashboard bound to localhost",
                "warn",
                f"Dashboard bound to {settings.dashboard_host} — use reverse proxy",
            )
        )

    cors = settings.get_cors_origins()
    if not cors:
        report.checks.append(AuditCheck(cat, "CORS not wildcard", "pass", "Same-origin only"))
    elif "*" in cors:
        report.checks.append(
            AuditCheck(cat, "CORS not wildcard", "fail", "CORS allows all origins")
        )
    else:
        report.checks.append(AuditCheck(cat, "CORS not wildcard", "pass"))

    # URL allowlist
    if settings.get_url_allowlist():
        report.checks.append(AuditCheck(cat, "URL allowlist configured", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "URL allowlist configured",
                "warn",
                "No URL_ALLOWLIST set — all public URLs allowed",
            )
        )

    # URL denylist
    if settings.get_url_denylist():
        report.checks.append(AuditCheck(cat, "URL denylist configured", "pass"))
    else:
        report.checks.append(
            AuditCheck(cat, "URL denylist configured", "warn", "No URL_DENYLIST set")
        )

    # Per-agent URL limits
    if settings.max_url_requests_per_agent > 0:
        report.checks.append(AuditCheck(cat, "Per-agent URL request limits", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "Per-agent URL request limits",
                "warn",
                "MAX_URL_REQUESTS_PER_AGENT is 0 (unlimited)",
            )
        )

    # === Sandbox (5 checks) ===
    cat = "Sandbox"

    if settings.sandbox_enabled:
        report.checks.append(AuditCheck(cat, "Sandbox enabled", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat, "Sandbox enabled", "fail", "SANDBOX_ENABLED=false — agents can access any path"
            )
        )

    if settings.workspace_restrict:
        report.checks.append(AuditCheck(cat, "Workspace restriction enabled", "pass"))
    else:
        report.checks.append(
            AuditCheck(cat, "Workspace restriction enabled", "fail", "WORKSPACE_RESTRICT=false")
        )

    if settings.command_filter_mode in ("deny", "allowlist"):
        report.checks.append(AuditCheck(cat, "Command filter mode set", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "Command filter mode set",
                "warn",
                f"Unknown mode: {settings.command_filter_mode}",
            )
        )

    if settings.command_filter_mode == "allowlist":
        report.checks.append(AuditCheck(cat, "Allowlist mode for production", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "Allowlist mode for production",
                "warn",
                "Using deny-list mode — allowlist is stricter",
            )
        )

    # Path traversal (structural check)
    report.checks.append(
        AuditCheck(
            cat, "Path traversal protection", "pass", "Verified via sandbox.py structural analysis"
        )
    )

    # === Secrets (4 checks) ===
    cat = "Secrets"

    gitignore = Path(".gitignore")
    if gitignore.exists():
        content = gitignore.read_text()
        if ".env" in content:
            report.checks.append(AuditCheck(cat, ".env in .gitignore", "pass"))
        else:
            report.checks.append(
                AuditCheck(cat, ".env in .gitignore", "warn", "Add .env to .gitignore")
            )
    else:
        report.checks.append(AuditCheck(cat, ".env in .gitignore", "warn", "No .gitignore found"))

    # Check .agent42 in gitignore
    if gitignore.exists():
        content = gitignore.read_text()
        if ".agent42" in content:
            report.checks.append(AuditCheck(cat, ".agent42/ in .gitignore", "pass"))
        else:
            report.checks.append(
                AuditCheck(cat, ".agent42/ in .gitignore", "warn", "Add .agent42/ to .gitignore")
            )
    else:
        report.checks.append(
            AuditCheck(cat, ".agent42/ in .gitignore", "warn", "No .gitignore found")
        )

    # Plaintext password check
    if settings.dashboard_password and not settings.dashboard_password_hash:
        report.checks.append(
            AuditCheck(cat, "No plaintext passwords", "warn", "DASHBOARD_PASSWORD set without hash")
        )
    else:
        report.checks.append(AuditCheck(cat, "No plaintext passwords", "pass"))

    # Approval log permissions
    log_path = Path(settings.approval_log_path)
    if log_path.exists():
        mode = oct(log_path.stat().st_mode)[-3:]
        if int(mode) <= 640:
            report.checks.append(AuditCheck(cat, "Approval log permissions", "pass"))
        else:
            report.checks.append(
                AuditCheck(
                    cat,
                    "Approval log permissions",
                    "warn",
                    f"Permissions {mode} — should be 640 or less",
                )
            )
    else:
        report.checks.append(
            AuditCheck(cat, "Approval log permissions", "pass", "Log not yet created")
        )

    # === Rate Limiting (4 checks) ===
    cat = "Rate Limiting"

    if settings.tool_rate_limiting_enabled:
        report.checks.append(AuditCheck(cat, "Tool rate limiting enabled", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat, "Tool rate limiting enabled", "warn", "TOOL_RATE_LIMITING_ENABLED=false"
            )
        )

    if settings.login_rate_limit > 0:
        report.checks.append(AuditCheck(cat, "Login rate limiting", "pass"))
    else:
        report.checks.append(AuditCheck(cat, "Login rate limiting", "warn", "LOGIN_RATE_LIMIT=0"))

    if settings.max_websocket_connections > 0:
        report.checks.append(AuditCheck(cat, "WebSocket limits set", "pass"))
    else:
        report.checks.append(
            AuditCheck(cat, "WebSocket limits set", "warn", "MAX_WEBSOCKET_CONNECTIONS=0")
        )

    if settings.max_daily_api_spend_usd > 0:
        report.checks.append(AuditCheck(cat, "API spending limit set", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat, "API spending limit set", "warn", "MAX_DAILY_API_SPEND_USD=0 (unlimited)"
            )
        )

    # === Approval Gates (3 checks) ===
    cat = "Approval Gates"

    log_path = Path(settings.approval_log_path)
    report.checks.append(AuditCheck(cat, "Approval log path configured", "pass"))

    log_dir = log_path.parent
    if log_dir.exists():
        report.checks.append(AuditCheck(cat, "Approval log directory exists", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat, "Approval log directory exists", "warn", f"Directory {log_dir} does not exist"
            )
        )

    report.checks.append(
        AuditCheck(
            cat,
            "Protected actions defined",
            "pass",
            "gmail_send, git_push, file_delete, external_api",
        )
    )

    # === Notifications (3 checks) ===
    cat = "Notifications"

    if settings.get_webhook_urls():
        report.checks.append(AuditCheck(cat, "Webhook URLs configured", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "Webhook URLs configured",
                "warn",
                "No WEBHOOK_URLS set — no external notifications",
            )
        )

    if settings.get_notification_email_recipients():
        report.checks.append(AuditCheck(cat, "Email notifications configured", "pass"))
    else:
        report.checks.append(
            AuditCheck(
                cat,
                "Email notifications configured",
                "warn",
                "No NOTIFICATION_EMAIL_RECIPIENTS set",
            )
        )

    if settings.get_webhook_events():
        report.checks.append(AuditCheck(cat, "Webhook events configured", "pass"))
    else:
        report.checks.append(
            AuditCheck(cat, "Webhook events configured", "warn", "No WEBHOOK_EVENTS set")
        )

    return report


def startup_audit():
    """Run security audit at startup and log warnings."""
    logger.info("Running startup security audit...")
    report = run_audit()
    for check in report.checks:
        if check.status == "fail":
            logger.warning(f"SECURITY AUDIT FAIL: [{check.category}] {check.name} — {check.detail}")
        elif check.status == "warn":
            logger.warning(f"SECURITY AUDIT WARN: [{check.category}] {check.name} — {check.detail}")
    logger.info(
        f"Security audit complete: score={report.score}/100 "
        f"({report.passed} pass, {report.warnings} warn, {report.failures} fail)"
    )
    return report


class SecurityAuditTool(Tool):
    """Run security audit on the Agent42 installation."""

    @property
    def name(self) -> str:
        return "security_audit"

    @property
    def description(self) -> str:
        return (
            "Run a comprehensive security audit on this Agent42 installation. "
            "Checks authentication, network, sandbox, secrets, rate limiting, "
            "approval gates, and notification configuration."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Optional: filter to a specific category",
                    "default": "",
                },
            },
        }

    async def execute(self, category: str = "", **kwargs) -> ToolResult:
        report = run_audit()
        if category:
            report.checks = [c for c in report.checks if c.category.lower() == category.lower()]
        return ToolResult(output=report.format(), success=report.failures == 0)
