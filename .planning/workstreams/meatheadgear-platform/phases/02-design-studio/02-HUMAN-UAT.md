---
status: partial
phase: 02-design-studio
source: [02-VERIFICATION.md]
started: 2026-03-25T22:00:00Z
updated: 2026-03-25T22:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. AI Generation Speed and Quality
expected: Type "angry gorilla lifting weights" -> design appears on canvas in <15s with transparent background
result: [pending]

### 2. Ideogram Text Routing
expected: Type "gym shirt that says NO DAYS OFF in bold letters" -> legible text rendered (Ideogram v3 routed)
result: [pending]

### 3. Background Removal and Upscaling
expected: Generated design has transparent background, local file at .data/designs/{user_id}/{design_id}.png at 4x resolution
result: [pending]

### 4. Canvas Interaction
expected: Design on canvas can be dragged, resized via red corner handles, rotated. Fit/Center/Reset buttons work.
result: [pending]

### 5. Printful Mockup Generation
expected: With PRINTFUL_API_KEY configured and product selected, GENERATE MOCKUP shows photorealistic product photo
result: [pending]

### 6. Upload Own Image
expected: Upload PNG -> design appears on canvas, My Designs gallery shows uploaded design with status 'draft'
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
