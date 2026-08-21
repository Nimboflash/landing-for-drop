# 11 — Pixel transition B: films to music

**What to build:** The films→music passage: as film 03 completes, continued scroll fades the poster and description while a colored pixel mosaic (coordinates consistent with Pixel A) replaces Wavy Dots, passing through restrained DROP orange/purple energy, resolving into the Monochrome Mesh, holding a short empty dark beat at 100% before the Tracks scene enters.

**Blocked by:** 09 — Films scene; 10 — Monochrome Mesh mode.

**Status:** ready-for-agent

- [ ] Film content never disappears abruptly — poster/text fade is scroll-linked and begins while film 03 is still visible
- [ ] Pixel field passes through orange `#ff5a00` / purple `#480082` energy, restrained (atmospheric, not a color flood)
- [ ] Mesh is revealed through the cells — never visible as a generic crossfade underneath the old scene
- [ ] Pixel coordinates/seed consistent with transition A
- [ ] Fully reversible: scrolling back restores films exactly (seam test for state symmetry + Playwright)
- [ ] Short dark beat at 100% precedes any Tracks content
- [ ] Reduced motion: crossfade with a static mesh frame
