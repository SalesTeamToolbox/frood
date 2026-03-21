---
phase: 01-store-foundation
plan: 03
subsystem: meatheadgear/catalog
tags: [catalog, printful, pricing, sync, api]
dependency_graph:
  requires: ["01-01"]
  provides: ["catalog-sync", "pricing-engine", "product-api"]
  affects: ["apps/meatheadgear/services/", "apps/meatheadgear/routers/catalog.py", "apps/meatheadgear/main.py"]
tech_stack:
  added: ["httpx async client for Printful API v2", "aiosqlite upsert via ON CONFLICT DO UPDATE"]
  patterns: ["graceful degradation when API key absent", "runtime DB_PATH access for test isolation", "TDD red-green cycle"]
key_files:
  created:
    - apps/meatheadgear/services/pricing.py
    - apps/meatheadgear/services/printful.py
    - apps/meatheadgear/services/catalog.py
    - apps/meatheadgear/routers/catalog.py
    - apps/meatheadgear/tests/test_catalog.py
  modified:
    - apps/meatheadgear/main.py (already updated by plan 02 in same wave)
decisions:
  - "Import database module (not DB_PATH value) in catalog.py so test patches work at runtime"
  - "Catalog endpoints return from local SQLite regardless of Printful API availability"
  - "sync_catalog() skips with warning when PRINTFUL_API_KEY is not set"
  - "Background sync tasks launched non-blocking via asyncio.create_task() in lifespan"
metrics:
  duration_minutes: 15
  completed_date: "2026-03-20"
  tasks_completed: 2
  files_created: 5
  files_modified: 1
requirements: ["CAT-01", "CAT-02", "CAT-04"]
---

# Phase 01 Plan 03: Printful Catalog Sync Summary

**One-liner:** Async Printful API v2 client + 35%-margin pricing engine + SQLite upsert sync + read-only product REST API.

## What Was Built

### Pricing Engine (`services/pricing.py`)
`calculate_retail_price(cost, margin=0.35)` implements the formula from CONTEXT.md:
- `retail = cost / (1 - margin)` — achieves 35% gross margin target
- Rounds UP to nearest $X.99 using `math.ceil()`
- Verified: 13.50 → 20.99 (35.7% margin), 9.49 → 14.99 (36.7%), 29.94 → 46.99 (36.3%)
- All calculated margins exceed the 30% floor requirement (CAT-04)

### Printful API Client (`services/printful.py`)
`PrintfulClient` using `httpx.AsyncClient` (non-blocking, per Agent42 conventions):
- `get_catalog_products()`: fetches catalog filtered to gym wear categories (T-shirts, Hoodies, Leggings, Shorts, Hats, Bags)
- `get_product_details(id)`: fetches variants with sizes, colors, pricing
- Handles HTTP 429 rate limit: returns empty list/None without crashing
- Handles network errors (`httpx.HTTPError`): logs and returns empty/None

### Catalog Sync Service (`services/catalog.py`)
`sync_catalog()` orchestration function:
- Checks `PRINTFUL_API_KEY` — skips with warning if not set (graceful degradation)
- Fetches products from PrintfulClient, fetches details for each
- Calculates retail prices via `calculate_retail_price()`
- Upserts products, variants, images using `ON CONFLICT ... DO UPDATE` (idempotent)
- `start_background_sync()` re-runs every 6 hours without blocking

### Product API Router (`routers/catalog.py`)
- `GET /api/catalog/products` — lists active products with `price_min`/`price_max` ranges, optional `?category=` substring filter
- `GET /api/catalog/products/{id}` — product detail with `variants` array (size, color, retail_price, in_stock) and `images` array
- Returns 404 for missing/inactive products
- All reads from local SQLite — works even when Printful is unreachable

### Application Entry (`main.py`)
Updated lifespan handler launches catalog sync non-blocking:
```python
asyncio.create_task(sync_catalog())       # Initial sync in background
asyncio.create_task(start_background_sync())  # Periodic 6h refresh
```

## Test Coverage

All tests follow TDD (RED → GREEN):

| Test Class | Tests | Coverage |
|---|---|---|
| `TestPricingEngine` | 5 | All pricing cases + margin floor verification |
| `TestPrintfulClient` | 4 | List products, product detail, 429 handling, network error |
| `TestCatalogSync` | 4 | Insert products, retail price calculation, empty response, upsert deduplication |
| `TestCatalogAPI` | 4 | Empty list, product detail with variants/images, 404, category filter |

**Total: 17 new tests, 37 total passing (0 failures)**

## Requirements Satisfied

- **CAT-01**: Product catalog synced from Printful API, stored in SQLite
- **CAT-02**: Each product has available sizes, colors, retail prices via API
- **CAT-04**: Retail prices at >=35% gross margin (floor 30%): `(retail - cost) / retail >= 0.30`
- Background sync: refreshes every 6 hours via `start_background_sync()`
- Graceful degradation: catalog API works from local DB when Printful is unreachable

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test isolation for database.DB_PATH patching**
- **Found during:** Task 2 (catalog sync tests)
- **Issue:** `catalog.py` imported `DB_PATH` at module load time (`from database import DB_PATH`). When tests patch `database.DB_PATH`, the catalog module still used the old value.
- **Fix:** Changed to `import database` (module import), then reference `database.DB_PATH` at call time inside `sync_catalog()` via `db_path = str(database.DB_PATH)`.
- **Files modified:** `apps/meatheadgear/services/catalog.py`
- **Commit:** 6eba81e

None other - plan executed with one bug fix for test isolation.

## Known Stubs

None. The pricing engine, Printful client, catalog sync, and API endpoints are fully implemented. Endpoints return empty results until the Printful API key is configured and the first sync runs — this is documented, intentional behavior (not a stub).

## Self-Check: PASSED

All created files exist on disk. All commits present in git history.

| Item | Status |
|---|---|
| `apps/meatheadgear/services/pricing.py` | FOUND |
| `apps/meatheadgear/services/printful.py` | FOUND |
| `apps/meatheadgear/services/catalog.py` | FOUND |
| `apps/meatheadgear/routers/catalog.py` | FOUND |
| `apps/meatheadgear/tests/test_catalog.py` | FOUND |
| `.planning/...01-03-SUMMARY.md` | FOUND |
| Commit c1bfbf3 (TDD RED tests) | FOUND |
| Commit 4e4fe74 (pricing + Printful client) | FOUND |
| Commit 6eba81e (catalog sync + router) | FOUND |
