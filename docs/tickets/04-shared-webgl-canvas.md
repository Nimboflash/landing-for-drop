# 04 — Shared WebGL background canvas with mode state machine

**What to build:** The single fixed background canvas (`BackgroundCanvas` + R3F) that all shader scenes share, driven by the scene state machine's `backgroundMode` (`offWhiteGlow`, `greenGrid`, `pixelA`, `wavyDots`, `pixelB`, `monoMesh`, `footerLight`). Ships with the two simplest modes real (`offWhiteGlow` — the thesis scene's bottom glow in DROP orange/purple energy; `greenGrid` — the dark forest-green square grid) and stub uniforms for the rest. Demo: scrolling the shell swaps live background modes at the right scene boundaries.

**Blocked by:** 03 — Immersive shell.

**Status:** ready-for-agent

**Contract note:** the loader (ticket 05) is the one sanctioned exception to the shared canvas — the brief requires the DOM page mounted *beneath* the loader, so the loader renders on its own temporary overlay canvas that unmounts after the portal completes. This background canvas has no loader mode and stays behind the DOM at all times.

- [ ] Exactly one *persistent* WebGL context, fixed behind the DOM, `aria-hidden="true"`; DOM content remains semantic above it (the loader's temporary overlay canvas in ticket 05 is the only exception, and it never coexists with a second persistent context after entry)
- [ ] Mode transitions driven by scene-state seam output; shader uniforms receive scene progress (unit tests at the seam assert mode-per-scene mapping, including reverse scroll)
- [ ] DPR capped per quality tier (1.75–2 / 1.5 / 1); textures/geometries/materials disposed on unmount
- [ ] WebGL context-creation failure and context-loss produce the non-WebGL fallback (styled static backgrounds), not a blank or broken page — covered by a Playwright test with WebGL disabled
- [ ] Reduced motion: static backgrounds with brief crossfades
- [ ] `offWhiteGlow` glow expands/contracts with thesis progress; `[manual]` AA contrast maintained over the glow — sampled contrast measurement on worst-case frames, evidence in PR (Lighthouse can't see text over canvas)
- [ ] `greenGrid` renders the quiet square grid in `#102b19`/`#245236`; grid cell size exposed for pixel-transition alignment
- [ ] No WebGL warnings or console errors across a full scroll pass
