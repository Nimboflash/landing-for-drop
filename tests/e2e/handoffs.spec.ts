import { expect, test as base, type Page } from "@playwright/test";

/**
 * Page seam (BUILD-GUIDE seam 3) for the three CROSS-SCENE HAND-OFFS — the boundaries no single
 * scene ticket owns (ticket 15, first acceptance box):
 *
 * 1. brief §7.7 — pixel transition B: film content fades while film 03 is still on stage, a short
 *    empty dark beat is held, and only then does the tracks scene take over;
 * 2. brief §7.9 — the Monochrome Mesh continues from Tracks into Art Pieces without a cut;
 * 3. brief §7.10 — the mesh fades to black and the footer light horizon takes over.
 *
 * ## What this file may assert
 *
 * **Data attributes and text only.** Every value read below is an attribute a scene reflects its
 * logical state into from reducer output — `data-active-scene`, `data-background-mode`,
 * `data-film-fade`, `data-film-fade-percent`, `data-film-hold`, `data-track-index`,
 * `data-reveal-percent`, `data-active`/`data-index` on a film row. Never a computed style, never
 * an inline transform or opacity (Playwright's visibility heuristic is wrong for them: an element
 * at `opacity: 0` and a back-facing 3D element both still count as "visible"), never GSAP
 * internals, and never a canvas pixel — what the shader LOOKS like across these boundaries is
 * `[manual]` visual QA, recorded in the PR, not an automated assertion.
 *
 * **Ordinal, never absolute.** Scroll budgets are tunable by design. Scroll positions are used
 * only to NAVIGATE — each scene's own section supplies the range its ScrollTrigger reports over,
 * exactly as `useSceneStateMachine` documents it (`start: "top top"` → `end: "bottom bottom"`) —
 * and the assertions are about the ORDER of the states observed along the way, their monotonicity,
 * and how many distinct stages a scroll-linked value passes through. No expectation names a
 * position, a percentage, or a budget, so retuning the pacing cannot make this file pass or fail.
 *
 * The reducer-side half of the same three hand-offs — continuity of the descriptors themselves,
 * both directions, across several lens shapes — lives at seam 2 in
 * `tests/unit/scene-state.test.ts` ("cross-scene hand-offs"). This file only proves the part that
 * is genuinely DOM-observable.
 *
 * ## What these tests deliberately do NOT prove
 *
 * Three hand-off defects were found by hand while writing this file. None of them is expressible
 * at any of the three seams, because each is about what the shared canvas PAINTS, and canvas
 * pixels are never asserted. They are recorded here so a green run is not mistaken for a clean
 * hand-off, and each is filed against the file that owns it:
 *
 * 1. the tracks composition is already in frame during the dark beat (see the note on that test);
 * 2. the mesh's scroll-linked fade to black is overridden by the canvas's own time-based mode
 *    crossfade, so the footer entry is a ~0.4s dissolve rather than a scrubbed contrast loss;
 * 3. pixel B ends on a dimmed approximation of the mesh and the real mesh mode is hard-swapped in
 *    at full brightness, so the tracks entrance opens with a step up in background brightness.
 */

/* ------------------------------------------------------- expectations, from the source docs */

/** Brief §6, "Master Experience Sequence" — the only scene ids that may appear. */
const SCENE_ORDER_FROM_BRIEF = [
  "loader",
  "thesis",
  "menu",
  "gridStatement",
  "pixelA",
  "films",
  "pixelB",
  "tracks",
  "artPieces",
  "footer",
] as const;

/** W04 seed — `handoff/04-mock-content/…/beautiful-imperfection.mock.json` carries three films. */
const FILM_COUNT = 3;

/**
 * Brief §7.7, "Exact sequence": film content is held, then fades with continued scroll, then is
 * gone for the empty dark beat. `FilmScene` reflects exactly these three phases.
 */
const FILM_FADE_PHASES = ["held", "fading", "cleared"] as const;

