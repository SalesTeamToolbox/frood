---
phase: quick
plan: 260407-hww
type: execute
wave: 1
depends_on: []
files_modified:
  - dashboard/frontend/dist/app.js
  - .planning/workstreams/frood-dashboard/REQUIREMENTS.md
autonomous: true
requirements: [CLEAN-02, STRIP-09]
must_haves:
  truths:
    - "loadAll() runs without ReferenceError on startup"
    - "Tools page renders without ReferenceError on _CODE_ONLY_TOOLS"
    - "updateGsdIndicator calls do not throw ReferenceError at any call site"
    - "No dead renderDetail() harness code remains in app.js"
    - "REQUIREMENTS.md CLEAN-02 is marked as done"
  artifacts:
    - path: "dashboard/frontend/dist/app.js"
      provides: "Clean SPA with no undefined harness function references"
    - path: ".planning/workstreams/frood-dashboard/REQUIREMENTS.md"
      provides: "CLEAN-02 checked off"
  key_links:
    - from: "app.js loadAll()"
      to: "Promise.all array"
      via: "No loadGsdWorkstreams call"
      pattern: "Promise\\.all\\(\\[.*loadTools.*loadApps"
    - from: "app.js renderTools()"
      to: "category assignment"
      via: "Static 'general' category instead of _CODE_ONLY_TOOLS"
      pattern: "var category = .general."
---

<objective>
Fix 3 blocker-level JavaScript ReferenceErrors in app.js left behind by Phase 50 strip, plus remove the dead renderDetail() harness block and associated dead helpers. Update REQUIREMENTS.md to mark CLEAN-02 complete.

Purpose: The dashboard is currently non-functional at runtime because loadAll() crashes on startup (loadGsdWorkstreams undefined), the Tools page crashes (_CODE_ONLY_TOOLS undefined), and updateGsdIndicator calls throw at 4 sites. These are all call sites to functions whose definitions were deleted in Phase 50-02 but whose call sites were missed.

Output: A working app.js with zero undefined harness function references, and REQUIREMENTS.md updated.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@dashboard/frontend/dist/app.js
@.planning/workstreams/frood-dashboard/phases/50-strip-harness-features/50-VERIFICATION.md
@.planning/workstreams/frood-dashboard/REQUIREMENTS.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Remove 3 blocker call sites and dead renderDetail block from app.js</name>
  <files>dashboard/frontend/dist/app.js</files>
  <action>
Make these targeted edits to dashboard/frontend/dist/app.js:

1. **Remove loadGsdWorkstreams() from loadAll() at line 2142.** The current Promise.all array is:
   ```
   loadTools(), loadSkills(), loadChannels(), loadProviders(),
   loadHealth(), loadApiKeys(), loadEnvSettings(), loadStorageStatus(), loadTokenStats(), loadGsdWorkstreams(),
   loadApps(), loadReports(),
   ```
   Remove `, loadGsdWorkstreams()` from that line so it becomes:
   ```
   loadTools(), loadSkills(), loadChannels(), loadProviders(),
   loadHealth(), loadApiKeys(), loadEnvSettings(), loadStorageStatus(), loadTokenStats(),
   loadApps(), loadReports(),
   ```

2. **Replace _CODE_ONLY_TOOLS.has() in renderTools() at line 1124.** Change:
   ```
   var category = _CODE_ONLY_TOOLS.has(t.name) ? "code" : "general";
   ```
   to:
   ```
   var category = "general";
   ```
   The _CODE_ONLY_TOOLS constant was deleted. All remaining tools are intelligence-layer tools, so "general" is the correct static category. Keep the catBadge rendering on the next lines as-is (it will just always show "general").

3. **Remove all 4 updateGsdIndicator() call sites:**
   - Line 160: `loadAll().then(function() { render(); updateGsdIndicator(); });` — change to `loadAll().then(function() { render(); });`
   - Line 306: standalone `updateGsdIndicator();` after `render();` — delete the entire line
   - Line 474: standalone `updateGsdIndicator();` inside handleWSMessage system_health case — delete the entire line. The system_health case block will become empty braces `if (msg.type === "system_health") { }` which is fine but cleaner to remove the entire system_health branch. Change the block so system_health is simply not handled: remove the `if (msg.type === "system_health") { ... } else` prefix so handleWSMessage starts directly with `if (msg.type === "app_status")`.
   - Line 2237: standalone `updateGsdIndicator();` after `render();` in DOMContentLoaded — delete the entire line

4. **Delete the dead renderDetail() function block (lines 981-1097).** This is an unreachable harness function (not in the renderers map) that references 10+ deleted functions (doApproveTask, showReviewModal, doCancelTask, doRetryTask, viewTeamRun, doSetPriority, doBlockTask, doUnblockTask, doArchiveTask). Delete the entire function from its opening `function renderDetail() {` to its closing `}` on line 1097.

