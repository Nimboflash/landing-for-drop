/**
 * Scene-state seam (BUILD-GUIDE seam 2) — the page-level reducer.
 *
 * Assertions here are ORDINAL / STRUCTURAL only: scene order, mode mapping, counts derived
 * from data, monotonicity, symmetry, one-shot semantics, input precedence. Absolute progress
 * thresholds are never asserted — scroll budgets are tunable by design, so pinning a boundary
 * would only re-derive the implementation's own config.
 *
 * Expected values come from the brief (Sections 6, 8, 14) and the validated W04 seed content,
 * never from recomputing the way the reducer computes.
 */

import { describe, expect, it } from "vitest";

import { beautifulImperfectionLens } from "@/content/lenses/beautiful-imperfection";
import {
  PIXEL_SEED,
  SCENE_ORDER,
  createInitialSceneState,
  lensCounts,
  sceneStateReducer,
  type BackgroundMode,
  type InputEvent,
  type LensCounts,
  type SceneId,
  type SceneState,
  type TransitionState,
} from "@/lib/scene";

/* ------------------------------------------------------------- expectations */

/** Brief Section 6: the master experience sequence. */
const BRIEF_SCENE_SEQUENCE: SceneId[] = [
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
];

/**
 * Which shared-canvas background each scene runs on.
 *
 * Brief Sections 7 + 14 put the off-white glow behind the opening scenes and the Monochrome Mesh
 * behind Tracks and Art Pieces. That pairing has since been swapped by an explicit art-direction
 * decision: the mesh opens the page and Tracks / Art Pieces sit on flat black.
 */
const BRIEF_BACKGROUND_MODE: Array<[SceneId, BackgroundMode]> = [
  ["loader", "monoMesh"],
  ["thesis", "monoMesh"],
  ["menu", "monoMesh"],
  ["gridStatement", "greenGrid"],
  ["pixelA", "pixelA"],
  ["films", "wavyDots"],
  ["pixelB", "pixelB"],
  ["tracks", "black"],
  ["artPieces", "black"],
  ["footer", "footerLight"],
];

/** Brief Section 8: no header during the loader, then contrast follows the scene background. */
const BRIEF_HEADER_VARIANT: Array<[SceneId, TransitionState["headerVariant"]]> = [
  ["loader", "hidden"],
  // Dark grounds all the way down now the mesh opens the page, so the mark stays light
  // everywhere it is shown. `dark` is reachable only from `offWhiteGlow`, which no scene uses.
  ["thesis", "light"],
  ["menu", "light"],
  ["gridStatement", "light"],
  ["pixelA", "light"],
  ["films", "light"],
  ["pixelB", "light"],
  ["tracks", "light"],
  ["artPieces", "light"],
  ["footer", "light"],
];

/* ----------------------------------------------------------------- fixtures */

const W04_COUNTS = lensCounts(beautifulImperfectionLens);

/**
 * A deliberately different lens shape — every count differs from W04, including the film
 * count, because the reducer must not know the content schema's current film invariant.
 */
const SYNTHETIC_COUNTS: LensCounts = {
  heroMessages: 5,
  menuItems: 6,
  films: 5,
  tracks: 4,
  artPieces: 7,
};

/** The minimum content the schema allows, to prove no index ever leaves range. */
const MINIMUM_COUNTS: LensCounts = {
  heroMessages: 1,
  menuItems: 2,
  films: 1,
  tracks: 1,
  artPieces: 1,
};

const COUNT_FIXTURES: Array<[string, LensCounts]> = [
  ["W04 beautiful-imperfection", W04_COUNTS],
  ["a synthetic lens", SYNTHETIC_COUNTS],
];

/* ------------------------------------------------------------------ helpers */

function scroll(sceneId: SceneId, progress: number): InputEvent {
  return { type: "scrollProgress", sceneId, progress };
}

function trace(counts: LensCounts, events: InputEvent[], from?: SceneState): SceneState[] {
  const states: SceneState[] = [];
  let state = from ?? createInitialSceneState(counts);
  for (const event of events) {
    state = sceneStateReducer(state, event, counts);
    states.push(state);
  }
  return states;
}

function run(counts: LensCounts, events: InputEvent[], from?: SceneState): SceneState {
  const states = trace(counts, events, from);
  return states[states.length - 1] ?? from ?? createInitialSceneState(counts);
}

