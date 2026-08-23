/**
 * Scene-state reducer — the single authority on scene / background-mode / index state
 * (BUILD-GUIDE seam 2, ticket 03).
 *
 * Per-scene ScrollTriggers are dumb progress sources that feed `sceneStateReducer`; scenes
 * and the shared background canvas render EXCLUSIVELY from its output. No scene computes its
 * own scene id, background mode, or active index.
 *
 * The reducer is PURE: the same `(state, event, counts)` always produces the same output.
 * No `Date.now`, no `Math.random`, no DOM, no Three.js. It returns the previous state object
 * when nothing changed, so consumers can bail out of re-renders on identity.
 *
 * Every count-driven slot derives from `LensCounts` (array lengths of the validated lens),
 * never from a literal — the reducer works for any lens shape.
 *
 * ## Derivation rules
 *
 * A `scrollProgress` event fully settles the state. Scene-scoped values read:
 *
 * - `0` / initial while the active scene is BEFORE their own scene in `SCENE_ORDER`;
 * - derived from `progress` while their own scene is active;
 * - terminal (last index / all cards flipped) while the active scene is AFTER their scene.
 *
 * That keeps the state consistent even if a scroll jump skips a scene, and it makes
 * forward and reverse trajectories exact mirrors of one another.
 *
 * ## Carousel precedence — most recent input wins
 *
 * `trackIndex` is the one index with discrete inputs. Inside the tracks scene, scroll
 * stepping is RELATIVE: each `scrollProgress` event applies the delta between the scroll
 * band it lands in and the band the previous event landed in. So after a `carouselNext` /
 * `carouselPrev` / `carouselTo`, subsequent scroll stepping resumes from the index the
 * discrete input set instead of snapping back to the raw scroll-derived index.
 * Entering or leaving the tracks scene re-syncs `trackIndex` to the scroll position — the
 * carousel offset only lives as long as the scene does.
 *
 * ## Grid statement one-shot
 *
 * `gridStatementRevealed` latches true at the reveal point and STAYS true for the rest of
 * the scene and every later scene, so jitter around the reveal point can never re-fire the
 * mask animation. Reverse behavior (documented, tested): the latch clears only when scroll
 * retreats below the hysteresis floor inside `gridStatement`, or to any scene before it —
 * then a later forward pass reveals again. This is the single place where forward and
 * reverse trajectories deliberately differ; every index/mode value mirrors exactly.
 *
 * Scroll budgets and the thresholds below are tunable by design; nothing outside this file
 * depends on their values, and tests assert ordering/symmetry/counts rather than thresholds.
 */

import {
  PIXEL_SEED,
  SCENE_BACKGROUND_MODE,
  SCENE_ORDER,
  type BackgroundMode,
  type InputEvent,
  type LensCounts,
  type MeshDescriptor,
  type PixelDescriptor,
  type SceneId,
  type SceneState,
  type TransitionState,
} from "./types";

/* ------------------------------------------------------------------ tuning */
/** Fraction of the gridStatement scene at which the statement reveal fires. */
const GRID_STATEMENT_REVEAL_AT = 0.35;
/** Retreating below this inside gridStatement clears the one-shot (hysteresis band). */
const GRID_STATEMENT_RESET_BELOW = 0.2;
/** Fraction of pixel B by which film content has fully faded (1 -> 0, never abrupt). */
const FILM_FADE_COMPLETE_AT = 0.7;
/** Final stretch of pixel B held as an empty dark beat before Tracks content enters. */
const DARK_BEAT_FROM = 0.92;
/** Fraction of the footer scene by which the Monochrome Mesh has faded to pure black. */
const MESH_FADE_TO_BLACK_COMPLETE_AT = 0.45;

/** Background modes bright enough to need a dark logo; everything else gets a light one. */
const LIGHT_BACKGROUND_MODES: readonly BackgroundMode[] = ["offWhiteGlow"];

/* ------------------------------------------------------------------- utils */

const SCENE_ORDINAL: Readonly<Record<SceneId, number>> = SCENE_ORDER.reduce(
  (acc, sceneId, index) => {
    acc[sceneId] = index;
    return acc;
  },
  {} as Record<SceneId, number>,
);

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function clampInt(value: number, min: number, max: number): number {
  const rounded = Number.isFinite(value) ? Math.round(value) : min;
  if (max < min) return min;
  if (rounded < min) return min;
  if (rounded > max) return max;
  return rounded;
}

