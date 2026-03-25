# Phase 2: Design Studio - Context

**Gathered:** 2026-03-24 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Customer types a prompt → AI generates a design → they place it on a product → see a realistic mockup. Includes background removal, upscaling to print-ready resolution, Fabric.js canvas editor for positioning, mockup generation, own-upload alternative, and saving designs to account.

Requirements: DES-01 through DES-09.

</domain>

<decisions>
## Implementation Decisions

### AI Generation Provider (fal.ai)
- **D-01:** Replace existing multi-provider `services/image_gen.py` (OpenAI/Ideogram/Recraft direct calls) with fal.ai as single vendor using the `fal-client` Python SDK (`pip install fal-client`)
- **D-02:** Authentication via `FAL_KEY` environment variable (SDK reads it automatically; raw HTTP uses `Authorization: Key <FAL_KEY>` header)
- **D-03:** Use queue-based `fal_client.subscribe()` for production reliability (auto-polls, handles retries, supports `on_queue_update` callback for progress tracking)
- **D-04:** Model identifiers:
  - Flux 1.1 Pro (graphics): `fal-ai/flux-pro/v1.1`
  - Ideogram v3 (text/slogans): `fal-ai/ideogram/v3`
  - BiRefNet v2 (background removal): `fal-ai/birefnet/v2`
  - Real-ESRGAN (upscaling): `fal-ai/esrgan`
- **D-05:** Replace Claid.ai upscaling in `services/image_pipeline.py` with fal.ai Real-ESRGAN (~$0.005/image for 4x upscale)

### Prompt Routing
- **D-06:** Detect text/slogan intent in customer prompt (keywords like quotes, slogans, text patterns) and route to Ideogram v3 for superior text rendering; default route is Flux 1.1 Pro for graphics

### Canvas Editor (Fabric.js)
- **D-07:** Load Fabric.js v6 via CDN `<script>` tag: `https://cdn.jsdelivr.net/npm/fabric@6.4.3/dist/index.min.js` — no module bundler, matches the vanilla JS convention
- **D-08:** Use `fabric.FabricImage.fromURL()` to add generated/uploaded designs to canvas; built-in resize/rotate/move handles are automatic with `fabric.Canvas`
- **D-09:** Canvas shows a flat product template image (garment silhouette) for design positioning — NOT a photorealistic 3D preview during editing. The mockup is generated as a separate final step after user confirms placement.
- **D-10:** Export canvas as PNG via `canvas.toDataURL({ format: 'png', multiplier: 2 })` for the mockup submission

### Mockup Generation
- **D-11:** Use Printful's built-in Mockup Generator API (free, tied to product catalog, already partially implemented in `services/image_pipeline.py`) instead of Dynamic Mockups API ($15/mo, unnecessary for a Printful-based POD workflow)
- **D-12:** Mockup flow: canvas export → submit to Printful mockup generator with product_id + placement coordinates → poll for result → display photorealistic preview

### File Storage & Persistence
- **D-13:** Download fal.ai result images immediately after generation (URLs expire after 7 days by default) and store locally at `apps/meatheadgear/.data/designs/{user_id}/{design_id}.png`
- **D-14:** User uploads (DES-08) stored in same local directory structure, served via FastAPI StaticFiles mount
- **D-15:** `designs` SQLite table tracks: design_id, user_id, prompt, provider_model, image_path, created_at, mockup_path
- **D-16:** Design saved to user account (DES-09) means a row in `designs` table + file on disk — reusable from "My Designs" gallery

### Frontend Integration
- **D-17:** New "Design Studio" page/section in the SPA — reached from product detail "Design It" CTA button
- **D-18:** Flow: select product → enter prompt (or upload image) → view generated design → place on canvas → generate mockup → proceed to checkout (Phase 3)
- **D-19:** Show generation progress via fal.ai queue status callbacks (Queued → InProgress → Completed)

### Configuration
- **D-20:** Add `FAL_KEY` to `config.py` frozen dataclass and `.env.example`
- **D-21:** Remove `OPENAI_API_KEY`, `IDEOGRAM_API_KEY`, `RECRAFT_API_KEY`, `CLAID_API_KEY` from MeatheadGear config (consolidate to single vendor)