5. **Delete the dead submitComment() function (lines 1099-1105).** Only called from renderDetail HTML template. Delete the entire function.

6. **Delete the dead promptBlock() function (lines 1107-1110).** Only called from renderDetail HTML template. Delete the entire function.

DO NOT delete STATUS_FLAVOR (lines 73-83) — it is used by statusBadge() at line 955 which is called throughout the app.
DO NOT delete statusBadge() or timeSince() or formatNumber() — they are used by kept renderers.
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && node -e "const fs=require('fs'); const code=fs.readFileSync('dashboard/frontend/dist/app.js','utf8'); const errors=[]; if(code.includes('loadGsdWorkstreams')) errors.push('loadGsdWorkstreams still present'); if(code.includes('updateGsdIndicator')) errors.push('updateGsdIndicator still present'); if(code.includes('_CODE_ONLY_TOOLS')) errors.push('_CODE_ONLY_TOOLS still present'); if(code.includes('renderDetail')) errors.push('renderDetail still present'); if(code.includes('submitComment')) errors.push('submitComment still present'); if(code.includes('promptBlock')) errors.push('promptBlock still present'); if(!code.includes('STATUS_FLAVOR')) errors.push('STATUS_FLAVOR was accidentally deleted'); if(!code.includes('statusBadge')) errors.push('statusBadge was accidentally deleted'); if(errors.length) { console.error('FAIL:', errors.join(', ')); process.exit(1); } else { console.log('PASS: all harness call sites removed, kept functions preserved'); }"</automated>
  </verify>
  <done>
    - loadGsdWorkstreams() removed from loadAll() Promise.all
    - _CODE_ONLY_TOOLS.has() replaced with static "general" in renderTools()
    - All 4 updateGsdIndicator() call sites removed
    - renderDetail() function block deleted (lines 981-1097)
    - submitComment() and promptBlock() dead helpers deleted
    - STATUS_FLAVOR, statusBadge, timeSince, formatNumber all preserved
    - No JavaScript syntax errors in the file (node -c check passes)
  </done>
</task>

<task type="auto">
  <name>Task 2: Mark CLEAN-02 complete in REQUIREMENTS.md</name>
  <files>.planning/workstreams/frood-dashboard/REQUIREMENTS.md</files>
  <action>
In `.planning/workstreams/frood-dashboard/REQUIREMENTS.md` at line 39, change:
```
- [ ] **CLEAN-02**: Remove dead frontend code for stripped pages/components
```
to:
```
- [x] **CLEAN-02**: Remove dead frontend code for stripped pages/components
```

This was already claimed and largely executed by plan 50-02 but the checkbox was never updated. With Task 1 completing the remaining call-site removals, this requirement is now fully satisfied.
  </action>
  <verify>
    <automated>cd C:/Users/rickw/projects/agent42 && node -e "const fs=require('fs'); const content=fs.readFileSync('.planning/workstreams/frood-dashboard/REQUIREMENTS.md','utf8'); if(content.includes('- [x] **CLEAN-02**')) { console.log('PASS: CLEAN-02 marked done'); } else { console.error('FAIL: CLEAN-02 not checked'); process.exit(1); }"</automated>
  </verify>
  <done>CLEAN-02 checkbox changed from [ ] to [x] in REQUIREMENTS.md</done>
</task>

</tasks>

<verification>
1. `node -c dashboard/frontend/dist/app.js` — JavaScript syntax check passes (no parse errors)
2. Grep for all removed symbols returns 0 matches: `grep -cE "loadGsdWorkstreams|updateGsdIndicator|_CODE_ONLY_TOOLS|renderDetail|submitComment|promptBlock" dashboard/frontend/dist/app.js` should return 0
3. Grep for kept symbols confirms they exist: `grep -c "STATUS_FLAVOR\|statusBadge\|renderTools\|renderApps\|loadAll" dashboard/frontend/dist/app.js` should return >0 for each
4. REQUIREMENTS.md shows `[x]` for CLEAN-02
</verification>

<success_criteria>
- app.js has zero references to loadGsdWorkstreams, updateGsdIndicator, _CODE_ONLY_TOOLS, renderDetail, submitComment, or promptBlock
- app.js passes `node -c` syntax check
- renderTools() uses static "general" category
- loadAll() Promise.all contains only intelligence-layer load functions
- REQUIREMENTS.md CLEAN-02 is checked
- All 3 verification gaps from 50-VERIFICATION.md are resolved
</success_criteria>

<output>
After completion, create `.planning/quick/260407-hww-fix-3-app-js-gaps-from-phase-50-verifica/260407-hww-SUMMARY.md`
</output>
