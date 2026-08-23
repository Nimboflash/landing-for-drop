# Performance and resource hygiene — measured evidence

Ticket 15, boxes 6 and 7. Brief §17 ("Performance Requirements") and §14 ("Quality tiers").

Every number below came out of a run executed for this document. Where a target could not be
expressed at one of the three agreed seams, the `[manual]` procedure is written out instead of a
number — see [What stays `[manual]`](#4-what-stays-manual). **No fps figure appears anywhere in
this document**, because none was profiled.

---

## 1. The machine, and why it matters

| | |
| --- | --- |
| Host | `Nimbos-MacBook-Air.local` |
| CPU | Apple M4, 10 logical cores |
| Memory | 16 GB |
| OS | macOS (darwin 25.5.0), arm64 |
| Browser | Google Chrome 151.0.7922.170, headless (`--headless=new`) |
| Node / Lighthouse | v26.3.0 / lighthouse 13.4.1 |
| Server under test | the already-running **production** build on `http://localhost:3200` |

> **Contention caveat — read this before quoting any mobile number.** Sampled with `top -l 2` and
> `uptime` between the two Lighthouse runs recorded below:
>
> ```
> Load Avg: 185.42, 339.99, 315.03
> CPU usage: 47.69% user, 32.61% sys, 19.68% idle
> ```
>
> Four other agents were working in this repo on the same machine (a `tsc --noEmit` was burning
> 149 % CPU during the sample, alongside two Next servers and macOS's own indexing daemons).
> Roughly **one fifth of the CPU was idle**, and Lighthouse's mobile preset applies a 4× CPU
> slowdown *on top of that*, so a contended core is penalised four times over.
>
> The mobile performance figures below are therefore a **floor, not a measurement of the product**.
> They must be re-taken on an otherwise idle machine before this gate is treated as final. The
> accessibility, best-practices and CLS figures are not load-sensitive in the same way and can be
> read at face value.

---

## 2. Lighthouse — brief §17 launch targets

Run with `node scripts/lighthouse-audit.mjs` — audits `/` and `/lens/beautiful-imperfection`,
mobile and desktop presets, against the already-running :3200 server. The script never builds and
never starts a server: every agent here shares one `.next` directory. Full JSON in
`docs/qa/lighthouse-summary.json`.

### Targets and outcome

| Target (brief §17) | Threshold | Result across both runs below |
| --- | --- | --- |
| Accessibility | ≥ 95 | **96** on all 4 route × form-factor combinations, both runs — **PASS** |
| Best Practices | ≥ 90 | **100** on all 4, both runs — **PASS** |
| CLS | < 0.1 | **0** on all 4, both runs — **PASS** |
| Mobile performance | ≥ 75 | **49-89**, missed on 3 of 4 mobile route-runs — **FAIL** |

### The two runs executed for this document

Run **D** — 2026-08-22, 13:07 UTC. Not the canonical summary; kept because it is the outlier that
shows how wide the spread is.

| preset | route | perf | a11y | BP | CLS | FCP | LCP | TBT | SI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mobile | `/` | **49** | 96 | 100 | 0 | 1216 ms | 6450 ms | 1381 ms | 4383 ms |
| mobile | `/lens/beautiful-imperfection` | **89** | 96 | 100 | 0 | 809 ms | 1549 ms | 429 ms | 1356 ms |
| desktop | `/` | 100 | 96 | 100 | 0 | 206 ms | 318 ms | 0 ms | 479 ms |
| desktop | `/lens/beautiful-imperfection` | 97 | 96 | 100 | 0 | 317 ms | 1283 ms | 6 ms | 701 ms |

Run **E** — 2026-08-22, 13:33 UTC. This is the run held in `docs/qa/lighthouse-summary.json`
(written by the script itself via `--out`, then copied to the canonical path unmodified).

| preset | route | perf | a11y | BP | CLS | FCP | LCP | TBT | SI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mobile | `/` | **65** | 96 | 100 | 0 | 1060 ms | 5846 ms | 541 ms | 1972 ms |
| mobile | `/lens/beautiful-imperfection` | **64** | 96 | 100 | 0 | 1059 ms | 5882 ms | 581 ms | 1951 ms |
| desktop | `/` | 97 | 96 | 100 | 0 | 293 ms | 1220 ms | 6 ms | 581 ms |
| desktop | `/lens/beautiful-imperfection` | 98 | 96 | 100 | 0 | 288 ms | 1129 ms | 0 ms | 526 ms |

Two runs (A and B/C) recorded in an earlier session are **not reproduced here**, because they were
not executed for this document. For the record of spread only: mobile `/` has been observed at 41,
49, 57, 65 and 65 across five runs, and mobile `/lens/…` at 61, 62, 64, 64 and 89. **Treat any
single mobile number as ±20.** Every desktop number ever observed is ≥ 76, and 91-100 on the four
runs whose conditions are known.

The script **exits non-zero** when a gated threshold is missed, so it can gate CI as-is —
`SCRIPT_EXIT=1` was observed directly on run D (un-piped, so the exit code was the script's own).
Desktop performance is measured and printed but deliberately **not gated**: the brief names a
mobile performance target only, and inventing a desktop threshold would be a target this project
never agreed to.

### Why mobile misses: the page emits no LCP candidate at all

This is established, reproducible, and the largest single lever on the score. LCP is 25 % of the
Lighthouse performance score.

**What Lighthouse says.** All four audits in both runs printed
`LanternError: NO_LCP` from `@paulirish/trace_engine`, and
`largest-contentful-paint-element` resolved to `null` on all four — Lighthouse found no LCP
element and simulated a metric anyway (1.1-6.5 s, which is where the score goes).

**What the browser says.** Reproduced directly against :3200 with Playwright's Chromium, outside
Lighthouse, at 412×823 and 1280×720, on both routes:
`performance.getEntriesByType("largest-contentful-paint")` returns `[]` **every time**, and a
`PerformanceObserver` on `largest-contentful-paint` with `buffered: true` receives nothing — while
`paint` entries record FCP at 80-144 ms. The observer is not broken: appending a plain
`<div>` of 64 px text to the page makes it fire immediately (`size: 77140`), so the page's own
content is what is never eligible.

**Why it is never eligible.** Measured at `scrollY: 0`, after the loader published
`data-drop-loader="complete"` and the overlay had unmounted, at a 823 px-tall viewport:

```
loader section height : 988   (taller than the viewport)
thesis section top    : 988   (the first text starts below the fold)
text nodes in viewport: 0
<img> in viewport     : 0
<img> in document     : 0
LCP entries           : 0
```

The loader scene's own scroll budget is 988 px tall, so after hydration it fills the entire first
viewport, and everything it contains is `<svg>`/`<path>` and a `<canvas>` — **none of which are LCP
candidates** (only `<img>`, `<image>` inside SVG, `<video>` posters, CSS `background-image`, and
block-level text are). The production build additionally has zero `<img>` elements anywhere,
because `canDisplayAsset` correctly gates `development-mock` media out of production. Result: the
first viewport contains nothing Chrome will ever nominate, so no LCP is ever recorded.

Contrast with the **no-JS** render of the same URL, where the first viewport *is* full of text
(the `W04 / BEAUTIFUL IMPERFECTION` label at y=113, the `<h1>` at y=152, the thesis paragraphs,
the menu `<h2>` at y=544). Brief §17's "server-render all meaningful text" is satisfied; it is
hydration expanding the loader's scroll budget that pushes it all below the fold.

This is filed as a defect for the orchestrator rather than fixed here — `LoaderScene`, the scene
budgets and `ImmersiveLensPage` are not files this ticket owns.

**Second-order:** Lighthouse's only costed opportunity is `unused-javascript`, ~1.39 s on mobile
and ~0.20 s on desktop — the three.js / R3F payload. This is **not** a brief violation: §17's
"dynamically load WebGL-heavy modules on the client" is already honoured — `BackgroundCanvas`,
`LoaderScene` and `DropLogoMaterial3D` are all behind `next/dynamic`
(`ImmersiveLensPage.tsx:69-79`, `LoaderScene.tsx:59`). It is the size of the library, not the way
it is loaded.

### The accessibility score does NOT cover contrast over the shaders

Printed on every run of the script, and repeated here because it is the single most misreadable
number in this document:

> Lighthouse's `color-contrast` audit **cannot see text drawn over a `<canvas>`**. axe-core cannot
> sample a WebGL framebuffer. Every scene on this page puts editorial text over a live shader, so
> **accessibility 96 says nothing about AA contrast over the backgrounds.**

It is worse than a silent skip here: axe does not abstain, it **guesses the wrong background** and
reports failures against it. All four audits in both runs report `color-contrast` failing with
9-10 nodes, and every one of those findings composites the text against the body's
`--drop-off-white` (`#f2f2f2`) — or against that plus the element's own `text-shadow` halo
(`#d5d5d5`) — when the ground actually painted behind it is a dark shader:

| Reported by axe | Ground axe assumed | Ground actually painted |
| --- | --- | --- |
| `FilmScene .credit` — 2.7:1 (`#949494` on `#f2f2f2`) | body off-white | `wavyDots` |
| `TracksScene .headingFa` — 1.11:1 (`#fffffe` on `#f2f2f2`) | body off-white | `monoMesh` |
| `TracksScene .title span` — 1.11:1 | body off-white | `monoMesh` |
| `FooterScene .statementEn` — 2.92:1 (`#8e8e8e`) | body off-white | `footerLight` |
| `FooterScene .ctaEn` — 1.52:1 (`#adadad` on `#d5d5d5`) | off-white + text-shadow halo | `footerLight` |
| `FooterScene .links li span` — 2.32:1 (`#8b8b8b` on `#d5d5d5`) ×5 | off-white + text-shadow halo | `footerLight` |

**These are not filed as defects from this ticket** — they are measured against a background that
does not exist at runtime, and the real contrast question belongs to `docs/qa/contrast-audit.md`.
What they *are* is the worst-case sampling worklist for §4.2 below: six selectors, each rendering
semi-transparent over an animated shader, which is exactly the condition under which real AA
failures hide.

`best-practices/valid-source-maps` also scores below 1 ("Missing source maps for large first-party
JavaScript") on all four audits. It carries zero weight — the category still scores 100 — and is
informational only. Not a defect.

---

## 3. Resource hygiene — `tests/e2e/performance.spec.ts`

Page seam (BUILD-GUIDE seam 3): data attributes, text, element counts, and the browser's own
answers to `isContextLost()` and the `layout-shift` observer. No computed styles, no inline
transforms, no canvas pixels, no absolute scroll-progress thresholds.

```bash
PORT=3200 npx playwright test tests/e2e/performance.spec.ts --project=chromium
PORT=3200 npx playwright test tests/e2e/performance.spec.ts --project=mobile-safari
PORT=3000 npx playwright test tests/e2e/performance.spec.ts --project=chromium \
  -g "ScrollTriggers do not accumulate"      # dev server: diagnostics are live only there
```

### Runs actually executed

| Project | Server | Result |
| --- | --- | --- |
| chromium | :3200 production | **9 passed, 1 skipped** (3.0 min) |
| mobile-safari (iPhone 13) | :3200 production | **8 passed, 2 skipped** (25.8 s) |
| chromium, `-g "ScrollTriggers do not accumulate"` | :3000 dev | **1 passed** (38.0 s) |
| both projects together, JSON reporter | :3200 production | **17 passed, 3 skipped, 0 flaky, 0 failed** |
| both projects together (final, after the context-loss test was strengthened) | :3200 production | **17 passed, 3 skipped** (36.7 s) |
| chromium, `-g "ScrollTriggers do not accumulate"` (final) | :3000 dev | **1 passed** (30.1 s) |

Four full executions of the file, two of them across both projects. **Nothing flaked across any of
them** — the same pass/skip set every time, and the three skips are the same three every time
(ScrollTriggers ×2 for the stripped production diagnostics, layout-shift ×1 for WebKit).

### What each test proved, with the values recorded

**One persistent WebGL context.** After the loader hands over, on both routes: exactly one
`<canvas>` in the document, exactly one live WebGL context, zero loader overlays, and the
surviving canvas is the shared background's. Contexts are counted by wrapping
`HTMLCanvasElement.getContext` in an init script and asking each context `isContextLost()` — so a
renderer that was unmounted but never disposed shows up as a live context on a *detached* canvas,
which counting elements alone would miss. The test also asserts more than one context was ever
created, so a build that never made the loader's temporary renderer could not pass by accident. A
full forward-and-reverse pass across all ten scenes — every one of the seven background modes —
creates **no** additional context.

**ScrollTriggers do not accumulate.** Skipped against :3200 with an annotation, because the
dev-only diagnostics block is dead-code-eliminated from a normal production bundle — which is
correct, and the test says so rather than passing silently. Executed for real against the dev
server on :3000, where `__dropSceneDiagnostics.scrollTriggerCount` is live: the count is ≥ 10 (one
per brief §6 scene) and **identical across three consecutive route round trips**
(`/` → `/lens/beautiful-imperfection` → back, ×3). Three trips rather than one, because a leak of
one trigger per mount is invisible in a single before/after comparison if the first mount is the
one that leaks.

*Coverage limit, stated plainly:* the canonical `PORT=3200` command in the ticket **does not**
exercise this box. It only runs against the dev server. Anyone re-verifying must run the third
command in the block above.

**DPR caps (brief §14: high 1.75-2, medium 1.5, low 1).** The test reads the cap from
`src/lib/performance/quality-tier.ts` as the ticket asks, and separately asserts that module still
agrees with the brief's literals, so a silent change to the module cannot quietly redefine the
test. Applied ratio is measured as `canvas.width / canvas.clientWidth` — the renderer's actual
backing-store resolution, the only way to observe the cap from outside the renderer.

| Environment | tier published | `devicePixelRatio` | applied ratio |
| --- | --- | --- | --- |
| chromium headless (SwiftShader → software renderer → low) | `low` | 1 | **1.000** |
| mobile-safari, iPhone 13 emulation | `medium` | **3** | **1.500** |
| chromium, `deviceScaleFactor: 3` forced | `low` | 3 | 1.000 |

The mobile-safari row is the one that matters: a **3× panel rendering at 1.5×** is the brief's
medium cap doing its job, not a threshold satisfied by luck. The forced-3× test additionally
asserts the applied ratio is strictly below the device ratio, so a build with unbounded DPR fails
it rather than passing by coincidence.

*Coverage limit:* **no browser available here resolves the `high` tier** — headless Chromium falls
to `low` on SwiftShader and the iPhone 13 profile resolves `medium`. The high cap (1.75-2) is
therefore verified only as a static constant against the brief's literals, never as an applied
pixel ratio. Confirming it needs a real GPU-backed desktop browser: open the page, read
`data-quality-tier` off `[data-background-canvas]`, and check `canvas.width / canvas.clientWidth`
against the panel's `devicePixelRatio`.

**WebGL context loss is survived.** Forced through the browser's own `WEBGL_lose_context`
extension, in **both** chromium and WebKit. `[data-background-canvas]` flips `data-webgl` from
`active` to `fallback`; the lens title, the `W04` label and all ten `[data-scene]` sections are
still present; scroll still drives the state machine (asserted by reaching `films` and then
`footer` with the GPU gone). Calling `restoreContext()` returns `data-webgl` to `active` without
adding a canvas or a context. No console errors throughout — the only console output during loss
is three.js's own `console.log("THREE.WebGLRenderer: Context Lost.")`, a log rather than an error
or warning.

*Not blank, and not frozen.* The ticket asks this test to prove the page "falls back to a styled
static background", which `data-webgl="fallback"` alone does not establish — a blank layer would
publish the same attribute. The test therefore also reads `data-background-mode` at two scenes
while the GPU is gone and asserts both readings are real brief §14 modes **and that they differ**;
a fallback that stopped tracking the journey would report one mode at both ends of the page.
Measured values: **`wavyDots` at `films`, `footerLight` at `footer`**. Mutation-checked — flipping
the inequality to an equality fails with exactly those two values, so the assertion is live rather
than vacuously true. (Ordinal only: which mode belongs to which scene is seam 2's assertion, not
this file's. The fallback ground's colour is an inline style and is never read here.)

**Console hygiene across a full scroll pass.** All ten scenes, three positions each, forward and
then reverse: zero console errors, zero page errors, zero WebGL warnings. Two exclusions are made
explicitly rather than by a loose filter, so they stay visible:

- `GL Driver Message … GPU stall due to ReadPixels` — emitted by the compositor for its own
  screenshot/video readbacks on any page that draws WebGL. The same exclusion `loader.spec.ts`
  already makes.
- `THREE.Clock: This module has been deprecated. Please use THREE.Timer instead.` — printed by
  `@react-three/fiber`'s own store (`node_modules/@react-three/fiber/dist/events-*.esm.js`), not
  by anything in `src/`. A library deprecation notice, not a WebGL warning, and not silenceable
  without changing a dependency.

**No layout shift after fonts load (brief §17).** CLS proxy via the `layout-shift`
PerformanceObserver with `buffered: true`, cross-referenced against `document.fonts.ready`.
Chromium recorded **`total=0.0000 afterFonts=0.0000 entries=0`** — not a small number under the
0.1 target, but literally no shift entries at all, which matches Lighthouse's CLS of 0 on all four
audits in both runs. Skipped on WebKit with an annotation: it does not implement the entry type.

---

## 4. What stays `[manual]`

Never automate these. Nothing at any of the three agreed seams can express them, and a test that
pretended to would be worse than no test.

### 4.1 Frame rate — 60 fps capable desktop, ≥ 30 fps mid-range mobile (brief §17)

**Not measured. No fps figure is claimed anywhere in this document.** A profile taken on a machine
running at 19.68 % idle with four other agents on it measures the harness, not the experience.

Procedure, to be executed on quiet hardware and attached to the PR:

1. Name the hardware in the evidence — model, CPU/GPU, OS, browser build, display refresh rate and
   resolution, and whether the machine was otherwise idle. "A MacBook" is not a named machine.
2. Two devices minimum: one capable desktop (target 60 fps) and one **mid-range** phone (target
   ≥ 30 fps). A current flagship is not a mid-range phone and does not satisfy this box.
3. Serve the production build. Confirm the tier the page resolved before profiling — read
   `data-quality-tier` off `[data-background-canvas]` — and record it with each result, because a
   60 fps reading on the `low` tier proves nothing about `high`. (Per §3 above, `high` has never
   been observed in this environment at all, so the desktop run is also the first real check of
   that tier's DPR cap.)
4. Profile the **four heaviest scenes only**, each scrubbed slowly through its full range and then
   fully reversed:
   - **tracks** — five-position coverflow, transparent jewel cases, clipped disc artwork;
   - **pixelA** and **pixelB** — the mosaic transitions, the only scenes doing a full-frame cell
     flip, and the only ones that own their own mode change;
   - **footer** — the prismatic light horizon.
5. Capture per scene: a DevTools Performance recording covering the whole scrub, the frame-rate
   chart, and the percentage of frames over budget. Record the **worst sustained** rate, not the
   average — a scene that holds 60 and drops to 22 across the pixel flip fails this box even
   though its mean looks fine.
6. Repeat with `prefers-reduced-motion: reduce` active. The shader clock stops there
   (`backgroundBehavior: "static"`), so this run checks that reduced motion is genuinely cheaper
   rather than re-measuring the same thing.
7. Attach the `.json` trace exports, not screenshots of the chart.

### 4.2 AA contrast for text over live shaders (brief §16)

**Not measurable by any tool at the page seam** — and, as §2 shows, Lighthouse actively reports the
wrong answer here rather than abstaining.

Procedure:

1. Work from the six selectors in the §2 table. They are the highest-risk set: each renders
   semi-transparent over an animated background, and axe has already flagged them (against the
   wrong ground, but on the right elements).
2. For each, scrub its scene to the **worst-case shader frame** — the brightest ground under light
   text, the darkest under dark text. Specifically: the footer beam at the point where it passes
   lowest across the `FooterScene .links` row; the `monoMesh` at its brightest control-colour peak
   under the Tracks headings; the `wavyDots` glow under the Film credit.
3. Screenshot the composited frame at full resolution — **not** a canvas readback, which returns a
   cleared buffer (`preserveDrawingBuffer` is off, deliberately).
4. Sample the actual painted pixels: the text colour, and the background at several points
   directly behind the glyphs (not beside them — the halo is local). Compute the ratio with a WCAG
   contrast calculator.
5. Required: **4.5:1** for body text, **3:1** for large text (≥ 18.66 px bold or ≥ 24 px).
6. Repeat at 375×812 and 1440×900 — the shader fills the viewport, so the ground behind a given
   paragraph is not the same at both sizes.
7. Attach the sampled frames with the measured ratios annotated on them.

Cross-reference `docs/qa/contrast-audit.md`, which owns this box; the table in §2 is contributed to
it as the worklist, not as a competing verdict.

### 4.3 Shader look and scroll rhythm

Verified by eye against `handoff/02-motion/` and `handoff/03-layout/`, and by feel against the
brief's rhythm criterion. Outside this ticket's boxes 6-7; noted so that the list of what
Lighthouse does *not* cover is complete.

---

## 5. Open items handed to the orchestrator

1. **The page emits no LCP candidate at all** (brief §17). At `scrollY: 0` after the loader
   completes, the first viewport holds zero text nodes and zero images because the loader scene's
   988 px scroll budget fills it with SVG and a canvas. Chrome records no
   `largest-contentful-paint` entry on either route at either viewport; Lighthouse errors
   `NO_LCP` on all four audits and substitutes an estimate worth 25 % of the performance score.
   Reproduction is in §2. Not fixed here: `LoaderScene`, the scene budgets and `ImmersiveLensPage`
   are outside this ticket's file ownership.
2. **Mobile performance 49-89 against a ≥ 75 gate** (brief §17), missed on 3 of the 4 mobile
   route-runs executed for this document and on 9 of 10 mobile route-runs ever observed. Item 1 is
   the largest identified lever. **Re-measure on an idle machine before acting**: every run here
   was taken at ~20 % idle CPU under a 4× Lighthouse throttle.