/** Scroll the page down to the start of a scene, the way the page actually arrives at it. */
function enter(counts: LensCounts, sceneId: SceneId): SceneState {
  const target = SCENE_ORDER.indexOf(sceneId);
  const events: InputEvent[] = [];
  for (let i = 0; i < target; i += 1) {
    events.push(scroll(SCENE_ORDER[i], 0), scroll(SCENE_ORDER[i], 1));
  }
  events.push(scroll(sceneId, 0));
  return run(counts, events);
}

function ladder(steps: number): number[] {
  return Array.from({ length: steps + 1 }, (_, i) => i / steps);
}

/** Every state produced by scrubbing one scene from 0 to 1. */
function sweepScene(counts: LensCounts, sceneId: SceneId, steps = 40): SceneState[] {
  const start = enter(counts, sceneId);
  return trace(
    counts,
    ladder(steps).map((progress) => scroll(sceneId, progress)),
    start,
  );
}

const FULL_SWEEP_STEPS = [0, 0.25, 0.5, 0.75, 1];

function fullSweepEvents(): InputEvent[] {
  return SCENE_ORDER.flatMap((sceneId) =>
    FULL_SWEEP_STEPS.map((progress) => scroll(sceneId, progress)),
  );
}

function bandProgress(band: number, count: number): number {
  return (band + 0.5) / count;
}

function unique(values: number[]): number[] {
  return [...new Set(values)].sort((a, b) => a - b);
}

function range(count: number): number[] {
  return Array.from({ length: count }, (_, i) => i);
}

function isNonDecreasing(values: number[]): boolean {
  return values.every((value, i) => i === 0 || value >= values[i - 1]);
}

function isNonIncreasing(values: number[]): boolean {
  return values.every((value, i) => i === 0 || value <= values[i - 1]);
}

/* --------------------------------------------------------- cross-scene hand-offs */

/**
 * Steps per scene when a hand-off is under test. Fine enough that a value which is genuinely
 * scroll-linked shows many distinct stages, and a value that steps shows none — which is the
 * difference the brief's "must not disappear abruptly" (§7.7) and "gradually loses contrast"
 * (§7.10) are actually about. It is a sampling rate, never a threshold.
 */
const HANDOFF_STEPS = 200;

/** How many distinct in-between stages a value has to show before it counts as scroll-linked. */
const MIN_INTERMEDIATE_STAGES = 5;

/** The distinct values strictly inside 0..1 — the stages between "not started" and "finished". */
function intermediateStages(values: number[]): number[] {
  return unique(values.filter((value) => value > 0 && value < 1));
}

/** Consecutive duplicates collapsed, so a sequence of variants reads as the runs it is made of. */
function runsOf<T>(values: readonly T[]): T[] {
  return values.filter((value, i) => i === 0 || value !== values[i - 1]);
}

/**
 * Scrub across one scene boundary forward: the outgoing scene to its end, then the incoming one
 * from its start. That is exactly what the page's per-scene ScrollTriggers report — `onLeave`
 * fires (k, 1) as scene k is left downward, and the next scene's trigger takes over from 0.
 */
function crossForward(
  counts: LensCounts,
  from: SceneId,
  to: SceneId,
  steps = HANDOFF_STEPS,
): SceneState[] {
  return trace(
    counts,
    [
      ...ladder(steps).map((progress) => scroll(from, progress)),
      ...ladder(steps).map((progress) => scroll(to, progress)),
    ],
    enter(counts, from),
  );
}

/**
 * The same boundary crossed upward, obeying the shell's documented hand-over rule: scrolling up
 * out of a scene reports the PREVIOUS scene at 1 (`onLeaveBack` in `useSceneStateMachine`),
 * because the hand-over belongs to the scene that just finished.
 */
function crossBackward(
  counts: LensCounts,
  from: SceneId,
  to: SceneId,
  steps = HANDOFF_STEPS,
): SceneState[] {
  const forward = crossForward(counts, from, to, steps);
  const descending = [...ladder(steps)].reverse();
  return trace(
    counts,
    [
      ...descending.map((progress) => scroll(to, progress)),
      // The hand-over itself, reported once — then the outgoing scene's own trigger takes over
      // just below 1, which is why the ladder resumes at its second rung.
      scroll(from, 1),
      ...descending.slice(1).map((progress) => scroll(from, progress)),
    ],
    forward[forward.length - 1],
  );
}

/** The mesh descriptors of a trace, with the states that carry no mesh dropped. */
function meshTrail(states: SceneState[]) {
  return states.map((state) => state.transitionState.mesh).filter((mesh) => mesh !== null);
}

