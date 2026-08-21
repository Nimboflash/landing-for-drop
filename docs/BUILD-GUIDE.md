# Build Guide — DROP Immersive Weekly Lens

How this project gets built. The what lives in `docs/spec/drop-immersive-weekly-lens.md` and `docs/tickets/`; this file is the how: the TDD process, the agreed test seams, and the rules that keep every ticket honest. Written for a fresh agent session picking up any ticket.

## Before touching code

1. Read `CLAUDE.md`, `CONTEXT.md` (use its vocabulary), and the ticket you're implementing.
2. Read the master brief sections your ticket cites — `handoff/DROP_CLAUDE_MASTER_BUILD_BRIEF_EN.md` is the source of truth over every other document, this one included.
3. Inspect the visual references your scene names (in `handoff/01-brand` … `05-mock-assets`), including the motion `.mov` clips in `handoff/02-motion/` — see `VIDEO_REFERENCES.md` there for which clip specifies which scene.
4. Work on a branch per ticket; open a PR back to the integration branch.

## The TDD loop (from `/tdd`)

Red → green, one slice at a time:

1. Write one failing test at an **agreed seam** (below) that specifies the next behavior — a tracer bullet, not a batch of imagined tests.
2. Write only enough implementation to pass it. No speculative features, no anticipating future tests.
3. Repeat. Refactoring belongs to review (`/code-review`), not the loop.

Rules that matter here:

- **Test only at the three agreed seams.** No test against internals: no asserting GSAP timeline internals, uniform values by reaching into materials, React tree shapes, or CSS class names. If you can't express the behavior at a seam, it's manual visual QA, not an automated test.
- **No tautologies.** Expected values come from the seed content (`handoff/04-mock-content/…mock.json`), the brief's acceptance criteria, or worked examples — never recomputed the way the code computes them.
- **A good test reads like the spec**: `carousel advances with keyboard arrows`, `reverse scroll restores the grid state`, `production guard throws while mock assets remain`.

## The three seams

Agreed in the spec (Testing Decisions). Confirm any new seam with the user before writing tests at it — the ideal seam count stays exactly these three.

### 1. Content seam (Vitest)

The content module's public API: schema parse, validated lens export, lens lookup, `assertProductionMedia`.

- Prove: W04 parses; counts (2 menu / 3 films / 11 tracks / 4 art) match the manifest; bilingual fields present; malformed data fails loudly; **the guard throws on the mock pack — that throw is the correct, asserted behavior**.
- Never weaken: the guard, the `development-mock` statuses, `productionAllowed: false`.

### 2. Scene-state seam (Vitest)

The scene-state **reducer**: `(state, inputEvent) → state`, where input events are the ordered raw inputs — scroll-progress updates emitted by the per-scene ScrollTriggers, and discrete inputs (carousel keyboard/buttons/drag, reduced-motion flag) — and the state is `{ sceneId, sceneProgress, backgroundMode, transitionState }`. `transitionState` carries declarative descriptors only: active film/track/message indices, pixel-transition `{seed, progress}`, mesh variant (`"normal" | "reading" | "fadeToBlack"` + scalar), one-shot flags (e.g. grid statement revealed). No DOM, no Three.js imports — deterministic and GPU-free.

**Mandated data flow (one-way):** per-scene ScrollTriggers are dumb progress sources feeding the reducer; scenes and the background canvas render *exclusively* from reducer output; no scene computes its own scene/mode/index state. This is what makes seam-2 tests meaningful — a controller that merely mirrors what scenes compute independently would test a model the page doesn't use.

- **Assertions are ordinal/structural only**: scene order matches the brief's Section 6 sequence; indices and slot counts derive from data (including the variable-count fixture); mode-per-scene mapping; monotonicity; one-shot semantics. **Never assert absolute progress thresholds** — scroll budgets are tunable by design, so any absolute boundary expectation would just re-derive the implementation's config (a tautology).
- **Reversibility is a real property because the reducer is stateful**: a scroll-driven event sequence followed by its reverse must produce the mirrored index/mode trajectory; after a discrete input (keyboard/drag), the reducer's documented precedence (most recent input wins) defines the state, and reverse-scroll stepping resumes from it. These tests can genuinely fail.
- Pixel-transition determinism at this seam means: same `{seed, progress}` descriptor re-emitted on reverse. Whether the GLSL restores cells from that descriptor is manual visual QA.

