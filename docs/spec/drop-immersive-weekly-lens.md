# Spec: DROP Immersive Weekly Lens website

**Source of truth:** `handoff/DROP_CLAUDE_MASTER_BUILD_BRIEF_EN.md` (v1.2, 2026-08-21). This spec condenses the brief for planning and testing; where they disagree, the brief wins.
**Status:** ready-for-agent (pending seam confirmation — see Testing Decisions)

## Problem Statement

DROP publishes a Weekly Lens — a cultural point of view expressed through taste, sound, film, and art. The existing MVP presents that content as a plain page; it communicates the *what* but none of the *feel*. Visitors experience DROP's editorial voice as static text instead of the raw-but-controlled, cinematic identity the brand book defines. There is also no production-safe way to develop the experience while final licensed media (product photography, film posters, album art) is still being cleared.

## Solution

Rebuild the Weekly Lens as one uninterrupted, scroll-driven cinematic journey: a visitor enters through the animated DROP logo (the O becomes a portal), reads the weekly thesis through pinned scroll typography, discovers menu items through flipping cards, crosses reversible pixel transitions, explores three films over a Wavy Dots shader, browses music inside transparent jewel cases over a Monochrome Mesh, reviews cultural Art Pieces, and lands on a giant outline DROP footer crossed by a living prismatic light horizon.

The page is fully data-driven from a validated Weekly Lens object, so future lenses replace content without touching motion or structure. Development runs on a complete 20-asset mock pack whose rights flags deliberately fail the production-media guard until launch clearance.

## User Stories

### Entry and identity
1. As a visitor, I want the site to open with the animated DROP material logo, so that the brand's identity is the first thing I experience.
2. As a visitor, I want the loader's O to expand into a portal revealing the page, so that entry feels continuous rather than a hard cut.
3. As a returning visitor navigating between routes, I want a short mask transition instead of the full loader, so that navigation stays fast.
4. As a visitor on a slow connection, I want the loader capped at 4 seconds, so that I am never trapped waiting for noncritical media.
5. As a visitor, I want the small DROP logo fixed top-left from the hero onward, so that the brand stays present without a heavy navigation bar.
6. As a visitor, I want the header logo to adapt between black and white per scene, so that it stays legible over every background.

### Reading the lens
7. As a reader, I want the three W04 thesis messages to replace each other as I scroll a pinned scene, so that the weekly argument unfolds at my own pace.
8. As a Persian-speaking reader, I want Persian as the primary editorial language with correct `lang`/`dir` handling, so that the text reads naturally.
9. As a reader, I want reverse scroll to cleanly reverse every message transition, so that I can re-read without visual glitches.
10. As a reader, I want the dark-green grid scene to present a single centered statement, so that the brand's point of view lands without distraction.

### Taste edit
11. As a visitor, I want menu cards to rise as a stack, fan out, and flip in 3D with a stagger, so that discovering the taste edit feels physical.
12. As a visitor, I want each card front to show only the product image, name, and maker, so that the edit reads as editorial curation, not a shop.
13. As a visitor, I want card backs showing the white DROP logo on black, so that the deck reads as branded objects.
14. As a content editor, I want the deck to support 2–6 items driven by data, so that future lenses can change the selection without code changes.

### Films
15. As a visitor, I want exactly one film recommendation visible at a time (info left, poster right on desktop), so that each recommendation gets full attention.
16. As a visitor, I want posters to enter from the lower-right with slight rotation and exit upward as the next arrives, so that the sequence feels like handling physical posters.
17. As a visitor, I want the three W04 films in their view order (First / Second / Completing View) with their Persian rationales, so that the progression of views makes sense.
18. As a visitor, I want the Wavy Dots background alive but restrained behind the films, so that atmosphere never fights readability.

### Transitions
19. As a visitor, I want the grid scene to dissolve into the film scene through a bottom-weighted pixel mosaic aligned to the grid cells, so that scenes replace each other with brand energy instead of a crossfade.
20. As a visitor, I want scrolling backwards through a pixel transition to restore the exact prior state, so that the page feels like one continuous space.
21. As a visitor, I want the second pixel transition to pass through restrained orange/purple energy and resolve into the Monochrome Mesh with a short dark beat, so that music gets its own arrival moment.

### Tracks
22. As a listener, I want tracks presented as transparent jewel cases with artwork on the disc, so that browsing feels like flipping through physical media.
23. As a listener, I want the active case centered, largest, and brightest with title and artist beneath, so that I always know what I'm looking at.
24. As a listener, I want to advance the carousel by scroll, drag/swipe, arrow buttons, or keyboard arrows, so that the interaction works however I prefer.
25. As a listener, I want the group label (Morning / Afternoon / Night) available as small context, so that I understand the playlist's time-of-day logic.
26. As a content editor, I want the carousel length and scroll budget driven by track count, so that lenses with different playlists just work.