/** Brief §7.8 / §7.9: Tracks and Art Pieces share one background mode — the Monochrome Mesh. */
const MESH_MODE = "monoMesh";
/** Brief §7.10: the footer's prismatic light horizon. */
const FOOTER_MODE = "footerLight";

/**
 * How many distinct in-between stages a scroll-linked value has to show before it counts as
 * progressive rather than a jump. A step change shows none however the budget is tuned.
 */
const MIN_INTERMEDIATE_STAGES = 3;

/* ------------------------------------------------------------------------------- fixtures */

/** Brief §17: "No console errors, WebGL warnings, or accumulating ScrollTriggers." */
const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
      await use(errors);
      expect(errors, "the page must produce no console errors").toEqual([]);
    },
    { auto: true },
  ],
});

/* -------------------------------------------------------------------------------- helpers */

type SceneId = (typeof SCENE_ORDER_FROM_BRIEF)[number];

/**
 * One scene's scroll range, read off its own section element.
 *
 * This is NAVIGATION, not an expectation: it reproduces the trigger geometry `useSceneStateMachine`
 * documents (`start: "top top"` → `end: "bottom bottom"`) so a test can put the page anywhere
 * inside a scene without knowing a single budget number. Nothing is asserted about these values.
 */
async function sceneRange(page: Page, sceneId: SceneId): Promise<{ start: number; end: number }> {
  const range = await page.evaluate((id) => {
    const section = document.getElementById(`scene-${id}`);
    if (!section) return null;
    const box = section.getBoundingClientRect();
    const top = box.top + window.scrollY;
    return { start: top, end: top + box.height - window.innerHeight };
  }, sceneId);

  expect(range, `scene section "${sceneId}" must be in the document`).not.toBeNull();
  return range as { start: number; end: number };
}

/** Two animation frames: one for the scroll to be observed, one for the render it causes. */
async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

async function scrollTo(page: Page, top: number): Promise<void> {
  await page.evaluate((value) => {
    window.scrollTo({ top: value, behavior: "instant" as ScrollBehavior });
  }, top);
  await settle(page);
}

/**
 * Everything one sample of the page reports about the hand-offs, read in a single round trip.
 * Attributes only — every one of them is reducer output that a scene has reflected into the DOM.
 */
type Frame = {
  activeScene: string | null;
  backgroundMode: string | null;
  filmFade: string | null;
  filmFadePercent: number | null;
  filmHold: string | null;
  activeFilmIndex: string | null;
  trackIndex: string | null;
  footerRevealPercent: number | null;
};

async function readFrame(page: Page): Promise<Frame> {
  return page.evaluate(() => {
    const attribute = (selector: string, name: string): string | null =>
      document.querySelector(selector)?.getAttribute(name) ?? null;
    const numeric = (selector: string, name: string): number | null => {
      const raw = attribute(selector, name);
      return raw === null ? null : Number(raw);
    };

    return {
      activeScene: attribute("[data-active-scene]", "data-active-scene"),
      backgroundMode: attribute("[data-background-mode]", "data-background-mode"),
      filmFade: attribute("[data-film-fade]", "data-film-fade"),
      filmFadePercent: numeric("[data-film-fade-percent]", "data-film-fade-percent"),
      filmHold: attribute("[data-film-hold]", "data-film-hold"),
      activeFilmIndex: attribute("[data-film][data-active='true']", "data-index"),
      trackIndex: attribute("[data-tracks-carousel]", "data-track-index"),
      footerRevealPercent: numeric("[data-reveal-percent]", "data-reveal-percent"),
    };
  });
}

/**
 * Sample the page at evenly spaced scroll positions between two points.
 *
 * Sweeps are built one SEGMENT at a time — a scene's own trigger window, then the hand-over
 * viewport after it — rather than as one uniform pass over the whole crossing. That is not a
 * detail: the mobile breakpoint deliberately scales every scroll budget down (brief §15, "Avoid
 * long pinned sections that feel trapped on mobile"), so a uniform sweep spends most of its
 * samples in the hand-over gaps and can walk straight past a short transition without seeing it.
 * Segment sweeps sample each scene at its own scale, on every viewport.
 */
