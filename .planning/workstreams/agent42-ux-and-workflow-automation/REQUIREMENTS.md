# Requirements: Agent42 UX & Workflow Automation

**Defined:** 2026-03-20
**Core Value:** Agent42 must always be able to run agents reliably, with GSD as the default methodology when installed

## v1 Requirements

### Desktop App Experience

- [ ] **APP-01**: User can install Agent42 as a PWA from the browser (manifest.json with icons, theme, display: standalone)
- [ ] **APP-02**: User can run `setup.sh create-shortcut` to create a platform-specific desktop shortcut (Windows .lnk, macOS .app, Linux .desktop)
- [ ] **APP-03**: Desktop shortcut opens Agent42 in chromeless app mode (no address bar, tabs, or browser UI)
- [ ] **APP-04**: PWA displays correct Agent42 branding (name, icon, theme color) in OS taskbar and app switcher

### Memory Pipeline

- [x] **MEM-01**: Memory recall hook outputs relevant memories to stderr so they appear in VS Code Claude Code chat stream
- [x] **MEM-02**: Memory learn hook outputs learning confirmations to stderr so they appear in VS Code chat stream
- [x] **MEM-03**: End-to-end memory pipeline works: prompt triggers recall, stop triggers learn, both show visible feedback
- [x] **MEM-04**: Memory operations are logged in Agent42 server logs for debugging

### GSD Auto-Activation

- [ ] **GSD-01**: Always-on skill instructs Claude to use GSD methodology for multi-step coding/planning tasks
- [ ] **GSD-02**: CLAUDE.md section establishes GSD as the default process when Agent42 is installed
- [ ] **GSD-03**: Context-loader hook detects coding/planning task prompts and nudges toward GSD workflow
- [ ] **GSD-04**: Auto-activation is smart — skips GSD for trivial/single-step tasks (quick questions, simple edits)

### GSD Dashboard Integration

- [ ] **DASH-01**: Agent42 dashboard status bar shows active GSD workstream name and current phase
- [ ] **DASH-02**: Status bar updates in real-time via existing WebSocket heartbeat

## v2 Requirements

### Desktop App Experience

- **APP-05**: Service worker provides offline splash screen when server is unreachable
- **APP-06**: Auto-update notification when new Agent42 version is deployed

### GSD Integration

- **GSD-05**: Dashboard shows GSD roadmap progress (phases, completion percentage)
- **GSD-06**: Workstream switcher in dashboard sidebar

## Out of Scope

| Feature | Reason |
|---------|--------|
| Electron wrapper | PWA + --app mode achieves same result without build tooling |
| Chat/Code page consolidation | Separate milestone — mode toggle like Claude Desktop |
| Mobile app | Web-first, PWA handles mobile adequately |
| GSD auto-workstream creation | Complex UX, defer to v2 |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| MEM-01 | Phase 1 | Complete |
| MEM-02 | Phase 1 | Complete |
| MEM-03 | Phase 1 | Complete |
| MEM-04 | Phase 1 | Complete |
| GSD-01 | Phase 2 | Pending |
| GSD-02 | Phase 2 | Pending |
| GSD-03 | Phase 2 | Pending |
| GSD-04 | Phase 2 | Pending |
| APP-01 | Phase 3 | Pending |
| APP-02 | Phase 3 | Pending |
| APP-03 | Phase 3 | Pending |
| APP-04 | Phase 3 | Pending |
| DASH-01 | Phase 4 | Pending |
| DASH-02 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0

---
*Requirements defined: 2026-03-20*
*Last updated: 2026-03-20 after roadmap creation — all 14 requirements mapped*