/** Last valid index for a count (never negative, so empty collections stay safe). */
function lastIndex(count: number): number {
  return Math.max(0, count - 1);
}

/** Split `progress` into `count` equal bands -> 0..count-1. Count-agnostic by construction. */
function bandIndex(progress: number, count: number): number {
  if (count <= 0) return 0;
  return clampInt(Math.floor(clamp01(progress) * count), 0, count - 1);
}

/** Split `progress` into `count + 1` equal bands -> 0..count (slot counters, not indices). */
function bandCount(progress: number, count: number): number {
  if (count <= 0) return 0;
  return clampInt(Math.floor(clamp01(progress) * (count + 1)), 0, count);
}

/** Ramp 0 -> 1 over the leading `span` of a scene, then hold at 1. */
function ramp(progress: number, span: number): number {
  if (span <= 0) return 1;
  return clamp01(clamp01(progress) / span);
}

/* -------------------------------------------------------- scene-scoped derivation */

/** 0 before its scene, derived during it, last index after it. */
function scopedIndex(
  activeOrdinal: number,
  sceneId: SceneId,
  count: number,
  progress: number,
): number {
  const ordinal = SCENE_ORDINAL[sceneId];
  if (activeOrdinal < ordinal) return 0;
  if (activeOrdinal > ordinal) return lastIndex(count);
  return bandIndex(progress, count);
}

/**
 * Menu deck slot counter: 0 before the scene, derived during it, all cards flipped after it.
 * The first of the `count + 1` bands is the stack's rise/fan phase; each later band flips
 * one more card, so the choreography adapts to any menu-item count.
 */
function scopedFlippedCards(activeOrdinal: number, count: number, progress: number): number {
  const ordinal = SCENE_ORDINAL.menu;
  if (activeOrdinal < ordinal) return 0;
  if (activeOrdinal > ordinal) return count;
  return bandCount(progress, count);
}

/**
 * Tracks carousel index. Relative stepping inside the scene preserves any discrete carousel
 * offset (most recent input wins); entering or leaving the scene re-syncs to scroll.
 */
function nextTrackIndex(
  state: SceneState,
  sceneId: SceneId,
  progress: number,
  count: number,
): number {
  const ordinal = SCENE_ORDINAL.tracks;
  const activeOrdinal = SCENE_ORDINAL[sceneId];
  if (activeOrdinal < ordinal) return 0;
  if (activeOrdinal > ordinal) return lastIndex(count);
  if (state.sceneId !== "tracks") return bandIndex(progress, count);

  const delta = bandIndex(progress, count) - bandIndex(state.sceneProgress, count);
  return clampInt(state.transitionState.trackIndex + delta, 0, lastIndex(count));
}

function nextGridStatementRevealed(
  previous: boolean,
  activeOrdinal: number,
  progress: number,
): boolean {
  const ordinal = SCENE_ORDINAL.gridStatement;
  if (activeOrdinal < ordinal) return false;
  if (activeOrdinal > ordinal) return true;
  if (progress >= GRID_STATEMENT_REVEAL_AT) return true;
  if (progress < GRID_STATEMENT_RESET_BELOW) return false;
  return previous;
}

/** Film content fades 1 -> 0 across pixel B and is gone in every later scene. */
function nextFilmFade(activeOrdinal: number, progress: number): number {
  const ordinal = SCENE_ORDINAL.pixelB;
  if (activeOrdinal < ordinal) return 1;
  if (activeOrdinal > ordinal) return 0;
  return 1 - ramp(progress, FILM_FADE_COMPLETE_AT);
}

/**
 * Monochrome Mesh descriptor. Alive through tracks (`normal`) and art pieces (`reading`,
 * slower and darker for reading comfort), then fading as the footer is entered
 * (`fadeToBlack`). Null once the mesh is no longer the active background — including after
 * the footer fade has completed and the page is pure black.
 */
function nextMesh(sceneId: SceneId, progress: number): MeshDescriptor | null {
  if (sceneId === "tracks") return { variant: "normal", amount: progress };
  if (sceneId === "artPieces") return { variant: "reading", amount: progress };
  if (sceneId === "footer") {
    const amount = ramp(progress, MESH_FADE_TO_BLACK_COMPLETE_AT);
    return amount >= 1 ? null : { variant: "fadeToBlack", amount };
  }
  return null;
}

