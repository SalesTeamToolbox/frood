---
name: dependency-management
description: Manage project dependencies — version pinning, auditing, updating, lock files.
always: false
task_types: [coding, refactoring]
---

# Dependency Management

## Version Pinning Strategies

### Semantic Versioning (semver)
Version format: `MAJOR.MINOR.PATCH` (e.g., `2.4.1`).
- **MAJOR**: Breaking changes.
- **MINOR**: New features, backwards compatible.
- **PATCH**: Bug fixes, backwards compatible.

### Pinning Notation
| Notation       | Example    | Matches                   | Use When                         |
|----------------|------------|---------------------------|----------------------------------|
| Exact          | `1.2.3`    | Only `1.2.3`              | Maximum reproducibility          |
| Caret `^`      | `^1.2.3`   | `>=1.2.3, <2.0.0`         | Default for npm; allows minors   |
| Tilde `~`      | `~1.2.3`   | `>=1.2.3, <1.3.0`         | Allow patches only               |
| Range           | `>=1.2, <2` | Within the range          | Explicit control                 |
| Wildcard `*`   | `1.2.*`    | Any patch of `1.2`        | Rarely recommended               |

**Recommendation**: Use caret `^` for libraries (flexibility for consumers) and exact pinning or tilde `~` for applications (reproducibility).

## Lock Files

Lock files record the exact resolved versions of every dependency in the tree.

- **Why they matter**: Without a lock file, `npm install` or `pip install` may resolve to different versions on different machines or at different times, causing "works on my machine" bugs.
- **Always commit lock files** to version control for applications.
- **Do not commit lock files** for libraries (let consumers resolve versions).

| Ecosystem   | Lock File              | Install Command           |
|-------------|------------------------|---------------------------|
| npm         | `package-lock.json`    | `npm ci`                  |
| yarn        | `yarn.lock`            | `yarn install --frozen-lockfile` |
| pnpm        | `pnpm-lock.yaml`       | `pnpm install --frozen-lockfile` |
| pip         | `requirements.txt`     | `pip install -r requirements.txt` |
| poetry      | `poetry.lock`          | `poetry install`          |
| uv          | `uv.lock`              | `uv sync`                 |

Use `npm ci` (not `npm install`) in CI pipelines to ensure the lock file is respected exactly.

## Updating Dependencies Safely

1. **Update one dependency at a time** -- not everything at once.
2. **Read the changelog** before updating, especially for major version bumps.
3. **Run the full test suite** after each update.
4. **Check for deprecation warnings** in the output.
5. **Use automated tools** to identify available updates:
   - `npm outdated` or `npx npm-check-updates`
   - `pip list --outdated` or `uv pip list --outdated`
   - `poetry show --outdated`

### Automated Update Tools
- **Dependabot** (GitHub): Automatically creates PRs for dependency updates. Configure in `.github/dependabot.yml`.
- **Renovate**: More configurable alternative to Dependabot with automerge support and grouping.

## Auditing for Vulnerabilities

Run security audits regularly and in CI:

- **npm**: `npm audit` (fix with `npm audit fix`).
- **yarn**: `yarn audit`.
- **pip**: `pip-audit` (install separately).
- **uv**: `uv pip audit`.
- **Snyk**: Cross-ecosystem vulnerability scanning.

Set up alerts in your repository: **GitHub > Settings > Code security and analysis > Dependabot alerts**.

## Python Specifics

- **pip**: Use `pip freeze > requirements.txt` to capture exact versions. Consider `pip-tools` for managing `requirements.in` and `requirements.txt` separately.
- **poetry**: Declares dependencies in `pyproject.toml` with a `poetry.lock` for exact resolution. Use `poetry add <pkg>` and `poetry update <pkg>`.
- **uv**: Fast Rust-based package manager. Use `uv add <pkg>`, `uv sync`, and `uv lock`. Drop-in replacement for pip with significant speed improvements.
- Use virtual environments (`venv`, `poetry shell`, `uv venv`) to isolate project dependencies.

## JavaScript Specifics

- **npm**: Ships with Node.js. Use `npm ci` in CI, `npm install` locally.
- **yarn**: Offers Plug'n'Play (PnP) mode for faster installs. Use `yarn dlx` instead of `npx`.
- **pnpm**: Uses a content-addressable store to save disk space. Strict dependency resolution prevents phantom dependencies.
- Use `engines` field in `package.json` to enforce Node.js version requirements.
- Use `overrides` (npm) or `resolutions` (yarn) to force specific versions of transitive dependencies when patching vulnerabilities.
