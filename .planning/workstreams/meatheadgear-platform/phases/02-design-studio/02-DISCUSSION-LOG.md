# Phase 2: Design Studio - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-03-24
**Phase:** 02-design-studio
**Mode:** assumptions (--auto)
**Areas analyzed:** AI Generation Provider, Canvas Editor, Mockup Generation, File Storage & Persistence

## Assumptions Presented

### AI Generation Provider (fal.ai)
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Replace multi-provider image_gen.py with fal.ai single vendor | Confident | `services/image_gen.py` lines 140-247 (OpenAI/Ideogram/Recraft); `config.py` lines 34-37 (separate API keys); PROJECT.md fal.ai decision |
| Replace Claid.ai upscaling with fal.ai Real-ESRGAN | Confident | `services/image_pipeline.py` line 41 (Claid.ai API call); AI-DESIGN.md lines 295-299 (ESRGAN recommendation) |

### Canvas Editor (Fabric.js)
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Fabric.js v6 via CDN script tag (no bundler) | Likely → Confident (after research) | Phase 01 CONTEXT.md line 56-59 (vanilla JS convention); `frontend/index.html` line 274 (single script, no bundler) |
| Flat product template on canvas, mockup as final step | Likely | `image_pipeline.py` line 208 (`generate_mockup()` is async with polling); DES-05/06 vs DES-07 requirement separation |

### Mockup Generation
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Use Printful mockup generator vs Dynamic Mockups API | Unclear → Confident (after research) | `image_pipeline.py` lines 208-275 (existing Printful integration); ROADMAP.md says "Dynamic Mockups API" |

### File Storage & Persistence
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Local filesystem storage, download fal.ai results immediately | Likely → Confident (after research) | `database.py` line 16 (SQLite at `.data/`); no cloud storage deps in requirements.txt; fal.ai URLs expire in 7 days |

## Corrections Made

No corrections — all assumptions confirmed (auto mode).

## Auto-Resolved

- **Mockup Generation**: auto-selected "Keep Printful mockup generator" (free, product-tied, already integrated) over Dynamic Mockups API ($15/mo, unnecessary for Printful POD workflow). Research confirmed Printful API is free and includes 2,550+ product-specific templates.

## External Research

- **fal.ai SDK**: Python SDK is `fal-client` (`pip install fal-client`), auth via `FAL_KEY` env var, queue-based `subscribe()` for production. All 4 models confirmed available. (Source: fal.ai docs)
- **Dynamic Mockups API**: REST API, $15/mo Pro plan required for watermark-free renders, 1 credit per render. Printful's free mockup API is better fit for POD workflow. (Source: dynamicmockups.com/pricing)
- **Fabric.js v6 CDN**: Available at `jsdelivr.net/npm/fabric@6.4.3/dist/index.min.js`, exposes global `fabric` object, `FabricImage` class, built-in resize/rotate controls. (Source: fabricjs.com docs, GitHub README)
- **fal.ai URL expiration**: 7-day default retention, configurable via `X-Fal-Object-Lifecycle-Preference` header, download-immediately pattern recommended. (Source: fal.ai media expiration docs)