/**
 * The mirrored-trajectory projection: scene, mode, indices and declarative descriptors.
 * `gridStatementRevealed` is excluded on purpose — it is a documented one-shot with reverse
 * hysteresis (covered by its own test), the single value that does not mirror.
 * `loaderComplete` / `reducedMotion` are sticky flags set by discrete events, not by scroll.
 */
function project(state: SceneState) {
  const t = state.transitionState;
  return {
    sceneId: state.sceneId,
    sceneProgress: state.sceneProgress,
    backgroundMode: state.backgroundMode,
    messageIndex: t.messageIndex,
    flippedCards: t.flippedCards,
    filmIndex: t.filmIndex,
    trackIndex: t.trackIndex,
    artIndex: t.artIndex,
    pixelA: t.pixelA,
    pixelB: t.pixelB,
    mesh: t.mesh,
    darkBeat: t.darkBeat,
    filmFade: t.filmFade,
    footerReveal: t.footerReveal,
    headerVariant: t.headerVariant,
  };
}

/* -------------------------------------------------------------------- tests */

describe("lensCounts", () => {
  it("derives every count from the validated lens arrays", () => {
    // Counts from the brief's W04 seed: 3 hero messages, 2 menu items, 3 films, 11 tracks, 4 art pieces.
    expect(lensCounts(beautifulImperfectionLens)).toEqual({
      heroMessages: 3,
      menuItems: 2,
      films: 3,
      tracks: 11,
      artPieces: 4,
    });
  });
});

describe("initial scene state", () => {
  it("starts on the loader with nothing revealed and no header", () => {
    const state = createInitialSceneState(W04_COUNTS);

    expect(state.sceneId).toBe("loader");
    expect(state.sceneProgress).toBe(0);
    expect(state.backgroundMode).toBe("monoMesh");
    expect(state.reducedMotion).toBe(false);
    expect(state.transitionState.headerVariant).toBe("hidden");
    expect(state.transitionState.loaderComplete).toBe(false);
    expect(state.transitionState.gridStatementRevealed).toBe(false);
    expect(state.transitionState.pixelA).toBeNull();
    expect(state.transitionState.pixelB).toBeNull();
    // The mesh is the loader's own ground now, so it is live from the very first frame — and at
    // the `opening` variant, which is legible on that first frame rather than ramping into it.
    expect(state.transitionState.mesh).toEqual({ variant: "opening", amount: 0 });
    expect(state.transitionState.filmFade).toBe(1);
    expect(state.transitionState.footerReveal).toBe(0);
  });
});

describe("scene sequence", () => {
  it("exposes the ten scenes in brief Section 6 order", () => {
    expect([...SCENE_ORDER]).toEqual(BRIEF_SCENE_SEQUENCE);
  });

  it("walks the scenes in that order as scroll progress arrives", () => {
    const states = trace(
      W04_COUNTS,
      BRIEF_SCENE_SEQUENCE.map((sceneId) => scroll(sceneId, 0.5)),
    );

    expect(states.map((state) => state.sceneId)).toEqual(BRIEF_SCENE_SEQUENCE);
  });

  it("clamps scene progress into 0..1", () => {
    expect(run(W04_COUNTS, [scroll("films", 1.7)]).sceneProgress).toBe(1);
    expect(run(W04_COUNTS, [scroll("films", -0.4)]).sceneProgress).toBe(0);
  });
});

