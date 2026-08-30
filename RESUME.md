# RESUME — DROP Immersive Weekly Lens build

Tickets 01–15 are complete. Everything below is verified state, not claims. Re-run the verification
block first; if green, pick up at "What is left".

**Two servers must both be running for the full e2e suite.** `content-matrix.spec.ts` drives the
dev-only fixture route on :3000; everything else runs against the production build on :3200. With
:3000 down, seven mobile-safari tests fail with "Could not connect" — a missing server, not a defect.

```bash
npx next start --port 3200 &     # production build
npm run dev -- --port 3000 &     # dev server (fixture route + real mock imagery)
```

## Verification (all green)

```bash
npm run typecheck && npm run test && npm run build && npx playwright test && npm run ci:rights-guard
```

- typecheck clean
- **282 unit tests** (7 files)
- build green — routes `/`, `/lens/beautiful-imperfection` (SSG), `/brand-preview`,
  `/dev/fixture/[name]` (dev-only, 404s in production — verified)
- **216 e2e passed, 0 failed, 4 skipped** (chromium + mobile-safari, 10 spec files)
  - Under heavy machine load the suite can hit its 180s per-test timeout in `responsive.spec.ts`
    (`scrollIntoScene` runs up to 80 scroll steps). That is contention, not a regression: the same
    tests pass in ~8s each when re-run on a quiet machine. Check `uptime` before believing a red.
- Lighthouse: accessibility 96, best practices 100, mobile performance 78–80, CLS 0 — all four
  brief §17 targets met
- `ci:rights-guard` exit 0 — meaning the guard **blocked** the flagged production build. That red is
  the correct state until launch clearance. Do not "fix" it.

## What is built

**Foundation.** Next 16.3.2 + React 19 + TS strict, `src/`, `@/*` alias, CSS Modules (not Tailwind).
zod 4 · gsap + ScrollTrigger · lenis · three + R3F + drei · vitest · Playwright.
- `src/content/` — handoff schema verbatim, W04 JSON, extended rights guard wired at **module scope**
  in `src/content/index.ts` so no route can forget it. Two count fixtures.
- `src/components/brand/` — DROP identity as pure SVG geometry from an X-unit system. Preview at
  `/brand-preview`.
- `src/lib/scene/` — `types.ts` is the seam-2 contract; `reducer.ts` implements it.
- `src/lib/motion/`, `src/lib/performance/` — single-ticker GSAP, reduced motion, quality tiers,
  WebGL support + context loss.

**Shell + WebGL.** `ImmersiveLensPage`, `SiteHeader`, `SceneSection`, `SmoothScrollProvider`,
`useSceneStateMachine`, `scene-budgets`. One persistent canvas (`BackgroundCanvas`) with seven modes:
OffWhiteGlow, GreenGrid, WavyDots, PixelMosaic (A **and** B off one seed), MonochromeMesh (3
variants), FooterLight. The loader is the sanctioned exception — its own temporary renderer, disposed
after the portal.

**All ten scenes wired**: Loader · Thesis · MenuDeck · GridStatement · PixelA · Film · PixelB ·
Tracks · ArtPieces · Footer.

### Verified by eye (dev server, 1440×900)
- **Thesis** — header dark-variant top-left, top-right empty, W04 label, Persian title in Vazirmatn,
  hero messages with the active one emphasised, orange/purple glow at the lower edge.
- **Menu deck** — fanned cards, real product image, name/maker/category only, sharp corners, card
  back black with the DROP logo. No price/cart/like anywhere.
- **Grid statement** — dark forest green with the quiet 64px lattice; header swaps to light variant.
- **Pixel A** — cells on the grid lattice, bottom-weighted, **irregular stepped skyline**, old grid
  holding until each cell flips, dots revealed *through* the cells. Not a wipe or crossfade.
- **Films** — one at a time, info left / poster right held by CSS grid under RTL, paper layers behind
  the poster, credit reading "not the official film poster".
- **Tracks** — 5-position coverflow, transparent jewel cases, artwork clipped onto the circular disc,
  title/artist/group beneath, arrow controls.
- **Art Pieces** — editorial rows with index/category/creator/year, sharp media, thin dividers, mesh
  in its slowed "reading" variant, each image labelled a DROP concept study.
- **Footer** — prismatic light horizon curving across the lower frame, five disabled placeholder
  slots, no invented destinations.

## Bugs found and fixed (worth knowing about)

1. **e2e failures were environmental.** Next 16's dev server blocks `/_next/*` from a non-allowed
   origin. Playwright used `127.0.0.1` while a stray dev server ran on `localhost`, and
   `reuseExistingServer` grabbed it — every JS chunk 403'd and hydration never ran. Fixed by aligning
   `baseURL` to `localhost`. **If scroll tests ever time out again, check this first.**
