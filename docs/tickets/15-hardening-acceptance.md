# 15 — Hardening: integration, full acceptance pass, QA matrix, performance

**What to build:** The release-candidate pass over the assembled experience: the cross-scene hand-offs no single ticket owns (Pixel B dark beat → Tracks entrance; uncut Tracks→Art mesh continuity; Art→Footer fade), every brief Section 19 acceptance criterion verified, the full Section 21 QA matrix executed, scene pacing budgets tuned by feel, performance tiers profiled, and the automated suite completed for whole-journey flows.

**Blocked by:** 05 — Loader; 06 — Thesis; 07 — Menu deck; 09 — Films; 11 — Pixel B; 12 — Tracks; 13 — Art Pieces; 14 — Footer.

**Status:** ready-for-agent

- [ ] Scene hand-offs assembled and verified: dark beat precedes Tracks entrance after Pixel B; Monochrome Mesh continues without restart or cut from Tracks through Art Pieces; Mesh contrast-fade into the footer black — forward and reverse
- [ ] Full-journey Playwright specs: forward scroll through all ten scenes, full reverse scroll, rapid scroll, resize mid-scene, refresh at `/lens/beautiful-imperfection`, back-navigation — zero console errors, no stuck pins or dead zones
- [ ] Reduced-motion e2e covers the entire journey; no content lost; keyboard-only pass completes
- [ ] QA matrix rows all executed and recorded in the PR: Browsers (Chrome, Safari, Firefox, iOS Safari) × Viewports (375×812, 768×1024, 1024×768, 1440×900) × Input (mouse/trackpad/touch/keyboard) × Motion (forward/reverse/rapid/resize) × **Content** (2 menu items, 3 films, variable track count via the fixture lens, 4 Art Pieces, schema minimums render gracefully) × **Rights** (approved vs. rights-pending vs. replace-with-final vs. development-mock states behave per the brief) × Routes
- [ ] Rights-state behavior: rights-pending assets display only in development/staging behind an explicit internal flag; production fails/warns loudly on required `replace-with-final` assets; production fails while any asset is `development-mock` or `productionAllowed: false` (verified in CI as the expected current state); `contentMode: "development-mock"` visible in dev diagnostics
- [ ] Accessibility: semantic headings/landmarks, localized alt text everywhere, AA contrast, no flashing, external links announced and opened safely; Lighthouse a11y ≥ 95, best practices ≥ 90, mobile performance ≥ 75, CLS < 0.1
- [ ] Performance: DPR caps honored per tier, texture memory bounded, triggers cleaned up across route changes, context-loss fallback exercised; 60fps capable desktop / ≥30fps mid-range mobile on the heaviest scenes
- [ ] Scroll budgets tuned by feel against the brief's rhythm criterion; final values documented
- [ ] Brief Section 23 build contract checklist walked and checked off item by item in the PR description
