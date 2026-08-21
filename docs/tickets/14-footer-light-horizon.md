# 14 — Footer: outline wordmark and prismatic light horizon

**What to build:** The final scene: the Mesh loses contrast and fades to pure black (using the fade variant from ticket 10); a very large outline `DROP` wordmark (exact brand geometry, thin dark outline, subtle not high-contrast) spans the lower half; a real-time prismatic light horizon — bright white core, blue/cyan edge, restrained orange/purple spectral fringes — curves and drifts across the letters, briefly illuminating the outline sections it passes. Scroll controls the reveal and vertical drift; pointer adds subtle local distortion on desktop; the effect stays alive without input. Footer content (statement, disabled CTA, placeholder metadata slots) renders from data. (The Art→Footer fade hand-off across the scene boundary is verified in 15 — Hardening.)

**Blocked by:** 02 — Brand geometry (wordmark outline); 10 — Monochrome Mesh mode (fade-to-black variant). (Runs parallel to 12/13.)

**Status:** ready-for-agent

- [ ] Light is real-time WebGL/GLSL (`footerLight` mode on the shared canvas) — no screenshot, GIF, or video
- [ ] Outline uses the exact DROP wordmark character (from ticket 02 geometry), rendered as thin outline, not solid fill
- [ ] Mesh→black fade is gradual; footer is not a separate white card or generic site footer
- [ ] Closing statement from data; CTA present but disabled until final copy/action supplied
- [ ] All five brief-specified metadata slots render as non-interactive labeled placeholders: Instagram, location, contact, **copyright**, legal — the mock pack ships only four links, so add a disabled copyright placeholder to the repo's content copy (recorded data-pack gap); slot count from data, never hardcoded
- [ ] No invented destinations anywhere
- [ ] Header logo may hide during the largest word reveal; wordmark may overflow horizontally on mobile but `DROP` stays recognizable
- [ ] Reduced motion: static blurred gradient ribbon + simple outline reveal
- [ ] Pointer distortion desktop-only; effect animates without pointer input
- [ ] Playwright: footer statement/slots from data, disabled links not focusable-as-links, reduced-motion variant renders