async function sweep(page: Page, from: number, to: number, steps: number): Promise<Frame[]> {
  const frames: Frame[] = [];
  for (let step = 0; step <= steps; step += 1) {
    await scrollTo(page, from + ((to - from) * step) / steps);
    frames.push(await readFrame(page));
  }
  return frames;
}

/** Several sweeps end to end, as one list of samples in scroll order. */
async function sweepSegments(
  page: Page,
  segments: readonly [number, number, number][],
): Promise<Frame[]> {
  const frames: Frame[] = [];
  for (const [from, to, steps] of segments) {
    frames.push(...(await sweep(page, from, to, steps)));
  }
  return frames;
}

/** A point a fraction of the way through a scene's own trigger window. */
function within(range: { start: number; end: number }, fraction: number): number {
  return range.start + (range.end - range.start) * fraction;
}

/** Consecutive duplicates collapsed, so a sequence reads as the runs of states it is made of. */
function runsOf<T>(values: readonly T[]): T[] {
  return values.filter((value, index) => index === 0 || value !== values[index - 1]);
}

function isNonIncreasing(values: number[]): boolean {
  return values.every((value, index) => index === 0 || value <= values[index - 1]);
}

function isNonDecreasing(values: number[]): boolean {
  return values.every((value, index) => index === 0 || value >= values[index - 1]);
}

/** Distinct values strictly between "not started" and "finished". */
function intermediateStages(values: number[], min: number, max: number): number[] {
  return [...new Set(values.filter((value) => value > min && value < max))];
}

function column<K extends keyof Frame>(frames: Frame[], key: K): Frame[K][] {
  return frames.map((frame) => frame[key]);
}

function numericColumn(frames: Frame[], key: keyof Frame): number[] {
  return frames.map((frame) => {
    const value = frame[key];
    expect(value, `${String(key)} must be reported on every sample`).not.toBeNull();
    return Number(value);
  });
}

/* ---------------------------------------------------------------------------------- tests */

test.describe.configure({ timeout: 120_000 });

test.beforeEach(async ({ page }) => {
  const response = await page.goto("/");
  expect(response?.status()).toBe(200);
  await settle(page);
});

/* ---------------------------------- 1. brief §7.7 — pixel B dark beat -> tracks entrance */

test("film content fades across pixel B with the last film still on stage, never cut", async ({
  page,
}) => {
  // The films hand-over, where the film is still held, then the whole of transition B.
  const films = await sceneRange(page, "films");
  const pixelB = await sceneRange(page, "pixelB");
  const frames = await sweepSegments(page, [
    [films.end, pixelB.start, 4],
    [pixelB.start, pixelB.end, 24],
  ]);

  // Brief §7.7 step 1: "Film 03 remains visible" — the last film by the seed's own count.
  const onStage = new Set(column(frames, "activeFilmIndex"));
  expect([...onStage]).toEqual([String(FILM_COUNT - 1)]);

  // Steps 2-6: held, then fading with continued scroll, then cleared for the beat. Three phases,
  // in that order, each entered exactly once — a cut would skip "fading" entirely.
  expect(runsOf(column(frames, "filmFade"))).toEqual([...FILM_FADE_PHASES]);

  // The fade is scroll-linked, so it passes through many distinct stages on the way down.
  const fade = numericColumn(frames, "filmFadePercent");
  expect(fade[0]).toBe(100);
  expect(fade[fade.length - 1]).toBe(0);
  expect(isNonIncreasing(fade)).toBe(true);
  expect(intermediateStages(fade, 0, 100).length).toBeGreaterThanOrEqual(MIN_INTERMEDIATE_STAGES);

  // No scene after pixel B has begun anywhere in that range.
  expect(runsOf(column(frames, "activeScene"))).toEqual(["films", "pixelB"]);
});