describe.each(COUNT_FIXTURES)("scene state driven by %s", (_label, counts) => {
  it("maps every scene to its background mode, scrolling forward and in reverse", () => {
    for (const [sceneId, mode] of BRIEF_BACKGROUND_MODE) {
      expect(run(counts, [scroll(sceneId, 0.5)]).backgroundMode).toBe(mode);
    }

    let state = run(counts, fullSweepEvents());
    for (const [sceneId, mode] of [...BRIEF_BACKGROUND_MODE].reverse()) {
      state = sceneStateReducer(state, scroll(sceneId, 0.5), counts);
      expect(state.backgroundMode).toBe(mode);
    }
  });

  it("adapts the header logo contrast per scene and hides it on the loader", () => {
    for (const [sceneId, variant] of BRIEF_HEADER_VARIANT) {
      expect(run(counts, [scroll(sceneId, 0.5)]).transitionState.headerVariant).toBe(variant);
    }
  });

  it("steps the thesis through every hero message", () => {
    const indices = sweepScene(counts, "thesis").map((s) => s.transitionState.messageIndex);

    expect(indices[0]).toBe(0);
    expect(indices[indices.length - 1]).toBe(counts.heroMessages - 1);
    expect(unique(indices)).toEqual(range(counts.heroMessages));
    expect(isNonDecreasing(indices)).toBe(true);
  });

  it("flips every menu card exactly once across the deck scene", () => {
    const flipped = sweepScene(counts, "menu").map((s) => s.transitionState.flippedCards);

    expect(flipped[0]).toBe(0);
    expect(flipped[flipped.length - 1]).toBe(counts.menuItems);
    expect(unique(flipped)).toEqual(range(counts.menuItems + 1));
    expect(isNonDecreasing(flipped)).toBe(true);
  });

  it("shows one film at a time and reaches every film", () => {
    const indices = sweepScene(counts, "films").map((s) => s.transitionState.filmIndex);

    expect(indices[0]).toBe(0);
    expect(indices[indices.length - 1]).toBe(counts.films - 1);
    expect(unique(indices)).toEqual(range(counts.films));
    expect(isNonDecreasing(indices)).toBe(true);
  });

  it("scrolls the carousel through every track", () => {
    const indices = sweepScene(counts, "tracks").map((s) => s.transitionState.trackIndex);

    expect(indices[0]).toBe(0);
    expect(indices[indices.length - 1]).toBe(counts.tracks - 1);
    expect(unique(indices)).toEqual(range(counts.tracks));
    expect(isNonDecreasing(indices)).toBe(true);
  });

  it("reveals every art piece in editorial order", () => {
    const indices = sweepScene(counts, "artPieces").map((s) => s.transitionState.artIndex);

    expect(indices[0]).toBe(0);
    expect(indices[indices.length - 1]).toBe(counts.artPieces - 1);
    expect(unique(indices)).toEqual(range(counts.artPieces));
    expect(isNonDecreasing(indices)).toBe(true);
  });

  it("never moves an index backward while scroll progress moves forward", () => {
    const states = trace(counts, fullSweepEvents());

    expect(isNonDecreasing(states.map((s) => s.transitionState.messageIndex))).toBe(true);
    expect(isNonDecreasing(states.map((s) => s.transitionState.flippedCards))).toBe(true);
    expect(isNonDecreasing(states.map((s) => s.transitionState.filmIndex))).toBe(true);
    expect(isNonDecreasing(states.map((s) => s.transitionState.trackIndex))).toBe(true);
    expect(isNonDecreasing(states.map((s) => s.transitionState.artIndex))).toBe(true);
  });

  it("mirrors the whole index and mode trajectory when the scroll sequence reverses", () => {
    const events = fullSweepEvents();
    const forward = trace(counts, events);

    let state = forward[forward.length - 1];
    for (let i = events.length - 2; i >= 0; i -= 1) {
      state = sceneStateReducer(state, events[i], counts);
      expect(project(state)).toEqual(project(forward[i]));
    }
  });

  it("emits a pixel descriptor only inside its own transition, and both share one seed", () => {
    const inPixelA = run(counts, [scroll("pixelA", 0.5)]);
    const inPixelB = run(counts, [scroll("pixelB", 0.5)]);

    expect(inPixelA.transitionState.pixelA).toEqual({ seed: PIXEL_SEED, progress: 0.5 });
    expect(inPixelA.transitionState.pixelB).toBeNull();
    expect(inPixelB.transitionState.pixelB).toEqual({ seed: PIXEL_SEED, progress: 0.5 });
    expect(inPixelB.transitionState.pixelA).toBeNull();

    // Cell coordinates stay consistent between the two transitions.
    expect(inPixelA.transitionState.pixelA?.seed).toBe(inPixelB.transitionState.pixelB?.seed);

    expect(run(counts, [scroll("films", 0.5)]).transitionState.pixelA).toBeNull();
    expect(run(counts, [scroll("films", 0.5)]).transitionState.pixelB).toBeNull();
  });

  it("re-emits the same pixel seed with mirrored progress on reverse scroll", () => {
    const steps = ladder(8);
    const start = enter(counts, "pixelA");
    const forward = trace(
      counts,
      steps.map((progress) => scroll("pixelA", progress)),
      start,
    ).map((s) => s.transitionState.pixelA);

    const reverse = trace(
      counts,
      [...steps].reverse().map((progress) => scroll("pixelA", progress)),
      run(counts, steps.map((progress) => scroll("pixelA", progress)), start),
    ).map((s) => s.transitionState.pixelA);

    expect(reverse).toEqual([...forward].reverse());
    expect(reverse.every((descriptor) => descriptor?.seed === PIXEL_SEED)).toBe(true);
  });

  it("fades film content across pixel B instead of cutting it", () => {
    expect(
      sweepScene(counts, "films").every((s) => s.transitionState.filmFade === 1),
    ).toBe(true);

    const fades = sweepScene(counts, "pixelB").map((s) => s.transitionState.filmFade);

    expect(fades[0]).toBe(1);
    expect(fades[fades.length - 1]).toBe(0);
    expect(isNonIncreasing(fades)).toBe(true);
    expect(enter(counts, "tracks").transitionState.filmFade).toBe(0);
  });

  it("holds an empty dark beat at the end of pixel B, before any tracks content", () => {
    const states = sweepScene(counts, "pixelB");
    const beats = states.map((s) => s.transitionState.darkBeat);

    expect(beats[0]).toBe(false);
    expect(beats[beats.length - 1]).toBe(true);
    // The beat is empty: no film content is still on screen while it holds.
    expect(states.every((s) => !s.transitionState.darkBeat || s.transitionState.filmFade === 0)).toBe(
      true,
    );
    // Once it starts it runs to the end of the transition — one contiguous final stretch.
    expect(beats.slice(beats.indexOf(true)).every(Boolean)).toBe(true);
    // It belongs to pixel B alone.
    expect(sweepScene(counts, "films").every((s) => !s.transitionState.darkBeat)).toBe(true);
    expect(sweepScene(counts, "tracks").every((s) => !s.transitionState.darkBeat)).toBe(true);
  });

  it("keeps one mesh alive from the loader through the menu deck, and nothing after it", () => {
    // The mesh is the ground for the three opening scenes, at one variant throughout.
    for (const sceneId of ["loader", "thesis", "menu"] as const) {
      expect(
        sweepScene(counts, sceneId).every((s) => s.transitionState.mesh?.variant === "opening"),
      ).toBe(true);
    }

    // And for nothing else: every later scene runs on a ground of its own, so the reducer has
    // no mesh to hand the canvas there.
    for (const sceneId of [
      "gridStatement",
      "pixelA",
      "films",
      "pixelB",
      "tracks",
      "artPieces",
      "footer",
    ] as const) {
      expect(sweepScene(counts, sceneId).every((s) => s.transitionState.mesh === null)).toBe(true);
    }
  });

  it("reveals the footer light horizon across the footer scene only", () => {
    const reveals = sweepScene(counts, "footer").map((s) => s.transitionState.footerReveal);

    expect(reveals[0]).toBe(0);
    expect(reveals[reveals.length - 1]).toBe(1);
    expect(isNonDecreasing(reveals)).toBe(true);
    expect(enter(counts, "artPieces").transitionState.footerReveal).toBe(0);
  });

  it("reveals the grid statement once and does not re-trigger while the scene stays at or past the reveal", () => {
    let state = enter(counts, "gridStatement");
    expect(state.transitionState.gridStatementRevealed).toBe(false);

    state = sceneStateReducer(state, scroll("gridStatement", 1), counts);
    expect(state.transitionState.gridStatementRevealed).toBe(true);

    // Re-arriving at the same progress changes nothing at all.
    const settled = state;
    state = sceneStateReducer(state, scroll("gridStatement", 1), counts);
    expect(state).toBe(settled);

    // Still revealed further into the scene and in every later scene.
    state = sceneStateReducer(state, scroll("pixelA", 0.5), counts);
    expect(state.transitionState.gridStatementRevealed).toBe(true);
    state = sceneStateReducer(state, scroll("films", 0.5), counts);
    expect(state.transitionState.gridStatementRevealed).toBe(true);
  });

  it("clears the grid-statement one-shot only when scroll retreats before the reveal", () => {
    let state = run(counts, [scroll("gridStatement", 0), scroll("gridStatement", 1)]);
    expect(state.transitionState.gridStatementRevealed).toBe(true);

    // Documented reverse behavior: retreating to the start of the scene arms it again.
    state = sceneStateReducer(state, scroll("gridStatement", 0), counts);
    expect(state.transitionState.gridStatementRevealed).toBe(false);

    state = sceneStateReducer(state, scroll("gridStatement", 1), counts);
    expect(state.transitionState.gridStatementRevealed).toBe(true);

    // Retreating to an earlier scene arms it again too.
    state = sceneStateReducer(state, scroll("menu", 0.5), counts);
    expect(state.transitionState.gridStatementRevealed).toBe(false);

    state = sceneStateReducer(state, scroll("gridStatement", 1), counts);
    expect(state.transitionState.gridStatementRevealed).toBe(true);
  });

  it("resumes scroll stepping from the index a carousel button set (most recent input wins)", () => {
    const atBand = (band: number) => scroll("tracks", bandProgress(band, counts.tracks));

    let state = enter(counts, "tracks");
    state = sceneStateReducer(state, atBand(2), counts);
    expect(state.transitionState.trackIndex).toBe(2);

    state = sceneStateReducer(state, { type: "carouselNext" }, counts);
    expect(state.transitionState.trackIndex).toBe(3);

    // One band of reverse scroll steps back from 3 — not back to the raw scroll band 1.
    state = sceneStateReducer(state, atBand(1), counts);
    expect(state.transitionState.trackIndex).toBe(2);

    state = sceneStateReducer(state, { type: "carouselPrev" }, counts);
    expect(state.transitionState.trackIndex).toBe(1);

    // Forward scroll resumes from the button's index.
    state = sceneStateReducer(state, atBand(2), counts);
    expect(state.transitionState.trackIndex).toBe(2);
  });

  it("resumes scroll stepping from the index carouselTo set", () => {
    const atBand = (band: number) => scroll("tracks", bandProgress(band, counts.tracks));

    let state = enter(counts, "tracks");
    state = sceneStateReducer(state, { type: "carouselTo", index: 2 }, counts);
    expect(state.transitionState.trackIndex).toBe(2);

    state = sceneStateReducer(state, atBand(1), counts);
    expect(state.transitionState.trackIndex).toBe(3);

    state = sceneStateReducer(state, atBand(0), counts);
    expect(state.transitionState.trackIndex).toBe(2);
  });

  it("clamps the carousel at the first and last track", () => {
    const last = counts.tracks - 1;
    let state = enter(counts, "tracks");

    state = sceneStateReducer(state, { type: "carouselPrev" }, counts);
    expect(state.transitionState.trackIndex).toBe(0);

    state = sceneStateReducer(state, { type: "carouselTo", index: last }, counts);
    state = sceneStateReducer(state, { type: "carouselNext" }, counts);
    expect(state.transitionState.trackIndex).toBe(last);

    state = sceneStateReducer(state, { type: "carouselTo", index: counts.tracks + 99 }, counts);
    expect(state.transitionState.trackIndex).toBe(last);

    state = sceneStateReducer(state, { type: "carouselTo", index: -5 }, counts);
    expect(state.transitionState.trackIndex).toBe(0);

    // Scroll stepping cannot push a carousel offset out of range either.
    state = sceneStateReducer(state, { type: "carouselTo", index: last }, counts);
    for (const progress of ladder(12)) {
      state = sceneStateReducer(state, scroll("tracks", progress), counts);
      expect(state.transitionState.trackIndex).toBeGreaterThanOrEqual(0);
      expect(state.transitionState.trackIndex).toBeLessThanOrEqual(last);
    }
  });

  it("is pure and never mutates the state it was given", () => {
    const state = enter(counts, "films");
    const snapshot = JSON.parse(JSON.stringify(state)) as SceneState;
    const event = scroll("films", 0.5);

    const first = sceneStateReducer(state, event, counts);
    const second = sceneStateReducer(state, event, counts);

    expect(first).toEqual(second);
    expect(state).toEqual(snapshot);
  });

  it("returns the same state object when an event changes nothing", () => {
    const state = sceneStateReducer(enter(counts, "films"), scroll("films", 0.5), counts);

    expect(sceneStateReducer(state, scroll("films", 0.5), counts)).toBe(state);
  });
});