/**
 * The active background mode.
 *
 * Every scene but the footer takes its fixed mode straight from `SCENE_BACKGROUND_MODE`. The
 * footer is the exception, and deliberately so: brief §7.10 asks the mesh to "gradually lose
 * contrast and fade to pure black AFTER the last Art Piece", with scroll controlling the reveal.
 *
 * Handing the canvas `footerLight` the instant the footer becomes active makes that impossible.
 * The canvas would start its own wall-clock mode crossfade and unmount the outgoing mesh once the
 * fade completed, so the contrast loss would play out over ~0.42s of real time no matter what the
 * scroll did — finishing even while the user held still, and re-dissolving on a timer when they
 * scrubbed back. Two authorities were driving one fade.
 *
 * So the mesh REMAINS the active mode until its own scroll-linked `fadeToBlack` ramp reaches 1,
 * and only then does `footerLight` take over. By that point the mesh is already black, so the
 * handover the canvas performs is black-to-black and invisible. One authority: scroll.
 */
function nextBackgroundMode(sceneId: SceneId, progress: number): BackgroundMode {
  if (sceneId === "footer" && ramp(progress, MESH_FADE_TO_BLACK_COMPLETE_AT) < 1) {
    return SCENE_BACKGROUND_MODE.artPieces;
  }
  return SCENE_BACKGROUND_MODE[sceneId];
}

function nextHeaderVariant(sceneId: SceneId, mode: BackgroundMode): TransitionState["headerVariant"] {
  if (sceneId === "loader") return "hidden";
  return LIGHT_BACKGROUND_MODES.includes(mode) ? "dark" : "light";
}

function pixelDescriptor(active: boolean, progress: number): PixelDescriptor | null {
  // Both transitions share PIXEL_SEED so cell coordinates stay consistent between them.
  return active ? { seed: PIXEL_SEED, progress } : null;
}

/* -------------------------------------------------------------- equality */

function samePixel(a: PixelDescriptor | null, b: PixelDescriptor | null): boolean {
  if (a === b) return true;
  if (a === null || b === null) return false;
  return a.seed === b.seed && a.progress === b.progress;
}

function sameMesh(a: MeshDescriptor | null, b: MeshDescriptor | null): boolean {
  if (a === b) return true;
  if (a === null || b === null) return false;
  return a.variant === b.variant && a.amount === b.amount;
}

function sameSceneState(a: SceneState, b: SceneState): boolean {
  if (
    a.sceneId !== b.sceneId ||
    a.sceneProgress !== b.sceneProgress ||
    a.backgroundMode !== b.backgroundMode ||
    a.reducedMotion !== b.reducedMotion
  ) {
    return false;
  }
  const x = a.transitionState;
  const y = b.transitionState;
  return (
    x.messageIndex === y.messageIndex &&
    x.flippedCards === y.flippedCards &&
    x.gridStatementRevealed === y.gridStatementRevealed &&
    x.filmIndex === y.filmIndex &&
    x.trackIndex === y.trackIndex &&
    x.artIndex === y.artIndex &&
    x.darkBeat === y.darkBeat &&
    x.footerReveal === y.footerReveal &&
    x.filmFade === y.filmFade &&
    x.loaderComplete === y.loaderComplete &&
    x.headerVariant === y.headerVariant &&
    samePixel(x.pixelA, y.pixelA) &&
    samePixel(x.pixelB, y.pixelB) &&
    sameMesh(x.mesh, y.mesh)
  );
}

/* ---------------------------------------------------------------- public API */

/** Anything shaped like a validated lens; only the collection lengths matter here. */
export type LensCountSource = {
  heroMessages: readonly unknown[];
  menuItems: readonly unknown[];
  films: readonly unknown[];
  tracks: readonly unknown[];
  artPieces: readonly unknown[];
};

/** Counts for every count-driven slot, derived from array lengths — never literals. */
export function lensCounts(lens: LensCountSource): LensCounts {
  return {
    heroMessages: lens.heroMessages.length,
    menuItems: lens.menuItems.length,
    films: lens.films.length,
    tracks: lens.tracks.length,
    artPieces: lens.artPieces.length,
  };
}

