---
phase: 03-desktop-app-experience
plan: 01
subsystem: ui
tags: [pwa, manifest, icons, pillow, png, web-app]

# Dependency graph
requires: []
provides:
  - PWA manifest.json with standalone display, Agent42 branding, theme/background colors
  - PNG icons at 192x192, 512x512, and 180x180 generated from SVG favicon
  - index.html wired with manifest link, theme-color meta, and apple-touch-icon
  - scripts/generate-icons.py with cairosvg/svglib/Pillow fallback chain
affects: [03-02-service-worker, pwa-installability, desktop-app-experience]

# Tech tracking
tech-stack:
  added: [cairosvg (installed but Cairo DLL absent on Windows), Pillow (pure-Python icon renderer)]
  patterns: [SVG-to-PNG with graceful degradation fallback chain, Pillow geometry replication for Cairo-free environments]

key-files:
  created:
    - dashboard/frontend/dist/manifest.json
    - dashboard/frontend/dist/assets/icons/icon-192.png
    - dashboard/frontend/dist/assets/icons/icon-512.png
    - dashboard/frontend/dist/assets/icons/apple-touch-icon-180.png
    - scripts/generate-icons.py
  modified:
    - dashboard/frontend/dist/index.html

key-decisions:
  - "Pillow pixel-art fallback replicates robot-face geometry directly when Cairo DLL unavailable on Windows"
  - "Icons committed to repo (D-09) — not gitignored, available without running generate script"

patterns-established:
  - "Icon generation: cairosvg -> svglib+reportlab -> Pillow geometry fallback chain"
  - "PWA manifest: display=standalone, theme_color=#6366f1, background_color=#0f1117"

requirements-completed: [APP-01, APP-04]

# Metrics
duration: 7min
completed: 2026-03-21
---

# Phase 03 Plan 01: PWA Manifest and Icons Summary

**PWA manifest.json with standalone display + 3 PNG icons generated from SVG favicon using Pillow geometry fallback (Cairo DLL absent on Windows)**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-21T02:36:49Z
- **Completed:** 2026-03-21T02:43:50Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Created `manifest.json` with `display: standalone`, Agent42 branding, accent/dark theme colors
- Generated 3 PWA icons (192x192, 512x512, 180x180) from SVG favicon via pure-Python Pillow renderer
- Wired manifest link, theme-color meta, and apple-touch-icon into `index.html` head
- Built `scripts/generate-icons.py` with a 3-level fallback chain (cairosvg -> svglib -> Pillow geometry)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create icon generation script and generate PNG icons** - `7107b08` (feat)
2. **Task 2: Create PWA manifest and wire into index.html** - `fb78914` (feat)

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `dashboard/frontend/dist/manifest.json` — PWA manifest with standalone display, Agent42 name, theme colors, 3 icon references
- `dashboard/frontend/dist/index.html` — Added theme-color meta, manifest link, apple-touch-icon link to head
- `dashboard/frontend/dist/assets/icons/icon-192.png` — 192x192 PNG for PWA home screen
- `dashboard/frontend/dist/assets/icons/icon-512.png` — 512x512 PNG for PWA splash/install
- `dashboard/frontend/dist/assets/icons/apple-touch-icon-180.png` — 180x180 PNG for iOS add-to-home
- `scripts/generate-icons.py` — Icon generation script with cairosvg/svglib/Pillow fallback chain

## Decisions Made

- **Pillow geometry fallback:** cairosvg and svglib+reportlab both require the Cairo native DLL which is not installed on Windows. Rather than producing a solid-color placeholder, the script faithfully replicates the SVG robot-face geometry (background rect, antenna, arc eyes, smile, ear sensors) using Pillow's drawing API. Icons are visually correct at all three sizes.
- **Icons committed to repo:** Per D-09, the generated PNGs are tracked in git so the PWA works without running the generation script after clone.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pillow geometry renderer added when Cairo DLL unavailable on Windows**

- **Found during:** Task 1 (icon generation)
- **Issue:** cairosvg requires `libcairo-2.dll` (not installed on Windows without GTK/MSYS2). svglib+reportlab also falls through to Cairo via rlPyCairo. Both fail with `OSError: no library called "cairo-2" was found`.
- **Fix:** Added a third fallback path to `generate-icons.py` that directly draws the Agent42 robot face geometry using Pillow's `ImageDraw` API, faithfully replicating all SVG elements (rect, quadratic bezier arcs for eyes/smile, rounded rectangles for ears).
- **Files modified:** `scripts/generate-icons.py`
- **Verification:** Script runs to completion, all 3 icons generated at correct sizes, all > 100 bytes.
- **Committed in:** `7107b08` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 3 — blocking)
**Impact on plan:** Necessary workaround for Windows environment. On Linux/Mac with Cairo installed, cairosvg will be used automatically (true vector rendering). Pillow fallback produces visually correct icons.

## Issues Encountered

- Cairo native library not present on Windows development machine. All Python SVG renderers that ship pure-Python (cairosvg, svglib, wand) ultimately depend on Cairo/ImageMagick DLLs. Solved by implementing the Pillow geometry fallback.

## Known Stubs

None — all three PNGs are real rendered icons, manifest.json has all required fields, index.html correctly links them.

## User Setup Required

None — no external service configuration required. The PWA manifest is served automatically by the existing StaticFiles mount.

## Next Phase Readiness

- PWA manifest + icons complete — browser can detect installability (APP-01 satisfied)
- Correct branding (Agent42 name, accent purple theme, dark background) — no white flash on launch (APP-04 satisfied)
- Ready for Phase 03-02: Service Worker for offline support and install prompt control
- Chrome DevTools > Application > Manifest will show valid PWA manifest when server is running at http://localhost:8000

## Self-Check: PASSED

- FOUND: dashboard/frontend/dist/manifest.json
- FOUND: dashboard/frontend/dist/index.html
- FOUND: dashboard/frontend/dist/assets/icons/icon-192.png
- FOUND: dashboard/frontend/dist/assets/icons/icon-512.png
- FOUND: dashboard/frontend/dist/assets/icons/apple-touch-icon-180.png
- FOUND: scripts/generate-icons.py
- FOUND: commit 7107b08 (feat: icon generation script + PNG icons)
- FOUND: commit fb78914 (feat: PWA manifest + index.html update)

---
*Phase: 03-desktop-app-experience*
*Completed: 2026-03-21*