### Art Pieces
27. As a reader, I want Art Pieces as vertical editorial rows (index, category, title, creator, year, rationale, media), so that field notes read like a magazine, not a card grid.
28. As a reader, I want text entering through line masks and media through vertical crop reveals with mild parallax, so that the section keeps the cinematic rhythm.
29. As a reader, I want the Monochrome Mesh to continue uncut from Tracks (slower, slightly darker), so that the world doesn't reset between sections.

### Footer
30. As a visitor, I want a giant outline DROP wordmark with a real-time prismatic light horizon crossing it, so that the page ends on a living brand moment.
31. As a visitor, I want footer links to be clearly labeled placeholders until final destinations exist, so that nothing dead-ends or invents URLs.
32. As a stakeholder, I want the footer CTA disabled by default until final copy/action is approved, so that nothing unapproved ships.

### Data, rights, and routes
33. As a content editor, I want the whole page rendered from one validated Weekly Lens object, so that publishing a new lens is a data change, not a rebuild.
34. As a developer, I want Zod validation to fail loudly on malformed lens data, so that content errors surface at build/dev time, not in production.
35. As a brand owner, I want the production build to fail while any asset is `development-mock` or `productionAllowed: false` — and to fail or warn loudly on required `replace-with-final` assets, with `rights-pending` media visible only behind a dev/staging flag — so that unlicensed media can never silently ship.
36. As a developer, I want every mock asset local and rendered from data (no hotlinks, no repeated generic placeholder), so that development matches production shape.
37. As a visitor, I want `/` to render the current lens and `/lens/beautiful-imperfection` to render the same experience, so that lenses stay independently shareable.
38. As a search engine or screen reader, I want all meaningful text server-rendered, so that content is indexable and accessible without WebGL.

### Accessibility, responsiveness, performance
39. As a motion-sensitive visitor, I want `prefers-reduced-motion` respected in every scene (static logo + O-shaped crossfade loader, static gradient footer, crossfades elsewhere), so that the page is usable without animation.
40. As a keyboard user, I want the carousel and all controls reachable and operable with visible focus, so that nothing requires a pointer.
41. As a mobile visitor, I want scene-specific mobile behavior (narrower fans, swipe-first tracks, single-column art, safe viewport units), so that the experience holds at 375px.
42. As a visitor on a weak GPU, I want quality tiers (DPR caps, simplified shaders) and a non-WebGL fallback, so that the page degrades instead of breaking.
43. As a visitor, I want no scroll-jacking, stuck pins, dead scroll zones, or console errors, so that the page feels trustworthy.
44. As a screen-reader user, I want decorative canvases `aria-hidden` and all meaningful media given localized alt text, so that assistive output is clean.

## Implementation Decisions

- **Stack** (prescribed by the brief): Next.js App Router; React + TypeScript strict; Tailwind or CSS Modules for tokens/layout; GSAP + ScrollTrigger for pinned/scrubbed choreography; Lenis for smooth scroll integrated with GSAP's RAF; Three.js + React Three Fiber for loader, shared canvas, jewel-case depth, and footer light; custom GLSL for Wavy Dots, Monochrome Mesh, pixel mosaic, loader material, footer light; Zod for content validation; Playwright for e2e and scroll-state tests. Use current stable releases.
- **One shared fixed WebGL canvas** behind the DOM, switching background modes (`offWhiteGlow → greenGrid → pixelA → wavyDots → pixelB → monoMesh → footerLight`) by uniforms/state. Never multiple persistent canvases. DOM stays semantic above it; canvas is `aria-hidden`.
- **No giant timeline.** A page-level scene-state reducer (`SceneId` union) is the single authority on scene/mode/index state; per-scene ScrollTriggers are dumb progress sources feeding it, and scenes render exclusively from its output while owning their own triggers, cleanup, reduced-motion, and mobile behavior. Pixel transitions own mode changes between backgrounds.
- **Content module is the single source of truth**: schema (Zod), the validated W04 export, `currentLensSlug`, and the production-media guard live in a content module consumed by both routes. Scene components receive data as props; they never import media paths or copy directly. Counts, scroll budgets, and rendered slots derive from array lengths.
- **Logo as geometry**: the wordmark and primary logo are reconstructed as SVG/procedural components from the modular grid — module `2X`, spacing `X`, O outer `2X` / inner `X` per the brief; stroke details (symbol strokes `X/3`, R leg `X/3`, P bowl `2X/3`) per the brand deck's final-logo pages — never traced bitmaps, visually tuned to the supplied wordmark reference. Components: `DropWordmark`, `DropPrimaryLogo`, `DropSymbolRow`, `DropO` (controllable aperture), `DropLogoMaterial3D`.
- **Brand system**: black `#000000` / ink `#111111` / white `#fffffe` / off-white `#f2f2f2` / gray `#838383` base; orange `#ff5a00` and purple `#480082` only as atmospheric energy (glow, pixel energy, prismatic fringes); grid green `#102b19` with lines `#245236`. Montserrat (ExtraBold/Bold display, Regular body) + self-hosted Vazirmatn for Persian. Sharp corners on the logo and content-card system unless the physical form requires a circle; pills only for essential compact metadata. The brand PDF is a concepts deck — its exploratory palettes are not canon; the brief's tokens are.
- **Deliberate LTR editorial layout** for films (info left, poster right) held by CSS grid even for Persian content; Persian text inside columns may align right. Page-level `lang="fa"` with `dir` on text containers.
- **Persistent header**: small logo top-left only; top-right empty; no nav, no waitlist, no language toggle in V1.
- **Rights safety**: every media asset carries `rightsStatus` + `productionAllowed`; production builds call the guard and fail while mock assets remain, and fail/warn loudly on required `replace-with-final` assets; `rights-pending` assets display only in dev/staging behind an explicit internal flag (the handoff guard implements only the mock-asset clause — the content module extends it). Mock pack (20 local originals) is authoritative for development. No hotlinking or scraping, ever.
- **Deliberate hardenings/deviations** (recorded decisions): the adopted schema pins films at exactly 3 (brief says "usually three"); public media paths keep the mock-pack's `/media/lenses/<slug>/…` shape (deviates from the brief's §13 suggested tree because the validated JSON's `src` values are authoritative); the loader renders on its own temporary overlay canvas — the brief's "shared canvas where possible" exception — since the DOM must stay mounted beneath the loader; Art Piece media supports image or muted loop video, which requires extending the adopted media schema with an explicit kind; the footer adds a disabled copyright placeholder the mock pack lacks (brief §7.10 lists five metadata slots).
- **Routes**: `/` renders the configured current lens; `/lens/[slug]` renders the same scene template. Archive, CMS, share cards, language switcher are future work.
- **Performance**: server-render meaningful text; client-load WebGL modules dynamically; lazy-load scene media before entry; AVIF/WebP; DPR caps by quality tier; dispose GPU resources on unmount; targets — 60fps capable desktop, ≥30fps mid-range mobile, CLS < 0.1, a11y score ≥ 95.

