# 05 — Loader: material logo and O portal

**What to build:** The entry experience: the full DROP logo as one near-black, glossy, living 3D material (slow surface displacement, traveling highlights, soft irregularity) on off-white; the O aperture pulses between ~0.84 and ~1.08 of resting inner radius, then expands beyond the viewport as a screen-space mask revealing the hero beneath — no hard cut. Total ~3.2s after critical assets, hard cap 4s.

**Blocked by:** 02 — Brand geometry (logo forms, `DropO` aperture); 03 — Immersive shell (mounts over the shell; no-header-during-loader rule). (Not blocked by 04: per the contract note there, the loader renders `DropLogoMaterial3D` on its own temporary overlay canvas above the DOM — the brief's "shared canvas where possible" exception — so it can run parallel to 04.)

**Status:** ready-for-agent

- [ ] All four modules (D, R, O, P) share one living material — recognizably the final DROP geometry, not four unrelated blocks or a flat image
- [ ] O pulse visible; O expansion acts as the portal mask; DOM page mounted beneath throughout (no layout jump when the loader ends)
- [ ] Loader's overlay canvas fully unmounts and disposes after the portal completes — exactly one persistent WebGL context remains (the ticket-04 background canvas)
- [ ] Loader never exceeds 4s waiting for noncritical media; first hard visit plays full version, internal route navigation uses the short mask transition instead
- [ ] Reduced motion: static logo 500–700ms, then simple O-shaped crossfade
- [ ] No-WebGL fallback: brief static logo + crossfade (page remains reachable)
- [ ] No header during the loader; header appears from hero onward
- [ ] Playwright: page content accessible after loader on normal, reduced-motion, and WebGL-disabled runs; zero console errors
