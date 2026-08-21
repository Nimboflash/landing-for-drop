# 13 — Art Pieces / field notes

**What to build:** The editorial close of the lens body: `ART PIECES / FIELD NOTES` heading with data-driven count, then vertical editorial rows — index, category, title, creator, year, rationale left; sharp-edged media right with vertical crop reveal and mild parallax; thin dividers between rows; text entering through line/clip masks; title and media moving at slightly different speeds. Within this scene the Monochrome Mesh runs slowed and slightly darkened for reading comfort. W04's four items render from data. (The uncut Tracks→Art mesh continuity across the scene boundary is verified in 15 — Hardening, since 12 runs in parallel.)

**Blocked by:** 03 — Immersive shell; 10 — Monochrome Mesh mode. (Runs parallel to 12 — Tracks.)

**Status:** ready-for-agent

- [ ] Mesh renders continuously through the scene with the slowed/darkened variant — no restart or cut inside the scene; the cross-scene hand-off assertion lives in ticket 15
- [ ] Four W04 rows from data with all fields (the Pratfall row has duration + label instead of creator/year — optional fields leave no gaps)
- [ ] Media slot supports image or muted loop video (inline, pausable, never autoplaying audio) — schema extended with an explicit media kind; W04 ships images only
- [ ] Sharp media edges, thin horizontal dividers, no rounded service cards
- [ ] Active row has visual priority; adjacent rows may partially enter/leave; reverse scroll reconstructs prior state
- [ ] Concept images are presented as DROP concept studies, never as photographs of the referenced original works (alt text from data preserves this)
- [ ] When a `sourceUrl` exists, the row's link opens safely in a new tab (`rel="noopener"`, announced as external)
- [ ] Mobile: single column — title/details then media
- [ ] Reduced motion: rows reveal by simple fade, all content readable
- [ ] Playwright: 4 rows in order with correct titles/categories, forward/reverse assertions
