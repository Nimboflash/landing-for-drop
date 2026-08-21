# 02 — Brand geometry: DROP logo components as vector geometry

**What to build:** The DROP identity reconstructed as clean, reusable geometry components — `DropWordmark`, `DropPrimaryLogo`, `DropSymbolRow`, `DropO` with a controllable aperture scale — rendered from the modular grid math: module `2X`, spacing `X`, O outer `2X` / inner `X` (brief §4), plus the brand deck's stroke spec (symbol-row strokes `X/3`, R leg `X/3`, P bowl `2X/3` — from `handoff/01-brand/drop-brand-book.pdf`, "final logo" pages). Per the brief, visually tune the responsive wordmark to match `handoff/01-brand/drop-final-wordmark-reference.png` — the reference photo wins over the construction math where they disagree. Demoable on a dev-only page showing every component in black-on-light and white-on-dark.

**Blocked by:** 01 — Foundation.

**Status:** ready-for-agent

- [ ] Wordmark and primary logo are SVG/procedural geometry — no traced bitmaps anywhere
- [ ] `DropO` exposes an aperture scale prop (the loader will pulse 0.84–1.08 and expand it as the portal)
- [ ] Proportions derive from the X-unit system; a single size prop scales the whole lockup without drift
- [ ] Components render correctly in both black and white variants (header will swap per scene contrast)
- [ ] Visual check against the wordmark reference and storefront photo recorded in the PR (side-by-side screenshot)
- [ ] Exported SVGs written to `public/brand/` for static use (favicon/OG later)
