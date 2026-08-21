# 10 — Monochrome Mesh background mode

**What to build:** The `monoMesh` mode on the shared canvas: the animated Monochrome Mesh rebuilt in GLSL from the brief's preset — 4×4 control-color grid (exact gray values from brief Section 7.8), mono style, smooth, `drift: 0.35`, animated — plus the mode's progress-driven variants the later scenes consume: normal (Tracks), slowed/darkened (Art Pieces), and contrast-fade-to-black (Footer entry). Demoable on the shell with the mode active and each variant switchable.

**Blocked by:** 04 — Shared WebGL canvas.

**Status:** ready-for-agent

- [ ] Mesh uses the brief's exact 4×4 control colors and preset parameters; rebuilt in GLSL — no MetalForge embed, no recorded video
- [ ] Runs as a background mode on the single shared canvas, driven by scene-state seam output
- [ ] The reducer's `transitionState` carries a declarative mesh variant descriptor (`"normal" | "reading" | "fadeToBlack"` + scalar) for the three consumer variants — normal, slowed+darkened (reading comfort), gradual contrast-loss fade to pure black; seam-2 tests assert the descriptor per scene/progress and its reversibility; the shader consumes the descriptor, and `[manual]` each variant's look is verified visually (uniform values are never asserted by reaching into materials)
- [ ] Respects quality tiers (subdivision/detail reduction on medium/low) and reduced motion (static mesh frame)
- [ ] No console/WebGL warnings; disposed cleanly on unmount