### 3. Page seam (Playwright — the highest seam)

The rendered routes as a user experiences them. The brief prescribes `lens-page.spec.ts`, `reduced-motion.spec.ts`, `content-schema.spec.ts`; grow them per ticket:

- Data-driven counts and text visible in the DOM (server-rendered, JS-disabled check included).
- Scroll forward/reverse state assertions per scene; route matrix (`/`, `/lens/beautiful-imperfection`, refresh, back-nav).
- Input coverage: keyboard carousel, visible focus, no hover-dependent features.
- Reduced-motion and WebGL-disabled runs render all content.
- Zero console errors/WebGL warnings as a standing assertion in every spec.

**DOM observable-state contract:** every scene reflects its *logical* state into the DOM as attributes driven by reducer output — `data-active`, `data-flipped`, `aria-current`, and `hidden`/`inert` on inactive content. Playwright asserts **only these attributes plus text content** — never inline transforms, opacity values, or computed styles (those are the animation engine's implementation, and Playwright's visibility heuristic is wrong for them anyway: `opacity: 0` and back-facing 3D elements still count as "visible"). This is a convention of the page seam, not a fourth seam.

**Dev-only diagnostics escape hatch:** the page may expose a dev-build-only diagnostics object (e.g. live ScrollTrigger count) as part of the page seam, so leak checks ("no accumulating triggers after route round-trip") don't require reaching into GSAP internals. The behavioral proxy also applies: after navigating away and back, forward/reverse scroll must produce identical states.

**WebGL pixels are never asserted.** Shader look is verified by eye against the references; shader *state* is verified at seam 2 via declarative descriptors.

**`[manual]` boxes:** ticket acceptance boxes tagged `[manual]` (feel, fps, shader-visual, contrast-over-shader claims) are verified by hand with evidence (screenshots, recordings, profiling notes with named hardware) attached to the PR. Never invent an automated test for a `[manual]` box. In particular, WCAG AA contrast for text over live shaders is measured by sampling worst-case shader frames — Lighthouse's contrast rule silently skips text over canvas, so a passing Lighthouse score says nothing about it.

**Production-guard CI wiring:** the rights guard runs behind an explicit production flag. The default CI `build` stays green throughout development; a dedicated CI step runs the flagged production build and asserts a **non-zero exit** while mock assets remain — that red is the passing state of that step until launch clearance.

## Definition of done (every ticket)

- All acceptance boxes in the ticket file check.
- Typecheck clean; the ticket's test files green throughout; full suite green at the end.
- Forward scroll, reverse scroll, mobile viewport, and reduced-motion manually sanity-checked for the touched scenes.
- `/code-review` run on the change; findings addressed.
- No hard-rule violations (see `CLAUDE.md`): data-driven content, no commerce UI, sharp corners, guard intact, no hotlinked/scraped media, transitions reversible.
- PR references the ticket; QA evidence (screenshots/recordings for visual scenes) attached.

## Standing engineering rules

- One shared WebGL canvas; modes switch by state — never mount a second persistent canvas.
- Scenes are isolated: own triggers, own cleanup on unmount/route change, own reduced-motion and `gsap.matchMedia` mobile behavior. No cross-scene timeline reach-ins.
- Lenis and GSAP share one RAF; never introduce a second scroll or animation engine for the same interaction (Framer Motion only for small non-scroll UI states).
- Server-render meaningful text; dynamically import WebGL-heavy modules; lazy-load scene media before entry; dispose GPU resources on unmount.
- Persian first: `lang="fa"`, correct `dir` on text containers, film-scene LTR grid held deliberately by CSS.
- When a reference site and the brief conflict, the brief wins. When this guide and the brief conflict, the brief wins.
