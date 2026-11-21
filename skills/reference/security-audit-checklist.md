# Security Audit Checklist — Condensed Reference

> Condensed from `security-audit` skill. OWASP Top 10 focused.

## Quick-Scan Categories

### 1. Injection (A03)
- [ ] **SQL** — Parameterized queries only, no string concat
- [ ] **Command** — No `shell=True`, validate/allowlist args
- [ ] **LDAP/XPath/XQuery** — Escape or parameterize
- [ ] **NoSQL** — Validate query structure, no operator injection

### 2. Broken Access Control (A01)
- [ ] **AuthZ checks** — Every endpoint verifies permissions
- [ ] **IDOR** — No direct object references without ownership check
- [ ] **Path traversal** — `../` blocked, use allowlist for file access
- [ ] **Force browsing** — Admin endpoints protected

### 3. Cryptographic Failures (A02)
- [ ] **Secrets** — No hardcoded keys, passwords, tokens
- [ ] **TLS** — HTTPS everywhere, HSTS, secure cookies
- [ ] **Hashing** — bcrypt/argon2 for passwords, not MD5/SHA1
- [ ] **Key rotation** — Rotation policy documented

### 4. Injection — XSS (A03)
- [ ] **Output encoding** — Context-aware (HTML, JS, CSS, URL)
- [ ] **CSP** — Content-Security-Policy header set
- [ ] **Trusted types** — Where supported

### 5. Security Misconfiguration (A05)
- [ ] **Defaults changed** — No default creds, debug off in prod
- [ ] **Headers** — `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`
- [ ] **Error handling** — No stack traces to users
- [ ] **Dependencies** — No known CVEs (`npm audit`, `pip-audit`)

### 6. Auth/Session (A07)
- [ ] **MFA** — Required for admin/sensitive
- [ ] **Session** — Secure, HttpOnly, SameSite, rotation
- [ ] **Password policy** — Length, complexity, breach check
- [ ] **Rate limiting** — Login, API, password reset

### 7. Software Integrity (A08)
- [ ] **Supply chain** — Lockfiles committed, signed releases
- [ ] **CI/CD** — Build provenance, artifact verification
- [ ] **Updates** — Auto-update with verification

### 8. Logging/Monitoring (A09)
- [ ] **Security events** — Auth failures, access denied, admin actions logged
- [ ] **Alerting** — On anomaly thresholds
- [ ] **No PII/secrets** in logs

## Quick Commands

```bash
# Dependency audit
npm audit --audit-level=high
pip-audit -r requirements.txt

# Secret scan
git log --all --full-history --oneline --grep="password\|secret\|key\|token"
trufflehog git file://. --since-commit HEAD~100

# SAST (if configured)
semgrep --config=auto .
bandit -r .
```

## Output Format

```
## Security Audit — [component]

### Critical (must fix)
- [CVE-XXXX] [description] — [file:line] — [fix]

### Major (should fix)
- [OWASP AXX] [description] — [file:line] — [fix]

### Minor (nice to fix)
- [description] — [file:line] — [recommendation]

### Passed
- [check] — verified
```