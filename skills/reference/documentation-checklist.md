# Documentation Checklist — Condensed Reference

> Condensed from `documentation` skill. Technical doc patterns.

## Doc Types & Templates

### 1. API Reference (OpenAPI/Swagger)
```yaml
paths:
  /users/{id}:
    get:
      summary: Get user by ID
      parameters:
        - name: id
          in: path
          required: true
          schema: {type: integer}
      responses:
        '200':
          description: User object
          content:
            application/json:
              schema: {$ref: '#/components/schemas/User'}
        '404':
          description: Not found
```

### 2. README.md (Project Entry)
```markdown
# Project Name
One-line description.

## Quick Start
```bash
pip install -r requirements.txt
python main.py
```

## Architecture
[High-level diagram or description]

## Configuration
| Env Var | Required | Default | Description |
|---------|----------|---------|-------------|

## Testing
```bash
pytest tests/
```

## Deployment
[Link to deploy docs]
```

### 3. Architecture Decision Record (ADR)
```markdown
# ADR-XXX: [Title]

## Status
Proposed | Accepted | Superseded

## Context
[Problem, constraints, assumptions]

## Decision
[What we're doing]

## Consequences
### Positive
- [Benefit]

### Negative
- [Trade-off]

## Links
- [Related ADRs, tickets, docs]
```

### 4. Runbook (Operational)
```markdown
# Runbook: [Service/Component]

## Overview
[What it does, dependencies]

## Common Operations
### [Operation Name]
- **Command:** `...`
- **Expected:** `...`
- **Rollback:** `...`

## Alerts
| Alert | Meaning | Action |
|-------|---------|--------|

## Debugging
- Logs: `journalctl -u service`
- Metrics: [Grafana dashboard link]
- Traces: [Jaeger link]
```

## Quality Checklist

| Check | Yes/No |
|-------|--------|
| **Audience defined** — Who reads this? | |
| **Purpose stated** — What problem does it solve? | |
| **Prerequisites listed** — What's needed before starting? | |
| **Steps are atomic** — One action per step | |
| **Expected outcomes** — What does "done" look like? | |
| **Error cases covered** — What if it fails? | |
| **Examples included** — Real commands/output | |
| **Links to related docs** — No dead ends | |
| **Versioned** — Date, author, changelog | |
| **Reviewed** — By domain expert | |

## Style Rules

| Rule | Example |
|------|---------|
| **Imperative mood** | "Run `make test`" not "You should run..." |
| **Present tense** | "The service starts" not "will start" |
| **Specific paths** | `/etc/nginx/nginx.conf` not "config file" |
| **Code blocks for commands** | ```bash\ncmd\n``` not inline |
| **Screenshots dated** | UI changes fast; date them |
| **No marketing fluff** | "Fast, easy" → "Sub-100ms p99" |

## Maintenance

- [ ] **Review quarterly** — Schedule in calendar
- [ ] **Deprecation notices** — 6-month warning
- [ ] **Broken link check** — `lychee` or `markdown-link-check`
- [ ] **Diagram source tracked** — Mermaid/PlantUML in repo, not images
- [ ] **Single source of truth** — No duplication across files

## Quick Commands

```bash
# Link check
npx markdown-link-check README.md

# Spell check
npx cspell "**/*.md"

# Generate API docs from code
spectacle docs/openapi.yaml -t /output

# Convert ADRs to site
adr-log -o docs/adr
```

## Output Format (for PR description)

```
## Documentation Changes

### Added
- `docs/api/users.md` — GET /users/{id} endpoint
- `adr/003-use-redis-cache.md` — Decision record

### Updated
- `README.md` — Added quick start, fixed config table

### Removed
- `docs/old-deploy.md` — Superseded by deploy pipeline docs

### Review Required
- [ ] API docs match implementation
- [ ] Runbook steps verified in staging
```