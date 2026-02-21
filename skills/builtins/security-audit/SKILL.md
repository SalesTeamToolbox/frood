---
name: security-audit
description: Audit code and configuration for security vulnerabilities (OWASP Top 10, secrets, dependencies).
always: false
task_types: [coding, debugging, refactoring]
---

# Security Audit Skill

You are performing a security audit. Be thorough and assume an adversarial mindset.

## Audit Areas

### 1. Injection (OWASP A03)
- **SQL Injection**: parameterized queries, no string concatenation in SQL
- **Command Injection**: no `os.system()`, `subprocess.shell=True` with user input
- **XSS**: output encoding in templates, no `innerHTML` with user data
- **Path Traversal**: validate file paths, no `../` in user-controlled paths
- **LDAP/XML Injection**: sanitize structured query inputs

### 2. Authentication & Authorization (OWASP A01, A07)
- Passwords hashed with bcrypt/argon2 (not MD5/SHA1)
- JWT secrets are strong and not hardcoded
- Session tokens are cryptographically random
- Rate limiting on login endpoints
- Authorization checked on every protected endpoint
- No privilege escalation paths

### 3. Sensitive Data Exposure (OWASP A02)
- Secrets not in source code (check .env, config files, git history)
- API keys not logged or included in error messages
- HTTPS enforced, no mixed content
- Sensitive data encrypted at rest where required
- PII handled according to retention policies

### 4. Security Misconfiguration (OWASP A05)
- CORS restricted to specific origins (not `*`)
- Debug mode disabled in production
- Default credentials changed
- Unnecessary ports/services closed
- Security headers set (CSP, HSTS, X-Frame-Options)

### 5. Dependency Vulnerabilities (OWASP A06)
```bash
# Python
pip audit
safety check

# JavaScript
npm audit
npx snyk test
```

### 6. Logging & Monitoring
- Security events logged (auth failures, access denied, input validation failures)
- No sensitive data in logs (passwords, tokens, PII)
- Log injection prevented (newlines sanitized)

## Output Format

```
## Security Audit Report

**Scope:** [files/components audited]
**Risk Level:** CRITICAL / HIGH / MEDIUM / LOW / CLEAN

### Findings

#### [CRITICAL] Finding Title
**Location:** file.py:line
**Category:** Injection / Auth / Data Exposure / Misconfig
**Description:** What the vulnerability is.
**Impact:** What an attacker could do.
**Remediation:** How to fix it, with code example.
**References:** CWE-xxx, OWASP link

### Summary
- X critical, Y high, Z medium findings
- Recommended priority order for remediation
```

## Guidelines
- Prioritize findings by exploitability and impact.
- Provide concrete remediation steps, not vague advice.
- Check for defense-in-depth — don't assume one layer is enough.
- Review both the code and the configuration.
- Look at git history for accidentally committed secrets.