/* ------------------------------------------------------- cross-scene hand-offs */

/**
 * The three hand-offs no single scene owns (ticket 15, first acceptance box). Each one is a
 * property of the boundary BETWEEN two scenes, which is why none of the per-scene sweeps above
 * can see it: they all start by entering their scene cleanly.
 *
 * Assertions stay ordinal/structural. "Progressive rather than a jump" is expressed as *how many
 * distinct stages* a value passes through over a fine scrub — a step function shows none however
 * the budget is tuned, and a scroll-linked one shows many. No absolute progress threshold appears
 * anywhere, so retuning a scroll budget or a ramp span cannot make these pass or fail.
 *
 * What the descriptors MEAN for the field they drive is the shader module's contract, and it is
 * asserted there (`tests/unit/mesh-variants.test.ts`: "starts the art-pieces variant exactly where
 * tracks left off", "starts the footer fade exactly where art pieces settled", "crosses tracks ->
 * art pieces -> footer with no jump at any boundary"). This file owns the other half: that the
 * reducer actually emits that sequence of descriptors, without a gap, in both directions.
 */
describe.each(COUNT_FIXTURES)("cross-scene hand-offs driven by %s", (_label, counts) => {
  /* ---------------------------------- brief §7.7: pixel B dark beat -> tracks */

  it("keeps the last film on stage while its content fades, instead of cutting it", () => {
    const states = sweepScene(counts, "pixelB", HANDOFF_STEPS);

    // Step 1: "Film 03 remains visible" — the last film, whatever the lens's film count is.
    expect(states.every((s) => s.transitionState.filmIndex === counts.films - 1)).toBe(true);

    // Step 2: "the poster and left description begin fading" with continued scroll. A fade that
    // is genuinely scroll-linked passes through many stages; a step change passes through none.
    const fades = states.map((s) => s.transitionState.filmFade);
    expect(fades[0]).toBe(1);
    expect(fades[fades.length - 1]).toBe(0);
    expect(isNonIncreasing(fades)).toBe(true);
    expect(intermediateStages(fades).length).toBeGreaterThanOrEqual(MIN_INTERMEDIATE_STAGES);

    // And it begins while the film is still on screen, rather than all at the end.
    const firstFading = fades.findIndex((value) => value < 1);
    const firstCleared = fades.findIndex((value) => value === 0);
    expect(firstFading).toBeGreaterThan(-1);
    expect(firstFading).toBeLessThan(firstCleared);
  });

  it("holds the dark beat as the last thing before tracks, and nothing of tracks is in it", () => {
    const states = crossForward(counts, "pixelB", "tracks");
    const beats = states.map((s) => s.transitionState.darkBeat);

    const lastBeat = beats.lastIndexOf(true);
    const firstTracks = states.findIndex((s) => s.sceneId === "tracks");
    expect(lastBeat).toBeGreaterThan(-1);
    expect(firstTracks).toBeGreaterThan(-1);

    // Steps 6 and 7: the beat is held, and ONLY THEN does the tracks scene begin.
    expect(lastBeat).toBeLessThan(firstTracks);

    // "Empty": the film has already gone, and the carousel has not started.
    for (const state of states.filter((s) => s.transitionState.darkBeat)) {
      expect(state.sceneId).toBe("pixelB");
      expect(state.transitionState.filmFade).toBe(0);
      expect(state.transitionState.trackIndex).toBe(0);
    }
  });

  it("walks the fade and the dark beat back out when the scroll sequence reverses", () => {
    const steps = ladder(HANDOFF_STEPS);
    const forward = trace(
      counts,
      steps.map((progress) => scroll("pixelB", progress)),
      enter(counts, "pixelB"),
    );
    const backward = trace(
      counts,
      [...steps].reverse().map((progress) => scroll("pixelB", progress)),
      forward[forward.length - 1],
    );

    const shape = (state: SceneState) => ({
      darkBeat: state.transitionState.darkBeat,
      filmFade: state.transitionState.filmFade,
      pixelB: state.transitionState.pixelB,
    });

    expect(backward.map(shape)).toEqual([...forward].reverse().map(shape));
  });

  /* ------------------- one uncut mesh across the three opening scenes */

  it("never drops the mesh across the opening scene boundaries, in either direction", () => {
    for (const [from, to] of [
      ["loader", "thesis"],
      ["thesis", "menu"],
    ] as const) {
      const forward = crossForward(counts, from, to);
      const backward = crossBackward(counts, from, to);

      // There is no frame on either side of the boundary where the reducer has no mesh to hand
      // the canvas — the field carries straight through.
      expect(forward.every((s) => s.transitionState.mesh !== null)).toBe(true);
      expect(backward.every((s) => s.transitionState.mesh !== null)).toBe(true);

      // One variant the whole way, so there is no seam to cross at all.
      expect(runsOf(meshTrail(forward).map((mesh) => mesh.variant))).toEqual(["opening"]);
      expect(runsOf(meshTrail(backward).map((mesh) => mesh.variant))).toEqual(["opening"]);

      // The mode never leaves the mesh either: both scenes run on the same shared-canvas mode.
      expect(unique(forward.map((s) => (s.backgroundMode === "monoMesh" ? 1 : 0)))).toEqual([1]);
    }
  });

  it("releases the mesh exactly where the green grid takes the ground", () => {
    const forward = crossForward(counts, "menu", "gridStatement");

    // The descriptor and the mode change together on the same frame: a mesh descriptor exists
    // if and only if the mesh is the active mode. No gap, no overlap, one authority.
    expect(
      forward.every(
        (s) => (s.backgroundMode === "monoMesh") === (s.transitionState.mesh !== null),
      ),
    ).toBe(true);

    // The crossing really does happen inside this window, rather than the assertion above
    // passing vacuously on one side of it.
    expect(new Set(forward.map((s) => s.backgroundMode)).size).toBe(2);
  });

  it("carries one uncut field from the loader into the menu deck", () => {
    const states = trace(
      counts,
      [
        ...ladder(40).map((progress) => scroll("loader", progress)),
        ...ladder(40).map((progress) => scroll("thesis", progress)),
        ...ladder(40).map((progress) => scroll("menu", progress)),
      ],
      enter(counts, "loader"),
    );

    expect(states.every((s) => s.transitionState.mesh !== null)).toBe(true);
    expect(runsOf(meshTrail(states).map((mesh) => mesh.variant))).toEqual(["opening"]);
  });

  /* --------------------------------- art pieces -> footer, black into the light horizon */

  it("holds the black ground into the footer before the light horizon takes over", () => {
    const footer = sweepScene(counts, "footer");

    // Nothing to fade here any more — the ground arrived black and the mesh is long gone.
    expect(footer.every((s) => s.transitionState.mesh === null)).toBe(true);

    // Black first, then the light horizon: one change, in that order, and never back. Delaying
    // the mode change is what keeps scroll (not a wall clock) in charge of the reveal.
    expect(runsOf(footer.map((s) => s.backgroundMode))).toEqual(["black", "footerLight"]);
  });

  it("mirrors the opening mesh descriptor for descriptor on reverse scroll", () => {
    const forward = crossForward(counts, "thesis", "menu");
    const backward = crossBackward(counts, "thesis", "menu");

    const shape = (state: SceneState) => ({
      mesh: state.transitionState.mesh,
      backgroundMode: state.backgroundMode,
    });
    expect(backward.map(shape)).toEqual([...forward].reverse().map(shape));
  });
});

