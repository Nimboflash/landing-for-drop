# Ticket 15 — hardening status

Five parallel QA agents audited the assembled build, then a triage pass independently reproduced
every reported finding before it counted. Two reported findings did not survive that check and were
correctly killed (see "Dismissed"). This file records what was confirmed and what was done about it.

## Confirmed defects and their resolution

| # | Severity | Defect | Status |
|---|---|---|---|
| 1 | blocker | `/loader-probe`, a ticket-05 debug harness, shipped in the production build — publicly served, prerendered and indexable | **Fixed** — route deleted |
| 2 | blocker | The loader did not lock scrolling; a wheel flick during the ~3.2s loader carried the document past four scenes, and the O portal opened onto wherever it landed | **Fixed** — input-only lock |
| 3 | major | The Pixel B "short empty dark beat" was not empty: the Tracks title and carousel were already on screen throughout it | **Fixed** — entrance gated on reducer state |
| 4 | major | Art Piece rights placeholders were `aria-hidden` with no accessible name, so the data's localized alt text was lost — and in a production build *every* asset takes that branch | **Fixed** — matches the other three scenes |
| 5 | major | The footer's mesh fade to black ran on a 0.42s wall-clock crossfade instead of the reducer's scroll-linked ramp | **Fixed** — scroll is now the only authority |
| 6 | major | The background steps ~2× in brightness in one frame at the Pixel B → Tracks hand-over: the mosaic resolves into its own 3×3 noise approximation of the mesh, not the real 4×4 lattice | **Fixed** — one shared field, one shared clock |
| 9 | major | **Found while fixing #6:** the dark beat never darkened. `DARK_BEAT_DIM` was dead code | **Fixed** — the ramp had no signal to ramp on |
| 7 | minor | No footer landmark: the closing section was a plain `<div>` | **Fixed** — now `<footer>` |
| 8 | minor | No LCP candidate; mobile performance headroom is thin (78–80 against a target of 75) | **No action** — target is met |

### Notes on the fixes

**#2 — the lock is input-only, deliberately.** The obvious implementation is `lenis.stop()`, and it
is wrong: it also freezes *programmatic* scrolling, which a fragment entry (`/#scene-tracks`), a
browser-restored reload and the skip link all depend on. The first attempt did exactly that and also
forced `scrollTo(0)`, which broke four deep-link tests by overriding an intentional landing position
rather than protecting it. The shipped version prevents the wheel and touch gestures only — the
precise thing that caused the defect, and nothing else. Non-passive listeners are required, or
`preventDefault()` is ignored.

**#3 — gated on reducer state, not geometry.** The tracks section scrolls into frame while the beat
is still running, so position can never express "the beat has finished". The reducer already
computed `darkBeat` correctly; nothing consumed it. `entered={!transitionState.darkBeat}` now gates
the composition, reflected as `data-tracks-entered` so the page seam can assert it — previously this
defect was *not expressible* at any seam, which is why the hand-off spec was green across it. The
gate is opacity-only: `hidden`/`inert`/`display:none` would pull the eleven track titles out of the
server-rendered DOM that brief §17 requires be readable without JavaScript.

**#5 — one authority instead of two.** The mesh now stays the active background mode until its own
scroll-linked `fadeToBlack` ramp reaches 1, and only then does `footerLight` take over. By that point
the mesh is already black, so the canvas's handover is black-to-black and invisible. Note the triage
corrected the reporting agent here: this was **not** a reversibility violation — the round trip was
measured and returns exactly. What failed was that the fade was not distributed across its budget.

**#6 — one field, one clock.** The mesh's field is now defined once, in `MESH_FIELD_GLSL`, and both
programs include it; the mosaic's `dropMonoMeshLook` is a thin adapter onto `dropMeshFieldColor`.
Identical functions are not enough on their own — two clocks at different phases would still jump —
so the clock is a module-level singleton (`sharedMeshTime`), idempotent per frame, which is sound
because there is exactly one background canvas by design (brief §12).

Measured, with all scene DOM hidden so both sides show only the canvas:

