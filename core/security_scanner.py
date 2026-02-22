"""
Scheduled security scanner — automated environment scanning with GitHub issue reporting.

Runs security audits and vulnerability scans on a configurable interval,
then creates or updates GitHub issues with findings via the gh CLI.

Uses existing tools:
- tools.security_audit.run_audit() — configuration posture (36 checks)
- tools.security_analyzer.SecurityAnalyzerTool — secrets, dependencies, OWASP scans
"""

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime

logger = logging.getLogger("agent42.security_scanner")

# Severity ordering for filtering and display
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}

# Map audit check statuses to severity levels
_AUDIT_STATUS_SEVERITY = {"fail": "high", "warn": "medium", "pass": "none"}


class ScheduledSecurityScanner:
    """Background security scanner that reports findings as GitHub issues."""

    def __init__(
        self,
        workspace_path: str,
        interval_seconds: float = 28800.0,
        min_severity: str = "medium",
        github_issues_enabled: bool = True,
        notification_service=None,
        memory_store=None,
    ):
        self._workspace = workspace_path
        self._interval = interval_seconds
        self._min_severity = min_severity
        self._github_issues = github_issues_enabled
        self._notification_service = notification_service
        self._memory_store = memory_store
        self._running = False

    async def start(self):
        """Background loop: startup delay, then scan at interval."""
        self._running = True
        hours = self._interval / 3600
        logger.info(f"Security scanner started (interval: {hours:.1f}h)")

        # Initial delay to let the system stabilize before first scan
        await asyncio.sleep(60)

        while self._running:
            try:
                report = await self.run_scan()
                if self._github_issues:
                    await self._report_to_github(report)
                await self._notify(report)
                await self._log_event(report)
            except Exception as e:
                logger.error(f"Security scan failed: {e}", exc_info=True)

            # Sleep for the configured interval
            for _ in range(int(self._interval)):
                if not self._running:
                    break
                await asyncio.sleep(1)

    def stop(self):
        """Stop the background loop."""
        self._running = False
        logger.info("Security scanner stopped")

    async def run_scan(self) -> dict:
        """Execute all security checks and return aggregated report.

        Returns a dict with:
            - timestamp: ISO 8601 scan time
            - audit: AuditReport summary
            - findings: list of {severity, category, description, detail}
            - counts: {critical, high, medium, low} finding counts
            - overall_severity: highest severity found
        """
        logger.info("Starting security scan...")
        findings = []

        # 1. Configuration audit (tools/security_audit.py)
        try:
            from tools.security_audit import run_audit

            audit_report = run_audit()
            for check in audit_report.checks:
                severity = _AUDIT_STATUS_SEVERITY.get(check.status, "none")
                if _SEVERITY_ORDER.get(severity, 4) <= _SEVERITY_ORDER.get(self._min_severity, 2):
                    findings.append(
                        {
                            "severity": severity,
                            "category": f"Config: {check.category}",
                            "description": check.name,
                            "detail": check.detail,
                        }
                    )
        except Exception as e:
            logger.error(f"Config audit failed: {e}")

        # 2. Secrets scan (tools/security_analyzer.py)
        try:
            from tools.security_analyzer import SecurityAnalyzerTool

            analyzer = SecurityAnalyzerTool(self._workspace)
            result = analyzer._scan_secrets()
            findings.extend(self._parse_analyzer_output(result.output, "Secrets"))
        except Exception as e:
            logger.error(f"Secrets scan failed: {e}")

        # 3. Dependency scan
        try:
            from tools.security_analyzer import SecurityAnalyzerTool

            analyzer = SecurityAnalyzerTool(self._workspace)
            result = analyzer._scan_dependencies()
            findings.extend(self._parse_analyzer_output(result.output, "Dependencies"))
        except Exception as e:
            logger.error(f"Dependency scan failed: {e}")

        # 4. OWASP scan
        try:
            from tools.security_analyzer import SecurityAnalyzerTool

            analyzer = SecurityAnalyzerTool(self._workspace)
            result = analyzer._scan_owasp()
            findings.extend(self._parse_analyzer_output(result.output, "OWASP"))
        except Exception as e:
            logger.error(f"OWASP scan failed: {e}")

        # Count findings by severity
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in findings:
            sev = f["severity"]
            if sev in counts:
                counts[sev] += 1

        # Determine overall severity
        overall = "none"
        for sev in ("critical", "high", "medium", "low"):
            if counts.get(sev, 0) > 0:
                overall = sev
                break

        report = {
            "timestamp": datetime.now(UTC).isoformat(),
            "findings": findings,
            "counts": counts,
            "overall_severity": overall,
            "total": len(findings),
        }

        logger.info(
            f"Security scan complete: {report['total']} findings "
            f"(critical={counts['critical']}, high={counts['high']}, "
            f"medium={counts['medium']}, low={counts['low']})"
        )
        return report

    def _parse_analyzer_output(self, output: str, category: str) -> list[dict]:
        """Parse SecurityAnalyzerTool output into structured findings.

        The analyzer returns markdown-formatted output with sections like:
        ### CRITICAL (N)
        - L42 **description**
          `context`
        """
        findings = []
        if not output or "CLEAN" in output:
            return findings

        current_severity = "medium"
        for line in output.split("\n"):
            line = line.strip()

            # Match severity headers: ### CRITICAL (2)
            severity_match = re.match(r"###\s+(CRITICAL|HIGH|MEDIUM|LOW)\s+\(\d+\)", line)
            if severity_match:
                current_severity = severity_match.group(1).lower()
                continue

            # Match finding lines: - L42 **description**
            finding_match = re.match(r"^-\s+(?:L\d+\s+)?\*\*(.+?)\*\*", line)
            if finding_match:
                desc = finding_match.group(1)
                if _SEVERITY_ORDER.get(current_severity, 4) <= _SEVERITY_ORDER.get(
                    self._min_severity, 2
                ):
                    findings.append(
                        {
                            "severity": current_severity,
                            "category": category,
                            "description": desc,
                            "detail": "",
                        }
                    )
                continue

            # Match context lines:   `some context`
            context_match = re.match(r"^\s+`(.+?)`", line)
            if context_match and findings:
                findings[-1]["detail"] = context_match.group(1)

        return findings

    async def _report_to_github(self, report: dict):
        """Create or update GitHub issues with scan findings."""
        if report["total"] == 0:
            # Clean scan — close any existing open issue
            existing = await self._get_existing_issue()
            if existing:
                await self._close_issue(
                    existing, f"Security scan passed with no findings at {report['timestamp']}."
                )
                logger.info(f"Closed security scan issue #{existing} (clean scan)")
            return

        body = self._format_report_body(report)
        title = (
            f"[Security Scan] {report['overall_severity'].upper()} — "
            f"{report['total']} findings ({report['timestamp'][:10]})"
        )

        existing = await self._get_existing_issue()
        if existing:
            # Update existing issue with a comment
            await self._comment_on_issue(existing, body)
            logger.info(f"Updated security scan issue #{existing} with new findings")
        else:
            # Create new issue
            await self._create_issue(title, body, ["security-scan"])
            logger.info("Created new security scan GitHub issue")

    def _format_report_body(self, report: dict) -> str:
        """Format scan report as GitHub-flavored markdown."""
        lines = [
            "## Security Scan Report",
            f"**Date:** {report['timestamp']}",
            f"**Overall Severity:** {report['overall_severity'].upper()}",
            f"**Total Findings:** {report['total']}",
            "",
            "| Severity | Count |",
            "|----------|-------|",
            f"| Critical | {report['counts']['critical']} |",
            f"| High | {report['counts']['high']} |",
            f"| Medium | {report['counts']['medium']} |",
            f"| Low | {report['counts']['low']} |",
            "",
        ]

        # Group findings by category
        by_category: dict[str, list[dict]] = {}
        for f in report["findings"]:
            by_category.setdefault(f["category"], []).append(f)

        for cat, cat_findings in by_category.items():
            lines.append(f"### {cat}")
            for f in cat_findings:
                severity_badge = f"**[{f['severity'].upper()}]**"
                lines.append(f"- {severity_badge} {f['description']}")
                if f["detail"]:
                    lines.append(f"  - `{f['detail']}`")
            lines.append("")

        lines.append("---")
        lines.append("*Automated scan by Agent42 security scanner*")
        return "\n".join(lines)

    async def _get_existing_issue(self) -> int | None:
        """Find an existing open security-scan issue."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "list",
                "--label",
                "security-scan",
                "--state",
                "open",
                "--json",
                "number",
                "--limit",
                "1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"gh issue list failed: {stderr.decode().strip()}")
                return None
            issues = json.loads(stdout.decode())
            if issues:
                return issues[0]["number"]
        except FileNotFoundError:
            logger.warning("gh CLI not found — cannot check existing issues")
        except Exception as e:
            logger.warning(f"Failed to check existing issues: {e}")
        return None

    async def _create_issue(self, title: str, body: str, labels: list[str]):
        """Create a GitHub issue via gh CLI."""
        cmd = ["gh", "issue", "create", "--title", title, "--body", body]
        for label in labels:
            cmd.extend(["--label", label])
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"gh issue create failed: {stderr.decode().strip()}")
            else:
                logger.info(f"GitHub issue created: {stdout.decode().strip()}")
        except FileNotFoundError:
            logger.warning("gh CLI not found — cannot create issues")
        except Exception as e:
            logger.error(f"Failed to create GitHub issue: {e}")

    async def _comment_on_issue(self, issue_number: int, body: str):
        """Add a comment to an existing GitHub issue."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "comment",
                str(issue_number),
                "--body",
                body,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"gh issue comment failed: {stderr.decode().strip()}")
        except FileNotFoundError:
            logger.warning("gh CLI not found — cannot comment on issues")
        except Exception as e:
            logger.error(f"Failed to comment on GitHub issue: {e}")

    async def _close_issue(self, issue_number: int, comment: str):
        """Close a GitHub issue with a comment."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "close",
                str(issue_number),
                "--comment",
                comment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"gh issue close failed: {stderr.decode().strip()}")
        except FileNotFoundError:
            logger.warning("gh CLI not found — cannot close issues")
        except Exception as e:
            logger.error(f"Failed to close GitHub issue: {e}")

    async def _notify(self, report: dict):
        """Send webhook notification for critical/high findings."""
        if not self._notification_service:
            return
        if report["counts"]["critical"] == 0 and report["counts"]["high"] == 0:
            return

        try:
            from core.notification_service import SEVERITY_CRITICAL, NotificationPayload

            await self._notification_service.notify(
                NotificationPayload(
                    event="security_alert",
                    timestamp=time.time(),
                    title=f"Security Scan: {report['overall_severity'].upper()}",
                    details=(
                        f"{report['total']} findings "
                        f"(critical={report['counts']['critical']}, "
                        f"high={report['counts']['high']})"
                    ),
                    severity=SEVERITY_CRITICAL,
                )
            )
        except Exception as e:
            logger.error(f"Failed to send security notification: {e}")

    async def _log_event(self, report: dict):
        """Log scan event to persistent memory."""
        if not self._memory_store:
            return
        try:
            self._memory_store.log_event(
                "security_scan",
                f"Scan complete: {report['overall_severity'].upper()} ({report['total']} findings)",
                json.dumps(report["counts"]),
            )
        except Exception as e:
            logger.error(f"Failed to log security scan event: {e}")