const BLANK_STATE: SceneState = {
  sceneId: "loader",
  sceneProgress: 0,
  backgroundMode: SCENE_BACKGROUND_MODE.loader,
  reducedMotion: false,
  transitionState: {
    messageIndex: 0,
    flippedCards: 0,
    gridStatementRevealed: false,
    filmIndex: 0,
    trackIndex: 0,
    artIndex: 0,
    pixelA: null,
    pixelB: null,
    mesh: null,
    darkBeat: false,
    footerReveal: 0,
    filmFade: 1,
    loaderComplete: false,
    headerVariant: "hidden",
  },
};

/** The page at rest: loader scene, nothing revealed, header hidden. */
export function createInitialSceneState(counts: LensCounts): SceneState {
  return applyScrollProgress(BLANK_STATE, "loader", 0, counts);
}

function applyScrollProgress(
  state: SceneState,
  sceneId: SceneId,
  rawProgress: number,
  counts: LensCounts,
): SceneState {
  const progress = clamp01(rawProgress);
  const activeOrdinal = SCENE_ORDINAL[sceneId];
  const backgroundMode = nextBackgroundMode(sceneId, progress);
  const previous = state.transitionState;

  const next: SceneState = {
    sceneId,
    sceneProgress: progress,
    backgroundMode,
    reducedMotion: state.reducedMotion,
    transitionState: {
      messageIndex: scopedIndex(activeOrdinal, "thesis", counts.heroMessages, progress),
      flippedCards: scopedFlippedCards(activeOrdinal, counts.menuItems, progress),
      gridStatementRevealed: nextGridStatementRevealed(
        previous.gridStatementRevealed,
        activeOrdinal,
        progress,
      ),
      filmIndex: scopedIndex(activeOrdinal, "films", counts.films, progress),
      trackIndex: nextTrackIndex(state, sceneId, progress, counts.tracks),
      artIndex: scopedIndex(activeOrdinal, "artPieces", counts.artPieces, progress),
      pixelA: pixelDescriptor(sceneId === "pixelA", progress),
      pixelB: pixelDescriptor(sceneId === "pixelB", progress),
      mesh: nextMesh(sceneId, progress),
      darkBeat: sceneId === "pixelB" && progress >= DARK_BEAT_FROM,
      footerReveal: sceneId === "footer" ? progress : 0,
      filmFade: nextFilmFade(activeOrdinal, progress),
      loaderComplete: previous.loaderComplete,
      headerVariant: nextHeaderVariant(sceneId, backgroundMode),
    },
  };

  return sameSceneState(state, next) ? state : next;
}

function withTrackIndex(state: SceneState, trackIndex: number, counts: LensCounts): SceneState {
  const clamped = clampInt(trackIndex, 0, lastIndex(counts.tracks));
  if (clamped === state.transitionState.trackIndex) return state;
  return {
    ...state,
    transitionState: { ...state.transitionState, trackIndex: clamped },
  };
}

/**
 * `(state, event, counts) -> state`. Pure, deterministic, GPU-free.
 *
 * Carousel events are accepted in any scene — the tracks carousel is the only consumer, and
 * clamping to `0..counts.tracks - 1` keeps the index in range at both ends.
 */
export function sceneStateReducer(
  state: SceneState,
  event: InputEvent,
  counts: LensCounts,
): SceneState {
  switch (event.type) {
    case "scrollProgress":
      return applyScrollProgress(state, event.sceneId, event.progress, counts);

    case "carouselNext":
      return withTrackIndex(state, state.transitionState.trackIndex + 1, counts);

    case "carouselPrev":
      return withTrackIndex(state, state.transitionState.trackIndex - 1, counts);

    case "carouselTo":
      return withTrackIndex(state, event.index, counts);

    case "reducedMotion":
      if (state.reducedMotion === event.enabled) return state;
      return { ...state, reducedMotion: event.enabled };

    case "loaderComplete":
      if (state.transitionState.loaderComplete) return state;
      return {
        ...state,
        transitionState: { ...state.transitionState, loaderComplete: true },
      };

    default: {
      // Exhaustiveness guard: a new InputEvent variant must be handled above.
      const exhaustive: never = event;
      void exhaustive;
      return state;
    }
  }
}