| | last Pixel B frame | first Tracks frame | ratio |
|---|---:|---:|---:|
| before | 0.0693 | 0.1177 | **1.70×** |
| after | 0.2606 | 0.2570 | **0.99×** |

The remaining brightness change across the beat's end is intended and is *not* this defect: the beat
is dark by design and gives way to a lit scene. What must not change is the field's identity, and it
no longer does.

**#9 — the dark beat never darkened (found while fixing #6).** With the field unified, the beat
looked bright, so the dim was investigated. `darkBeatAmount` ramped on `progress - onset`, where
onset is the progress at which the reducer first raises the beat — but the reducer raises it exactly
when the scene's progress **saturates at 1**, and it then holds at 1 for the rest of the scroll
budget. So onset was captured at 1, every later frame took `min(1, 1)`, the delta stayed 0, and the
dim was permanently off.

Proved rather than reasoned: setting `DARK_BEAT_DIM` to `0.0` changed the frame's luminance by
nothing at all (0.2545 either way). The ramp now runs on the *approach* to 1 and then holds while the
reducer holds the beat — still a pure function of scroll state, so it scrubs backwards as it played
forwards. The beat now measures **0.023 against the lit scene's 0.266** — 9% of its luminance.

This one was invisible to the QA sweep because the acceptance box reads "a completed dark beat
precedes the Tracks entrance": the specs asserted the beat's *emptiness*, which is DOM state, and
never its *darkness*, which is canvas pixels and therefore never asserted by design.

**#7 — no explicit `role="contentinfo"`.** The element sits inside the scene machine's `<section>`
and inside `<main>`, and HTML-AAM only maps `<footer>` to `contentinfo` when it is *not* a descendant
of section/article/main. Forcing the role would trip axe's `landmark-contentinfo-is-top-level` rule —
trading a missing landmark for a real violation. A true top-level landmark means rendering the footer
scene outside `<main>`, which changes the element the scene machine pins. Flagged, not done.

## Dismissed by triage

- **"Mobile performance below the ≥75 target."** Measured 49/89 and 65/64 by an agent on a machine
  at load average 185–478 with four other agents running. Re-measured twice on an idle machine:
  **78/80 and 79/79 mobile, 98 desktop, accessibility 96, best practices 100, CLS 0** on both routes.
  A contention artifact, not a product defect. To that agent's credit it labelled its own numbers a
  floor and asked for a re-measure.
- **"No LCP candidate" filed separately from the above** — one finding at two levels of description;
  merged, and only the mechanism survives as minor headroom.

## Lighthouse — brief §17 gate

All four targets met, stably, across two idle-machine runs and both routes:

| Target | Required | Measured |
|---|---:|---:|
| Accessibility | ≥ 95 | 96 |
| Best practices | ≥ 90 | 100 |
| Mobile performance | ≥ 75 | 78–80 |
| CLS | < 0.1 | 0 |

**Lighthouse's accessibility score says nothing about text over the shaders** — its contrast rule
silently skips text drawn over a canvas. That measurement is separate: see `contrast-audit.md`,
where a real AA failure (worst case 1.00:1) was found and fixed.

## Still `[manual]`

Never fake these with an automated test:

- **fps profiling** — 60fps capable desktop / ≥30fps mid-range mobile on the heaviest scenes (tracks
  coverflow, pixel transitions, footer light), with named hardware. Not measured.
- **Mesh continuity by eye** across Tracks → Art Pieces: screen-record a slow continuous scroll and
  watch one bright lobe across the boundary — it must keep drifting at the same phase, only slowing
  and darkening. Repeat with the tab backgrounded mid-crossing, since the mesh clock clamps frame
  deltas and a fast-forward would show. The automated half is done: seam 2 proves the descriptor
  never goes null and the variant changes exactly once; seam 3 proves the mode stays `monoMesh`.
- **The dark beat's feel** — that the pause reads as intentional rather than as a stall.
- **Footer entry** — that the mesh visibly loses contrast gradually rather than snapping.
- **Shader look** against the supplied references.
- **Contrast in the remaining shader scenes** — the corrected sweep covered Tracks; Thesis, Films and
  Footer were spot-checked only.
