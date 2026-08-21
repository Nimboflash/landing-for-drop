# 03 — Immersive shell: scene state machine, smooth scroll, header

**What to build:** The `ImmersiveLensPage` shell that turns the ticket-01 static page into a scrollable scene sequence: Lenis + GSAP/ScrollTrigger wired together, a page-level scene state machine (`SceneId` union from the spec) that maps scroll progress to active scene + per-scene progress, placeholder scene sections in the exact brief order, the persistent top-left header logo (black/white per scene), and the reduced-motion + quality-tier utilities every later scene will consume. Demo: scrolling forward and backward walks all ten scenes in order with the header adapting, at plain-DOM fidelity.

**Blocked by:** 01 — Foundation; 02 — Brand geometry (header consumes `DropWordmark`).

**Status:** ready-for-agent

- [ ] Scene-state seam established as the reducer defined in `docs/BUILD-GUIDE.md`: `(state, inputEvent) → state` with output `{sceneId, sceneProgress, backgroundMode, transitionState}`; one-way data flow (ScrollTriggers feed the reducer, scenes render only from its output); unit tests prove scene ordering, mode mapping, and symmetric stepping — ordinal assertions only, no absolute progress thresholds
- [ ] Lenis integrated with GSAP's RAF (single ticker, no competing scroll engines); `[manual]` no scroll-jacking — wheel/touch momentum feels respected
- [ ] All ten scenes present as pinned/flowing placeholder sections with brief-specified approximate scroll budgets; tracks budget derives from track count
- [ ] Header: small DROP logo fixed top-left from hero onward, none during loader, top-right empty, contrast variant switches per scene, never intercepts scroll on mobile
- [ ] `prefers-reduced-motion` utility and quality-tier detection (`high`/`medium`/`low`) available and unit-tested
- [ ] ScrollTriggers recalculate after fonts/assets load and are killed on unmount/route change (Playwright: navigate away and back → no console errors, forward/reverse scroll produces identical states, and the dev-only diagnostics trigger count — see BUILD-GUIDE's escape hatch — hasn't grown)
- [ ] Page seam test: scene sections appear in brief order; reverse scroll returns to the top cleanly
