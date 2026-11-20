# IP / Provenance Audit — Frood

**Repository:** `SalesTeamToolbox/frood`  
**Commit audited:** `3de8e5c` (origin/main)  
**Audited:** 2026-11-20  
**Scope:** Every imported / vendored asset in the public tree, with source repo and commit sha.

## Purpose

Record the IP/provenance of every asset copied or imported into Frood from an external repository, per the public-release plan owner decision Q2: *"No subtree merges (they drag private history). Each import ticket cites source repo + sha in the commit message and a `process/ATTRIBUTION.md` line."* This file is the audit log; import tickets (M3 orchestrator-import, M4 peer-mail-import) append to it.

## Cross-repo imports landed

None. At M2 (scrub + license + README) no external-repo imports have landed yet. M3 (orchestrator commands/agents/bin/rules/skills/installer) and M4 (peer-mail MCP server) are future tickets and will append source repo + sha here when they land.

**DoD:** the tree is publishable even before imports land; this file documents that the import log is currently empty of cross-repo assets.

## Pre-existing vendored / third-party assets

| Asset | Location | Source repo | Version / ref | Commit sha | Notes |
|-------|----------|-------------|---------------|------------|-------|
| WinSW (Windows Service Wrapper) | `winsw.exe` | `https://github.com/winsw/winsw` | `v3.0.0-alpha.11` (WinSW-x64.exe) | not pinned in-tree | Downloaded at setup time by `scripts/setup_helpers.py` (fallback `v3.0.0-alpha.10`); exact commit sha is not recorded in the Frood tree. MIT-licensed upstream. Used only by the optional Windows service installer (`install-agent42-service.bat`). |

## Dependency manifests (package-manager, not git imports)

Python runtime dependencies are declared in `requirements.txt` / `requirements-dev.txt` and installed from PyPI — they are not git-imported assets and carry no single commit sha. Frontend/Node dependencies (where present) are declared in `package.json` files and installed from npm — likewise not git imports. Neither manifest is in scope for this audit's source-repo+sha log.

## Intentional public references (not private assets)

The README and `.env.example` reference `https://salesteamtoolbox.com/` (Sales Team Toolbox public site) with UTM parameters (`utm_source=github&utm_medium=frood&utm_campaign=oss`). This is an intentional public CTA destination, not a private URL, ledger, or secret.

## How to add an import

When an import ticket lands, append a row to the table above with:

| Asset | Location | Source repo | Version / ref | Commit sha | Notes |

and cite `source repo + sha` in the import commit message. No subtree merges — clean copies only, private history excluded.
