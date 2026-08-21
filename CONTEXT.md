# CONTEXT — DROP Immersive Weekly Lens

Domain glossary for this project. Use these terms — in code, tests, tickets, and commit messages — exactly as defined here.

## Brand

- **DROP** — a food concept store and cultural point of view (brief §1). Located in Tehran and taglined "FOOD CONCEPT STORE" per the brand assets — both facts come from the storefront photo and brand deck (`handoff/01-brand/`), not the brief. Persian-first, bilingual (fa/en).
- **Wordmark** — the D/R/O/P letter row. D, R, P live in sharp square modules; the O is a circular ring module (brief §4). The final execution knocks the letters out of solid tiles (per the wordmark reference photo).
- **Primary logo** — the wordmark row plus the **symbol row** (teeth/line mark, vertical bar in circle, diagonal bar, chevron — brief §4); a 4×2 lockup in the final storefront execution. The brand deck glosses the bar-in-circle as the Persian الف paired with the Latin O.
- **Module / X-unit** — the logo's construction grid. Brief §4: each module is `2X × 2X`; module spacing `X`; O outer diameter `2X`, inner diameter `X`. Brand deck adds the stroke spec: symbol-row strokes `X/3`, R leg `X/3`, P bowl `2X/3`. Where math and the supplied reference photo disagree, tune visually to the reference (brief §4).
- **The O** — the brand's hero shape ("one shape, endless possibilities"). In the loader it becomes the **portal** that reveals the page.

## Content model

- **Weekly Lens** (or just **lens**) — one week's editorial point of view: a tension found in balance through taste, sound, film, and art. Permanent slug, independently shareable. W01–W04 exist; **W04 "Beautiful Imperfection"** (`beautiful-imperfection`) is the launch seed.
- **Thesis / Tension / Balance / Not-this** — the four statements defining a lens's argument.
- **Hero messages** — the three pinned statements cycled in the thesis scene.
- **Taste edit / menu items** — 2–6 real menu cards (name, maker, category, rationale, image). Never price/commerce data.
- **Sound edit / tracks** — the lens playlist, grouped by **period** (`morning` / `afternoon` / `night`) with a **group title** and **playlist rationale**. W04 has 11 tracks.
- **Film edit / films** — normally three recommendations with **view labels** (First View / Second View / Completing View). The adopted schema currently pins the count at exactly 3 — a deliberate hardening of the brief's "usually three"; revisit if a future lens needs a different count.
- **Art Pieces / field notes** — editorial rows (architecture, art, photography, cultural note) with index, category, creator, year, rationale, media.
- **Media asset** — every image/video in content carries `rightsStatus` (`approved` | `rights-pending` | `replace-with-final` | `original-drop` | `development-mock`) and `productionAllowed: boolean`.
- **Production-media guard** — the production build check over media rights (brief §11): fails while any asset is `development-mock` or `productionAllowed: false`; fails or warns loudly when a required asset remains `replace-with-final`; `rights-pending` assets display only in development/staging behind an explicit internal flag. The handoff's `assertProductionMedia` implements only the first clause — the repo's content module must extend it. The guard failing on the current mock pack is correct behavior, not a bug.
- **Mock pack** — the 20 original development images + validated W04 JSON in `handoff/04-mock-content/` and `handoff/05-mock-assets/`. Authoritative for development rendering; never implies publication clearance.
- **Current lens** — the lens rendered at `/`; configured by `currentLensSlug`, not hardcoded.

## Experience

- **Scene** — one of the 10 fixed stages of the page, identified by `SceneId`: `loader`, `thesis`, `menu`, `gridStatement`, `pixelA`, `films`, `pixelB`, `tracks`, `artPieces`, `footer`. Scenes own their own triggers, cleanup, reduced-motion, and mobile behavior — there is no single giant timeline.
- **Scene state machine** — the page-level controller mapping scroll progress to the active scene and its progress value.
- **Background mode** — the shared WebGL canvas state: `offWhiteGlow`, `greenGrid`, `pixelA`, `wavyDots`, `pixelB`, `monoMesh`, `footerLight`. One fixed canvas; modes switch by uniforms/state, never by stacking canvases.
- **Loader** — the 3D material DROP logo (one near-black glossy living material) whose O aperture pulses, then expands as the portal into the page.
- **Pinned scene** — a scene that pins the viewport while scroll scrubs its timeline. Reverse scroll must reverse the animation (**reversibility** is an acceptance criterion everywhere).
- **Menu deck** — the stacked menu cards: rise → fan → 3D flip with stagger. Card back = black with white primary logo; card front = image/name/maker only.
- **Grid statement** — the dark forest-green square-grid scene with a single centered statement.
- **Pixel transition** — scroll-driven, reversible mosaic replacement between scenes. Cells align to the grid, change state at seeded thresholds, enter bottom-weighted with an irregular stepped skyline. **Pixel A** = grid → films; **Pixel B** = films → tracks (passes through restrained orange/purple energy).
- **Wavy Dots** — the film-scene GLSL background (MetalForge-inspired dots preset, rebuilt for web).
- **Monochrome Mesh** — the tracks/art GLSL background (4×4 gray mesh gradient preset, rebuilt for web). It continues uncut from tracks through Art Pieces, then fades to black for the footer.
- **Jewel case** — transparent CD case in the tracks carousel; track artwork is clipped onto the circular disc inside. Coverflow field shows up to 5 positions.
- **Light horizon** — the footer's real-time prismatic light band (white core, blue/cyan edge, restrained orange/purple fringes) crossing the giant outline DROP wordmark.
- **Quality tier** — `high` / `medium` / `low` / reduced-motion rendering levels (DPR caps, shader detail, static fallbacks).
- **Scroll budget** — the per-scene scroll length (in vh). Data-driven where counts vary (tracks). Tuned by feel; rhythm is the acceptance criterion, not exact heights.

## Terms to avoid

- "Slider" / "gallery" for the tracks scene — it's the **tracks carousel** (coverflow).
- "Splash screen" — it's the **loader** (a material scene, not an image).
- "Placeholder" for mock-pack images — say **mock asset** (they are complete, validated development media, not gray boxes).
- "Products" / "shop items" for menu items — DROP V1 has no commerce.
