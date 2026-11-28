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

logger = logging.getLogger("frood.security_scanner")

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
        github_issues_enabled: bool = False,
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
        # Repo privacy state for the public guard (fail closed).
        # _repo_visibility / _repo_name hold the current scan's gh repo view result.
        self._repo_visibility: str | None = None
        self._repo_name: str = "unknown repo"
        self._repo_unavailable_reason: str | None = None
        # _scan_private is True only while _report_to_github is running on a
        # PRIVATE/INTERNAL repo; write methods reuse it and reset it after.
        self._scan_private: bool | None = None
        # (repo, visibility) pairs already warned about, once per process.
        self._warned_visibility: set[tuple[str, str]] = set()

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

    async def _repo_is_private(self) -> bool:
        """Return True only when the workspace repo is PRIVATE or INTERNAL.

        Runs ``gh repo view --json visibility,nameWithOwner`` in
        ``self._workspace`` with a 30 s timeout. Any error, timeout, missing
        ``gh``, non-zero exit or unparsable output counts as not private
        (fail closed). The visibility, repo name and unavailability reason are
        stored on the instance for reuse within the same scan.
        """
        self._repo_visibility = None
        self._repo_name = "unknown repo"
        self._repo_unavailable_reason = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "repo",
                "view",
                "--json",
                "visibility,nameWithOwner",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._workspace,
            )
            try:
                stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                self._repo_unavailable_reason = "timed out"
                return False
            if proc.returncode != 0:
                self._repo_unavailable_reason = f"exit {proc.returncode}"
                return False
            try:
                data = json.loads(stdout.decode())
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                self._repo_unavailable_reason = "unparsable output"
                return False
            vis = data.get("visibility")
            name = data.get("nameWithOwner") or "unknown repo"
            self._repo_name = str(name)
            self._repo_visibility = str(vis) if vis is not None else None
            return self._repo_visibility in ("PRIVATE", "INTERNAL")
        except FileNotFoundError:
            self._repo_unavailable_reason = "gh not found"
            return False
        except Exception as e:
            self._repo_unavailable_reason = f"error: {e}"
            return False

    def _skip_due_to_visibility(self) -> bool:
        """Log the skip warning once per (repo, visibility) and return True if skipped.

        Called when the repo is not private (or visibility is unknown). The
        warning names the repo and visibility and is logged once per process for
        each distinct (repo, visibility) value.
        """
        vis = self._repo_visibility
        name = self._repo_name
        if vis in ("PRIVATE", "INTERNAL"):
            return False
        if vis is None:
            vis_label = f"UNKNOWN ({self._repo_unavailable_reason or 'unknown'})"
        else:
            vis_label = vis
        key = (name, vis_label)
        if key not in self._warned_visibility:
            self._warned_visibility.add(key)
            logger.warning(
                "security scanner: GitHub issue reporting skipped — %s is %s "
                "(never posts findings to a non-private repo)",
                name,
                vis_label,
            )
        return True

    async def _repo_write_permitted(self) -> bool:
        """True if writing to GitHub is allowed for this call.

        When called from ``_report_to_github`` on a private repo,
        ``self._scan_private`` is True and the scan's ``gh repo view`` result is
        reused. When called directly, the repo is checked for itself.
        """
        if self._scan_private is True:
            return True
        return await self._repo_is_private()

    async def _report_to_github(self, report: dict):
        """Create or update GitHub issues with scan findings."""
        if not self._github_issues:
            return
        # Fail closed: never post findings to a non-private repo.
        self._scan_private = None
        is_private = await self._repo_is_private()
        self._scan_private = is_private
        if not is_private:
            self._skip_due_to_visibility()
            self._scan_private = None
            return

        if report["total"] == 0:
            # Clean scan — close any existing open issue
            existing = await self._get_existing_issue()
            if existing:
                ok = await self._close_issue(
                    existing, f"Security scan passed with no findings at {report['timestamp']}."
                )
                if ok:
                    logger.info(f"Closed security scan issue #{existing} (clean scan)")
            self._scan_private = None
            return

        body = self._format_report_body(report)
        title = (
            f"[Security Scan] {report['overall_severity'].upper()} — "
            f"{report['total']} findings ({report['timestamp'][:10]})"
        )

        existing = await self._get_existing_issue()
        if existing:
            # Update existing issue with a comment
            ok = await self._comment_on_issue(existing, body)
            if ok:
                logger.info(f"Updated security scan issue #{existing} with new findings")
        else:
            # Create new issue
            ok = await self._create_issue(title, body, ["security-scan"])
            if ok:
                logger.info("Created new security scan GitHub issue")
        # Reset so direct write-method calls after this scan check for themselves.
        self._scan_private = None

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
        lines.append("*Automated scan by Frood security scanner*")
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
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("gh issue list timed out after 30s")
                return None
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

    async def _create_issue(self, title: str, body: str, labels: list[str]) -> bool:
        """Create a GitHub issue via gh CLI. Returns True only on gh exit 0."""
        if not await self._repo_write_permitted():
            return False
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
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("gh issue create timed out after 30s")
                return False
            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip()[:300]
                logger.warning("gh issue create failed: %s", err)
                return False
            logger.info(f"GitHub issue created: {stdout.decode().strip()}")
            return True
        except FileNotFoundError:
            logger.warning("gh CLI not found — cannot create issues")
            return False
        except Exception as e:
            logger.warning(f"Failed to create GitHub issue: {e}")
            return False

    async def _comment_on_issue(self, issue_number: int, body: str) -> bool:
        """Add a comment to an existing GitHub issue. Returns True only on gh exit 0."""
        if not await self._repo_write_permitted():
            return False
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
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("gh issue comment timed out after 30s")
                return False
            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip()[:300]
                logger.warning("gh issue comment failed: %s", err)
                return False
            logger.info(f"Comment added to security scan issue #{issue_number}")
            return True
        except FileNotFoundError:
            logger.warning("gh CLI not found — cannot comment on issues")
            return False
        except Exception as e:
            logger.warning(f"Failed to comment on GitHub issue: {e}")
            return False

    async def _close_issue(self, issue_number: int, comment: str) -> bool:
        """Close a GitHub issue with a comment. Returns True only on gh exit 0."""
        if not await self._repo_write_permitted():
            return False
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
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
                logger.warning("gh issue close timed out after 30s")
                return False
            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip()[:300]
                logger.warning("gh issue close failed: %s", err)
                return False
            logger.info(f"Closed security scan issue #{issue_number}")
            return True
        except FileNotFoundError:
            logger.warning("gh CLI not found — cannot close issues")
            return False
        except Exception as e:
            logger.warning(f"Failed to close GitHub issue: {e}")
            return False

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
