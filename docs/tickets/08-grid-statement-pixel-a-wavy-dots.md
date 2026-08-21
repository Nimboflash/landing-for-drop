# 08 — Grid statement, Pixel transition A, Wavy Dots

**What to build:** The first full shader transition arc: the dark-green grid scene pins with its single centered statement (from data), then a scroll-driven, reversible pixel mosaic — cells aligned to the background grid, seeded thresholds, bottom-weighted irregular stepped skyline — replaces the grid with the live Wavy Dots film background (MetalForge preset rebuilt in GLSL: white dots on black, `horizon: -0.45`, vignette, depth fade). The statement fades between ~20–55% of replacement progress.

**Blocked by:** 04 — Shared WebGL canvas (`greenGrid` mode, cell-size contract).

**Status:** ready-for-agent

- [ ] Grid scene: one centered statement only — no form, button, arrows, handwriting, social icons, imagery, or floating UI (the Zero University reference's furniture is explicitly excluded)
- [ ] Statement reveals once via clean mask/opacity+y; scene pins briefly
- [ ] Pixel A is a shared-canvas mosaic (WebGL preferred; DOM grid only if provably smooth): stable random seed, bottom-weighted threshold field, old grid visible until each cell is replaced — not a wipe, blur, crossfade, or gradient dissolve
- [ ] Reverse scroll restores the exact prior grid state (seeded determinism asserted at the scene-state seam; visual state asserted in Playwright)
- [ ] Wavy Dots fully active at 100%; restrained (never fights text); rebuilt in GLSL — no MetalForge embed, no video
- [ ] Reduced motion: static grid → brief crossfade → static dots field
- [ ] 60fps target on capable desktop through the whole transition; no console/WebGL warnings