/**
 * KNOWN GAP — read before trusting this test's name to mean more than it proves.
 *
 * What is asserted here is that the reducer holds the beat: pixel B is still the active scene,
 * the film has cleared, the carousel has not started, and the tracks scene has not begun. What
 * CANNOT be asserted at this seam is whether the beat is visually empty — and by hand, on a
 * 1280x800 production build, it is not: from roughly a quarter of the way through the hand-over
 * viewport the TRACKS heading and the jewel-case coverflow are already inside the frame while the
 * page still reports `data-active-scene="pixelB"`. Brief §7.7 puts the Tracks entrance at step 7,
 * AFTER the beat of step 6. Reported as a defect against the shell, which renders the tracks
 * section's content ungated by any reducer output; there is no data attribute for "the tracks
 * composition has entered", so no honest assertion can be written here until one exists.
 *
 * Manual procedure: open `/`, scroll to the pixel B section's bottom edge, then a further quarter
 * of a viewport, and screenshot. Expected: an empty dark frame. Actual: the Tracks title and cases.
 */
test("the dark beat holds after the film clears and before the tracks scene takes over", async ({
  page,
}) => {
  const films = await sceneRange(page, "films");
  const pixelB = await sceneRange(page, "pixelB");
  const tracks = await sceneRange(page, "tracks");
  // Transition B, then its hand-over, then far enough in that tracks has certainly taken over.
  const frames = await sweepSegments(page, [
    [films.end, pixelB.start, 2],
    [pixelB.start, pixelB.end, 20],
    [pixelB.end, tracks.start, 8],
    [tracks.start, within(tracks, 0.1), 4],
  ]);

  const scenes = column(frames, "activeScene");
  const beat = frames.map(
    (frame) => frame.activeScene === "pixelB" && frame.filmFade === "cleared",
  );

  const lastBeat = beat.lastIndexOf(true);
  const firstTracks = scenes.indexOf("tracks");

  // Brief §7.7 steps 6-7: the beat exists, is held while pixel B is still the active scene, and
  // is over before the tracks scene begins.
  expect(lastBeat, "the dark beat must be observable").toBeGreaterThan(-1);
  expect(firstTracks, "the tracks scene must be reached").toBeGreaterThan(-1);
  expect(lastBeat).toBeLessThan(firstTracks);

  // The film side of "empty": the film scene reports it is no longer holding content, for every
  // sample of the beat. (The tracks side is the known gap documented above.)
  for (const frame of frames.filter((_, index) => beat[index])) {
    expect(frame.filmHold).toBe("false");
    // …and nothing of the carousel has started — it is still on its first track.
    expect(frame.trackIndex).toBe("0");
  }

  expect(runsOf(scenes)).toEqual(["films", "pixelB", "tracks"]);
});

test("reverse scroll brings the film back through the same fade, never as a cut", async ({
  page,
}) => {
  const films = await sceneRange(page, "films");
  const pixelB = await sceneRange(page, "pixelB");
  const tracks = await sceneRange(page, "tracks");

  const frames = await sweepSegments(page, [
    [within(tracks, 0.05), pixelB.end, 6],
    [pixelB.end, pixelB.start, 24],
    [pixelB.start, films.end, 4],
  ]);

  expect(runsOf(column(frames, "filmFade"))).toEqual([...FILM_FADE_PHASES].reverse());
  expect(isNonDecreasing(numericColumn(frames, "filmFadePercent"))).toBe(true);
  // The scenes hand back in the mirrored order, with nothing skipped.
  expect(runsOf(column(frames, "activeScene"))).toEqual(["tracks", "pixelB", "films"]);
});

/* -------------------------- 2. brief §7.9 — the Monochrome Mesh continues, uncut, into art */