## Testing Decisions

A good test verifies externally observable behavior at an agreed seam and reads like a specification ("carousel advances with keyboard arrows"), never internal structure (uniform values, GSAP internals, component tree). Expected values come from the seed content and the brief's acceptance criteria, not from re-deriving what the code computes.

**Seams under test (pre-agreed; confirm before the first test is written):**

1. **Content seam** — the content module's public API: `weeklyLensSchema` parsing, the validated W04 export, `assertProductionMedia`, lens lookup by slug. Vitest unit tests. This is where data integrity, bilingual completeness, and rights-guard behavior are proven (the guard **throwing** on the mock pack is the asserted-correct behavior).
2. **Scene-state seam** — the page-level scene-state *reducer*: `(state, inputEvent) → state`, consuming ordered raw inputs (scroll-progress updates from per-scene ScrollTriggers, discrete carousel inputs, reduced-motion flag) and producing `{sceneId, sceneProgress, backgroundMode, transitionState}` with declarative descriptors (active indices, pixel `{seed, progress}`, mesh variant, one-shot flags). Data flow is one-way: triggers feed the reducer; scenes and canvas render only from its output. Vitest unit tests, ordinal/structural assertions only (order, counts, mode mapping, symmetric stepping) — never absolute progress thresholds, which are tunable by design. Reversibility is falsifiable because the reducer is stateful.
3. **Page seam (highest)** — the rendered routes via Playwright: scene order and counts from data (2 cards, 3 films, 11 tracks, 4 art rows), scroll forward/reverse states, carousel input methods (scroll, buttons, keyboard), reduced-motion flows, `lang`/`dir`/landmarks/alt text, zero console errors, route matrix (`/`, `/lens/beautiful-imperfection`, refresh, back-nav).

WebGL pixels are not asserted; shaders are verified through the scene-state seam (mode and declarative variant descriptors — never by reaching into materials for uniform values) plus manual visual QA against the reference assets. Playwright tests prescribed by the brief (`lens-page.spec.ts`, `reduced-motion.spec.ts`, `content-schema.spec.ts`) map onto seams 3, 3, and 1 respectively.

Prior art: none — this repo has no existing tests; these three seams establish the pattern.

## Out of Scope

- Checkout, ordering, payment, cart, price, buy, like, favorite — any commerce.
- User accounts, CMS/admin, audio playback or streaming embeds.
- Archive page for W01–W03; rebuilding historic lenses with final media.
- Language switcher UI; share cards / OG image generation.
- Replacing mock media with licensed final assets (tracked by `handoff/04-mock-content/REPLACE_BEFORE_LAUNCH.md`, happens later as a data change).
- Copying reference-site code, assets, or copy in any form.

## Further Notes

- The handoff package is fully vendored at `handoff/`, including the three `.mov` motion references (see `handoff/02-motion/VIDEO_REFERENCES.md`).
- Scroll-budget numbers in the brief (Section 6) are starting points; the acceptance criterion is intentional rhythm, not exact page height.
- The brief's Section 19 acceptance criteria and Section 21 QA matrix are the final gate; every ticket's acceptance criteria trace back to them.
- Ticket breakdown with blocking edges: `docs/tickets/`. Build process: `docs/BUILD-GUIDE.md`.