describe("discrete page inputs", () => {
  it("mirrors the reduced-motion flag", () => {
    const enabled = run(W04_COUNTS, [{ type: "reducedMotion", enabled: true }]);
    expect(enabled.reducedMotion).toBe(true);

    const disabled = sceneStateReducer(enabled, { type: "reducedMotion", enabled: false }, W04_COUNTS);
    expect(disabled.reducedMotion).toBe(false);
  });

  it("keeps the reduced-motion flag across scroll", () => {
    const state = run(W04_COUNTS, [
      { type: "reducedMotion", enabled: true },
      scroll("thesis", 0.5),
      scroll("menu", 0.5),
    ]);

    expect(state.reducedMotion).toBe(true);
  });

  it("marks the loader complete once the O portal finishes", () => {
    const before = createInitialSceneState(W04_COUNTS);
    expect(before.transitionState.loaderComplete).toBe(false);

    const after = sceneStateReducer(before, { type: "loaderComplete" }, W04_COUNTS);
    expect(after.transitionState.loaderComplete).toBe(true);

    // Sticky across later scroll, and a repeat is a no-op.
    expect(sceneStateReducer(after, { type: "loaderComplete" }, W04_COUNTS)).toBe(after);
    expect(
      run(W04_COUNTS, [scroll("thesis", 0.5), scroll("menu", 1)], after).transitionState
        .loaderComplete,
    ).toBe(true);
  });
});

describe("minimum content counts", () => {
  it("keeps every index in range for the smallest allowed lens", () => {
    const states = trace(MINIMUM_COUNTS, fullSweepEvents());

    for (const state of states) {
      const t = state.transitionState;
      expect(t.messageIndex).toBeGreaterThanOrEqual(0);
      expect(t.messageIndex).toBeLessThanOrEqual(MINIMUM_COUNTS.heroMessages - 1);
      expect(t.flippedCards).toBeGreaterThanOrEqual(0);
      expect(t.flippedCards).toBeLessThanOrEqual(MINIMUM_COUNTS.menuItems);
      expect(t.filmIndex).toBeGreaterThanOrEqual(0);
      expect(t.filmIndex).toBeLessThanOrEqual(MINIMUM_COUNTS.films - 1);
      expect(t.trackIndex).toBeGreaterThanOrEqual(0);
      expect(t.trackIndex).toBeLessThanOrEqual(MINIMUM_COUNTS.tracks - 1);
      expect(t.artIndex).toBeGreaterThanOrEqual(0);
      expect(t.artIndex).toBeLessThanOrEqual(MINIMUM_COUNTS.artPieces - 1);
    }
  });
});
