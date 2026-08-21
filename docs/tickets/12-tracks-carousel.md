# 12 — Tracks: jewel-case coverflow carousel

**What to build:** The music edit over the Monochrome Mesh: large `TRACKS` heading, transparent CD jewel cases in a coverflow field (up to 5 positions on desktop, 3 on tablet, swipe-first on mobile), each track's artwork clipped onto the circular disc inside the clear case with restrained reflections and micro-motion. Active case centered/largest/brightest with title, artist, and optional time-of-day group label beneath. Scroll advances the pinned carousel; drag/swipe, visible arrow buttons, and keyboard arrows all work. W04's 11 tracks render from data. (The scene's entrance beat after Pixel B is owned by ticket 11; the assembled hand-off is verified in 15 — Hardening.)

**Blocked by:** 03 — Immersive shell; 10 — Monochrome Mesh mode. (Runs parallel to the 08→09→11 film arc.)

**Status:** ready-for-agent

- [ ] Artwork sits on the disc surface (circular clip), not as a square card above it; missing artwork falls back to a branded DROP placeholder texture, never a broken image
- [ ] All four input methods work: scroll, drag/swipe, arrow buttons, keyboard arrows — all routed as events through the seam-2 reducer (most recent input wins), so active-index behavior after mixed inputs is unit-testable; `[manual]` snapping feels clean, not like a stock component-library carousel
- [ ] Arrow controls keyboard-accessible with visible focus states and accessible labels
- [ ] Item count and scroll budget fully data-driven (`max(340vh, trackCount * 55vh)` starting point, sensible cap) — seam-2 tests assert count-driven slots/indices against both W04 (11 tracks) and the ticket-01 variable-count fixture; `[manual]` coverflow position/scale/dim adaptation checked visually
- [ ] Title first, artist second, optional group label third under the active case; text syncs with position changes
- [ ] No audio autoplay; optional click opens configured external source in a new tab safely (`rel="noopener"`, announced as external) only when a `sourceUrl` exists in data
- [ ] Reverse scroll steps backward through tracks symmetrically
- [ ] Reduced motion: the carousel keeps its coverflow presentation but steps by non-animated crossfade — all four input methods still work and all tracks remain reachable (no content or capability removed)
- [ ] Playwright: 11 slides from data, keyboard traversal end-to-end, active-track text assertions
