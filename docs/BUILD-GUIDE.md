# Build Guide — DROP Immersive Weekly Lens

How this project gets built. The what lives in `docs/spec/drop-immersive-weekly-lens.md` and `docs/tickets/`; this file is the how: the TDD process, the agreed test seams, and the rules that keep every ticket honest. Written for a fresh agent session picking up any ticket.

## Before touching code

1. Read `CLAUDE.md`, `CONTEXT.md` (use its vocabulary), and the ticket you're implementing.
2. Read the master brief sections your ticket cites — `handoff/DROP_CLAUDE_MASTER_BUILD_BRIEF_EN.md` is the source of truth over every other document, this one included.
3. Inspect the visual references your scene names (in `handoff/01-brand` … `05-mock-assets`). Motion `.mov` clips are not in the repo — see `handoff/02-motion/VIDEO_REFERENCES.md`.
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

The pure page controller: scroll progress in → `{ sceneId, sceneProgress, backgroundMode, transitionState }` out. This is where choreography is provable without a GPU:

- Scene order matches the brief's Section 6 sequence exactly.
- **Reversibility is a property**: for any progress sequence, reversing it produces the mirrored states (pixel transitions restore prior state; film/track/message indices step back symmetrically).
- Background modes map to scenes per the spec; pixel transitions own the mode changes.
- Keep this controller pure (no DOM, no Three.js imports) so these tests stay fast and deterministic.

### 3. Page seam (Playwright — the highest seam)

The rendered routes as a user experiences them. The brief prescribes `lens-page.spec.ts`, `reduced-motion.spec.ts`, `content-schema.spec.ts`; grow them per ticket:

- Data-driven counts and text visible in the DOM (server-rendered, JS-disabled check included).
- Scroll forward/reverse state assertions per scene; route matrix (`/`, `/lens/beautiful-imperfection`, refresh, back-nav).
- Input coverage: keyboard carousel, visible focus, no hover-dependent features.
- Reduced-motion and WebGL-disabled runs render all content.
- Zero console errors/WebGL warnings as a standing assertion in every spec.

**WebGL pixels are never asserted.** Shader look is verified by eye against the references; shader *state* is verified at seam 2.

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