### Claude's Discretion
- Exact prompt routing heuristics (keyword list vs. LLM classification for text detection)
- Canvas UI layout and control styling (dark theme matching brand)
- Design gallery grid layout and pagination
- Error states for generation failures (retry UX, fallback messaging)
- Garment template image sourcing (Printful product images or custom silhouettes)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Requirements
- `.planning/workstreams/meatheadgear-platform/REQUIREMENTS.md` — DES-01 through DES-09 requirement specs

### Project Research
- `.planning/research/AI-DESIGN.md` — AI generation vendor comparison, fal.ai model details, pricing, pipeline architecture
- `.planning/research/POD-SERVICES.md` — Printful API details, mockup generator docs

### Prior Phase Context
- `.planning/workstreams/meatheadgear-platform/phases/01-store-foundation/01-CONTEXT.md` — App structure, frontend conventions, auth patterns, database patterns

### Existing Implementation (to modify/extend)
- `apps/meatheadgear/services/image_gen.py` — Current multi-provider image generation (replace with fal.ai)
- `apps/meatheadgear/services/image_pipeline.py` — Current pipeline with Claid.ai upscaling + Printful mockup generator (refactor)
- `apps/meatheadgear/models_design.py` — Existing Design/DesignAsset dataclasses
- `apps/meatheadgear/config.py` — Settings dataclass (add FAL_KEY, remove old API keys)
- `apps/meatheadgear/frontend/index.html` — SPA shell (add design studio section)
- `apps/meatheadgear/frontend/app.js` — Frontend logic (add canvas, generation, upload functions)
- `apps/meatheadgear/frontend/style.css` — Brand styles (extend for design studio)

### External Documentation
- fal.ai Python SDK: `pip install fal-client`, auth via FAL_KEY env var
- fal.ai queue API: `fal_client.subscribe()` with `on_queue_update` callback
- Fabric.js v6 CDN: `https://cdn.jsdelivr.net/npm/fabric@6.4.3/dist/index.min.js`
- Fabric.js v6 class names: `FabricImage` (not `Image`), `FabricText` (not `Text`)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/image_gen.py` — Has `_select_provider()` routing logic and `PROVIDER_COSTS` dict; architecture can be adapted for fal.ai model routing (Flux vs Ideogram)
- `services/image_pipeline.py` — Has `generate_mockup()` with Printful API polling (lines 208-275); reuse for DES-07 mockup generation
- `models_design.py` — `Design` dataclass with `image_url`, `prompt`, `style`, `provider` fields; extend for canvas placement data and local file paths
- `models_wallet.py` — `WalletTransaction` pattern for tracking per-design generation costs
- `frontend/app.js` — 14 existing functions (init, auth, products, filters); same SPA pattern for design studio functions

### Established Patterns
- All services use `httpx.AsyncClient` for HTTP calls — fal.ai SDK is sync but has async mode via `fal_client.subscribe()` which is compatible
- Config via frozen dataclass from `.env` — add FAL_KEY following existing pattern
- Frontend: vanilla JS, DOM manipulation, fetch API, no build step — Fabric.js CDN fits this pattern
- Database: raw SQL via aiosqlite (no ORM) — add `designs` table with same pattern as `products`

### Integration Points
- Product detail page "Design It" button → new design studio flow
- Auth system (JWT) — design studio requires login, designs tied to user_id
- Product catalog data — canvas needs product template images from catalog
- Printful product_id — needed for mockup generator API call
- `.data/` directory — designs stored alongside `meatheadgear.db`

</code_context>

<specifics>
## Specific Ideas

- Generation cost ~$0.05/design (Flux) or ~$0.01/design (Ideogram) — track in wallet system
- Background removal should be automatic (no user toggle) — clean design on transparent background
- Upscaling should be automatic for print-ready quality (300 DPI at print area size)
- Canvas should show a product-appropriate print area guide (e.g., chest area for t-shirt)
- "My Designs" gallery accessible from nav — shows all saved designs with reuse option

</specifics>

<deferred>
## Deferred Ideas

- Design templates library (pre-made edgy gym templates) — v2 requirement DES-10
- LoRA fine-tuning on MeatheadGear brand style — v2 requirement DES-11
- Dynamic Mockups API for premium/lifestyle/marketing mockups — future enhancement if needed
- Style transfer / design variations from existing design — future feature
- Collaborative design sharing between users — future feature

</deferred>

---
*Phase: 02-design-studio*
*Context gathered: 2026-03-24 via assumptions mode with external research*
