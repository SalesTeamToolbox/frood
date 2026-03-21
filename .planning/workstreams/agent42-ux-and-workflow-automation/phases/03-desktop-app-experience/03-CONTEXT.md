# Phase 3: Desktop App Experience - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Users can install Agent42 as a PWA from the browser and launch it from the desktop without a browser address bar or tabs. This phase creates the PWA manifest, generates icons in required sizes, adds a `setup.sh create-shortcut` command for platform-specific desktop shortcuts, and ensures chromeless launch. No service worker offline support (v2 requirement APP-05), no auto-update notifications (APP-06).

</domain>

<decisions>
## Implementation Decisions

### PWA manifest configuration
- **D-01:** Create `dashboard/frontend/dist/manifest.json` with `"display": "standalone"` (not `fullscreen` — standalone preserves OS window chrome like close/minimize).
- **D-02:** App name: `"Agent42"`, short_name: `"Agent42"`, description: `"AI Agent Platform — Don't Panic"`.
- **D-03:** Theme color: `#6366f1` (matches CSS `--accent`). Background color: `#0f1117` (matches CSS `--bg-primary`).
- **D-04:** Start URL: `/` (the dashboard root). Scope: `/`.
- **D-05:** Icons array must include sizes: 192x192, 512x512 (minimum for Chrome PWA install), plus 180x180 for Apple touch icon. Source: generate PNGs from existing `agent42-favicon.svg`.
- **D-06:** Add `<link rel="manifest" href="/manifest.json">` and `<meta name="theme-color" content="#6366f1">` to `index.html`.

### Icon generation
- **D-07:** Generate PNG icons from `dashboard/frontend/dist/assets/agent42-favicon.svg` at build time. Use a simple Python script (`scripts/generate-icons.py`) with Pillow/cairosvg — no npm toolchain.
- **D-08:** Output icons to `dashboard/frontend/dist/assets/icons/` directory: `icon-192.png`, `icon-512.png`, `apple-touch-icon-180.png`.
- **D-09:** Include the generated PNGs in the repo (not gitignored) so the dashboard works without running the generator.

### Desktop shortcut command
- **D-10:** Add `setup.sh create-shortcut` subcommand that creates a platform-appropriate shortcut launching the default browser in app mode.
- **D-11:** Windows: create a `.lnk` file on the Desktop using PowerShell. Target: `chrome.exe --app=http://localhost:8000` (or Edge fallback `msedge.exe --app=...`). Icon: the 512px PNG converted to `.ico`.
- **D-12:** macOS: create a `.app` bundle in `/Applications/` using a shell script wrapper. Bundle contains `Info.plist` + shell script that runs `open -a "Google Chrome" --args --app=http://localhost:8000`.
- **D-13:** Linux: create a `.desktop` file in `~/.local/share/applications/`. Uses `Exec=google-chrome --app=http://localhost:8000` with `StartupWMClass=agent42`.
- **D-14:** The shortcut command auto-detects the platform and available browser (Chrome preferred, Edge fallback on Windows, Chromium fallback on Linux). If no supported browser found, print error with instructions to install Chrome.

### Chromeless launch behavior
- **D-15:** The `--app=URL` flag on Chromium-based browsers (Chrome, Edge, Brave) provides chromeless mode natively — no address bar, no tab bar, own taskbar entry. This is the primary mechanism.
- **D-16:** Safari on macOS: document limitation (Safari doesn't support `--app` flag). Recommend Chrome for desktop app experience; PWA install from Safari creates an adequate standalone window.
- **D-17:** The Agent42 dashboard `<title>` already reads "Agent42 — Don't Panic". The PWA manifest `name` and shortcut name should both read "Agent42" (without the tagline — keeps taskbar clean).

### Claude's Discretion
- PowerShell script details for .lnk creation
- Exact Info.plist fields for macOS .app bundle
- Whether to add a `setup.sh remove-shortcut` cleanup command
- Icon generation script implementation details
- Whether to support Brave/Vivaldi detection in addition to Chrome/Edge

</decisions>

<specifics>
## Specific Ideas

- The app should feel native on the taskbar — correct icon, correct name, no "localhost:8000" visible anywhere.
- Agent42's existing dark theme (`--bg-primary: #0f1117`) should be the splash/background color — no white flash on launch.
- setup.sh should print a clear success message: "Shortcut created! Find Agent42 on your desktop." with platform-specific location.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Dashboard frontend
- `dashboard/frontend/dist/index.html` — Current HTML head with existing PWA meta tags (mobile-web-app-capable, apple-mobile-web-app-capable)
- `dashboard/frontend/dist/style.css` — CSS custom properties (theme colors: --accent, --bg-primary)
- `dashboard/frontend/dist/assets/` — Existing SVG assets (agent42-favicon.svg, agent42-logo.svg, agent42-logo-light.svg)

### Server configuration
- `dashboard/server.py` line 4815 — StaticFiles mount at `/` serving `dashboard/frontend/dist/`

### Setup script
- `setup.sh` — Existing subcommand pattern (sync-auth), info/warn/error helpers, platform detection

### Requirements
- `.planning/workstreams/agent42-ux-and-workflow-automation/REQUIREMENTS.md` — APP-01 through APP-04

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dashboard/frontend/dist/assets/agent42-favicon.svg` — Source for icon generation (already used as favicon)
- `setup.sh` — Has subcommand routing pattern, platform detection, info/warn/error helpers. Add `create-shortcut` alongside `sync-auth`.
- `index.html` — Already has `mobile-web-app-capable` and `apple-mobile-web-app-capable` meta tags. Just needs manifest link and theme-color.

### Established Patterns
- Frontend is pure HTML/JS/CSS — no build step, no npm, no bundler. Icons must be pre-generated.
- StaticFiles mount at `/` means `manifest.json` placed in `dashboard/frontend/dist/` is automatically served.
- setup.sh uses bash with `set -e`, color helpers, and subcommand routing via `$1` positional arg.

### Integration Points
- `dashboard/frontend/dist/manifest.json` — new file, served by existing StaticFiles mount
- `dashboard/frontend/dist/index.html` — add manifest link tag and theme-color meta
- `dashboard/frontend/dist/assets/icons/` — new directory for generated PNG icons
- `setup.sh` — new `create-shortcut` subcommand
- `scripts/generate-icons.py` — new utility for SVG→PNG conversion

</code_context>

<deferred>
## Deferred Ideas

- Service worker for offline splash screen (APP-05 — v2 requirement)
- Auto-update notification when new version deployed (APP-06 — v2 requirement)
- Electron wrapper (out of scope per REQUIREMENTS.md — PWA + --app achieves same result)

</deferred>

---

*Phase: 03-desktop-app-experience*
*Context gathered: 2026-03-21 via --auto (Claude recommended defaults)*
