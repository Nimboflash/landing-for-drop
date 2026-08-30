# Contrast audit — text over live shaders

Brief §16 requires WCAG AA text contrast; §14 forbids "shader motion that lowers text contrast".
Ticket 15 marks this `[manual]` for a specific reason: **Lighthouse's contrast rule silently skips
text drawn over a `<canvas>`**, so a passing accessibility score says nothing about any of the
shader scenes. This file records the measurement that actually was performed.

Measured on the dev server at 1440×900, Chromium (Playwright), 2026-08-22.

## Method

Automating this correctly is harder than it looks, and three plausible approaches give wrong answers.
Recording them so nobody repeats them:

1. **`gl.readPixels` on the live canvas** returns all-black. The drawing buffer is not preserved
   after compositing (`preserveDrawingBuffer` is false, correctly — preserving it costs performance).
2. **Screenshot the text's bounding box and treat non-glyph pixels as background.** Anti-aliased
   glyph edges are intermediate colours and get counted as background, inflating the failure count.
   This produced a bogus "59 failures" run.
3. **Set `element.style.visibility = "hidden"` then screenshot.** GSAP rewrites inline styles every
   tick and clobbers it before the screenshot lands.

What works:

- Mark the exact leaf text nodes with a class, then hide them with a stylesheet rule using
  `!important` — a stylesheet `!important` beats GSAP's inline styles, and marking *leaves only*
  matters because hiding by tag name also hides an ancestor (`li.track`) and takes its
  reading-ground pseudo-element with it. That mistake made a working fix look broken.
- Let crossfades **settle** before sampling. WCAG is judged at rest; a caption caught at opacity 0.5
  mid-transition is not a conformance failure.
- Sample **several frames**, because the mesh drifts under the text.
- Compare against WCAG thresholds by computed size: 3.0:1 for large text (≥24px, or ≥18.66px bold),
  4.5:1 otherwise.

Caveat: React re-renders can drop the marker class from a node between marking and screenshotting.
Any result whose sampled background equals the text colour exactly is that artifact, not a finding.

## Finding — Tracks scene (fixed)

The Monochrome Mesh's control colours run to `#E4E4E6` (brief §7.8), so its light lobes drift behind
the caption and heading. Measured **28 failures at rest**:

| Element | Colour | Size | Required | Measured |
|---|---|---:|---:|---:|
| Group label (time-of-day) | `#ff5a00` | 10.88px | 4.5:1 | **1.00:1** |
| Track title | `#fffffe` | 34.56px | 3.0:1 | 1.65:1 |
| Artist | `#f2f2f2` | 19.44px | 4.5:1 | 1.81:1 |
| `TRACKS` heading | `#f2f2f2` | 54.72px | 3.0:1 | 1.26:1 |

The orange label at 1.00:1 was effectively invisible whenever a light lobe passed behind it.

### Fix

1. **Reading ground** (`.readingGround` in `TracksScene.module.css`) — a feathered horizontal band
   that darkens the mesh behind the heading and the caption. Brief §7.9 already sanctions darkening
   the mesh for reading comfort, so this is in-language rather than a new device. A horizontal band,
   not a radial ellipse: an ellipse only darkens the middle, leaving the ends of a long title under
   AA. The alpha plateau spans 22–78% so every line sits on full ground rather than in the feather.
2. **Group label off DROP orange.** Brief §4 reserves orange for "light, transition, and atmospheric
   energy" — not for text. It now renders in off-white and stays subordinate through size and
   letter-spacing instead of hue.

**Result: 0 failures at rest** across 24 sampled text nodes, four scroll positions, three frames each.

## Still `[manual]`, not yet executed

- **Mid-transition contrast.** Measured at rest by design. A caption crossfading through ~0.5 opacity
  dips below AA transiently. Judged acceptable (WCAG conformance is evaluated at rest), but it is a
  judgment call, not a measurement — flag it if an accessibility reviewer disagrees.
- **Other shader scenes.** The sweep above covers Tracks. Thesis (over `offWhiteGlow`), Films (over
  Wavy Dots) and Footer (over the light horizon) were spot-checked but not swept at rest with the
  corrected method. Re-run the corrected script per scene before launch.
- **fps profiling** — 60fps capable desktop / ≥30fps mid-range mobile on the heaviest scenes
  (tracks coverflow, pixel transitions, footer light), with named hardware. Not measured.
- **Shader look** against the supplied references — verified by eye only.