test("the mesh background is never cut between tracks and art pieces", async ({ page }) => {
  const tracks = await sceneRange(page, "tracks");
  const art = await sceneRange(page, "artPieces");
  // The back half of tracks, the hand-over viewport between them, then the front half of art.
  const segments: [number, number, number][] = [
    [within(tracks, 0.5), tracks.end, 8],
    [tracks.end, art.start, 6],
    [art.start, within(art, 0.5), 8],
  ];

  const forward = await sweepSegments(page, segments);

  // Brief §7.9: "The Monochrome Mesh continues from Tracks without restarting or cutting."
  // The shared canvas only ever swaps or crossfades a background when the MODE changes, so a mode
  // that never changes across the boundary is the DOM-observable half of "no cut". What the field
  // looks like while the variant slows and darkens is `[manual]` visual QA.
  expect([...new Set(column(forward, "backgroundMode"))]).toEqual([MESH_MODE]);
  expect(runsOf(column(forward, "activeScene"))).toEqual(["tracks", "artPieces"]);

  const backward = await sweepSegments(
    page,
    [...segments].reverse().map(([from, to, steps]) => [to, from, steps] as [number, number, number]),
  );
  expect([...new Set(column(backward, "backgroundMode"))]).toEqual([MESH_MODE]);
  expect(runsOf(column(backward, "activeScene"))).toEqual(["artPieces", "tracks"]);
});

/* ------------------------------------ 3. brief §7.10 — mesh fade to black -> footer horizon */

/**
 * KNOWN GAP — this test proves the two things the DOM reports (the mode hands over once, in the
 * right order, and the horizon reveal is scroll-linked and reversible). It does NOT prove the
 * clause of brief §7.10 that comes first: "The Mesh gradually loses contrast and fades to pure
 * black." The reducer does emit that fade progressively (seam 2 proves it), but the shared canvas
 * unmounts the outgoing mesh layer on its own ~0.4s timer, so by hand the field is already gone at
 * a footer position where the reducer still has it near full brightness. Filed as a defect.
 *
 * Manual procedure: scroll to about 5% into the footer section's window, wait two seconds without
 * scrolling, and screenshot. Expected: the mesh still largely present, dimming as scroll advances.
 * Actual: pure black, whatever the scroll position, once the timer has run.
 */
test("the footer horizon takes over from the mesh progressively, and reverses", async ({
  page,
}) => {
  const art = await sceneRange(page, "artPieces");
  const footer = await sceneRange(page, "footer");
  const segments: [number, number, number][] = [
    [within(art, 0.9), art.end, 3],
    [art.end, footer.start, 4],
    [footer.start, footer.end, 20],
  ];

  const forward = await sweepSegments(page, segments);

  // The mesh holds the frame until the footer scene begins, then the horizon takes over — one
  // change of background mode, in that order.
  expect(runsOf(column(forward, "backgroundMode"))).toEqual([MESH_MODE, FOOTER_MODE]);
  expect(runsOf(column(forward, "activeScene"))).toEqual(["artPieces", "footer"]);

  // "The light… Scroll controls the main reveal" (brief §7.10): scroll-linked, so it climbs
  // through many distinct stages rather than switching on.
  const reveal = numericColumn(forward, "footerRevealPercent");
  expect(reveal[0]).toBe(0);
  expect(reveal[reveal.length - 1]).toBe(100);
  expect(isNonDecreasing(reveal)).toBe(true);
  expect(intermediateStages(reveal, 0, 100).length).toBeGreaterThanOrEqual(
    MIN_INTERMEDIATE_STAGES,
  );

  const backward = await sweepSegments(
    page,
    [...segments].reverse().map(([from, to, steps]) => [to, from, steps] as [number, number, number]),
  );
  expect(runsOf(column(backward, "backgroundMode"))).toEqual([FOOTER_MODE, MESH_MODE]);
  const reverseReveal = numericColumn(backward, "footerRevealPercent");
  expect(isNonIncreasing(reverseReveal)).toBe(true);
  expect(reverseReveal[reverseReveal.length - 1]).toBe(0);
});