2. **The loader was built but never mounted** — the shell rendered a placeholder and never dispatched
   `loaderComplete`. A test was skipping itself with a note saying exactly that. Now wired.
3. **Every shader uniform was dead.** three.js clones uniforms when it builds the material, so each
   module's `update()` wrote to an orphaned object; every background rendered its first frame
   forever. Fixed by writing to `material.uniforms` (and disposing the same object). Guarded by
   `tests/e2e/background-liveness.spec.ts` — which never asserts what the background *looks* like,
   only that it is not frozen. Mutation-checked.
4. **190px of horizontal overflow** from the film poster's designed bleed widened the document; on an
   RTL page that shifts the viewport origin and drags the fixed canvas off its edge, leaving a bare
   strip. Fixed with `overflow-x: clip` on `SceneSection`'s **sticky pane**. Note: clipping on `html`
   instead silently breaks every pinned scene, because it makes `html` the sticky containing block —
   that was tried and reverted.

## What is left

Ticket 15 is done — see `docs/qa/ticket-15-status.md` for the full defect table. Eight defects were
confirmed by triage; **seven are fixed**. Outstanding work:

1. **No open defects.** All nine confirmed defects are fixed. The last two were the Pixel B → Tracks
   field discontinuity (the mosaic painted its own approximation of the mesh; both now share one
   field and one clock, and the measured step went 1.70× → 0.99×) and a dark beat that never
   darkened (`DARK_BEAT_DIM` was dead code — the ramp had no signal to ramp on). Details and
   measurements in `docs/qa/ticket-15-status.md`.

2. **The `[manual]` boxes**, which must never be faked with an automated test: fps profiling on named
   hardware; mesh continuity across Tracks → Art Pieces by eye; the dark beat's feel; footer entry;
   shader look against the references; and contrast sampling for the shader scenes other than Tracks.
   Procedures are in `docs/qa/contrast-audit.md` and `docs/qa/ticket-15-status.md`.
3. **Launch clearance** — replace the 20 mock assets per
   `handoff/04-mock-content/REPLACE_BEFORE_LAUNCH.md`. Until then the rights guard blocking the
   flagged build is the correct state.

## Standing rules

- Data-driven: never hardcode titles, counts, media paths, years, artists.
- Never weaken the guard or the `development-mock` / `productionAllowed: false` flags.
- No commerce UI. Sharp corners. No hotlinked or scraped reference assets.
- Every scroll transition reversible; reduced-motion and no-WebGL fallbacks mandatory.
- Test only at the three seams. Seam 2 is **ordinal/structural only** — never assert an absolute
  scroll-progress threshold. Playwright asserts **data attributes and text only**, never canvas
  pixels (the liveness guard is the one sanctioned exception, and it asserts only *difference*).

## The reference traps (do not lose this)

Following `handoff/03-layout/` literally violates the brief's hard rules. Only the composition
skeleton transfers:

| Reference | Contains (do NOT copy) | Brief requires |
|---|---|---|
| `menu-card-front` | rounded card, ♥ like, `59$`, cart button | image/name/maker only, `border-radius: 0` |
| `menu-card-back` | rounded **white** card, service list | near-black, centered white DROP logo, no other copy |
| `grid-statement` | email form, "Join Beta", handwriting, arrows, socials | grid + **one centered statement**, nothing else |
| `film-layout` | unrelated stacked card, no left text column | text left / poster right, one film at a time |

`02-motion/footer-light-horizon-reference.png` also contains a "Schedule demo" pill. Forbidden; the
footer CTA ships disabled. Ticket 08 documents this for the grid scene only — the other three traps
are undocumented, which is why this table exists.

## Housekeeping

- Nothing is committed. All work is untracked on `main`. To checkpoint:
  ```bash
  git checkout -b build/drop-immersive && git add -A && git commit -m "DROP: foundation, shell, shaders, ten scenes"
  ```
- `next dev` rewrites a `<!-- BEGIN:nextjs-agent-rules -->` block into `CLAUDE.md` on every run. That
  is Next 16 behavior, not a stray edit — commit it with the work.
- QA evidence lives in `docs/qa/`: `ticket-15-status.md` (defect table and resolutions),
  `contrast-audit.md` (the AA measurement and the four ways to measure it wrongly),
  `performance-notes.md`, `lighthouse-summary.json`.
- **This is Next.js 16.** Read `node_modules/next/dist/docs/01-app/` before route code.
- In a **production build the mock media deliberately does not render** — `canDisplayAsset` gates
  `development-mock` to dev/staging, so scenes show branded DROP placeholders. That is correct. Use
  `npm run dev` to see the real mock imagery.
