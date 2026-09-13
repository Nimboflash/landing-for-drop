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
 * `trackIndex` is the one index driven ENTIRELY by discrete inputs. Scroll does not move it:
 * `carouselNext` / `carouselPrev` / `carouselTo` are the only things that do, dispatched by
 * the controls, the keyboard, a drag, or the scene's own auto-advance while it is on screen.
 * Inside the scene the index simply holds whatever the last of those made it, and arriving at
 * the scene from either direction starts at the first track.
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
/**
 * How far through pixel B the film has fully cleared.
 *
 * Was 0.7, which emptied the frame while a third of the mosaic still had to run — the film was
 * gone and the destination had not arrived, which is the blank stretch that was reported. The
 * film now holds almost to the end of the transformation, so the blocks are always advancing
 * across something rather than across nothing.
 */
/**
 * Where the film card starts leaving, in the FILMS scene's own progress.
 *
 * The card used to hold at full strength until pixel B had already started, and only then
 * fade across it — so the transition ran on top of a card that was still there. The card now
 * leaves first and the transition follows it, which is the order the two were always meant to
 * read in.
 *
 * It must reach 0 AT films progress 1, not after: a full viewport of frozen scroll separates
 * every scene pair, and a ramp with further to travel would stall half-faded across it.
 */
const FILM_FADE_FROM = 0.82;
/**
 * Where the empty beat at the end of pixel B begins — and, just as importantly, where it ENDS.
 *
 * Every consecutive scene pair is separated by one full viewport of scroll in which the reducer
 * is frozen at (previous scene, progress 1). For every other pair one side holds content across
 * that hand-over. For pixel B neither did: the film had cleared long before, and the beat was
 * still raised at progress 1, so the frame stayed black for the whole hand-over viewport on top
 * of the beat itself. That is the "long fully black viewport before music" that was reported —
 * structural, not a tuning value.
 *
 * Releasing the beat AT progress 1 is the whole fix: at the frozen end the beat clears, the
 * tracks composition is no longer suppressed, and it rides the hand-over into frame the way every
 * other incoming scene already does. The beat still plays where it was designed to, inside the
 * scene's own scroll; it simply no longer outlives it.
 */
const DARK_BEAT_FROM = 0.92;
/** Fraction of the footer scene by which the Monochrome Mesh has faded to pure black. */
const MESH_FADE_TO_BLACK_COMPLETE_AT = 0.45;

/** Background modes bright enough to need a dark logo; everything else gets a light one. */
const LIGHT_BACKGROUND_MODES: readonly BackgroundMode[] = ["offWhiteGlow"];

/**
 * Is this ground bright enough that copy and the mark must be drawn dark?
 *
 * Exported because the SHELL needs the same verdict for the page's text colour, and deriving that
 * from the header variant instead was a real defect: the loader's variant is `"hidden"`, which is
 * a statement about the mark, not about the ground. While the loader sat on off-white paper the
 * two happened to agree; once the mesh moved under it they did not, and the opening lines of the
 * lens painted in `--drop-ink` on a dark field until the thesis became active and snapped them to
 * off-white. One authority — the mode — cannot disagree with itself that way.
 */
export function isLightGround(mode: BackgroundMode): boolean {
  return LIGHT_BACKGROUND_MODES.includes(mode);
}

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
/**
 * The carousel's index, which SCROLL NO LONGER MOVES.
 *
 * This is a departure from brief §7.8, whose Interaction list opens with "Vertical scroll
 * advances the pinned carousel" — recorded rather than slipped in, by explicit direction. The
 * rest of that list is unaffected: "Drag and swipe also change the active item" is still how
 * it moves, and it is now the only way alongside the controls, the keyboard and the timer the
 * scene runs while it is on screen.
 *
 * So inside the scene the index is whatever the last discrete input made it. Arriving at the
 * scene from either direction starts at the first track: the old behaviour synced the index to
 * the scroll band, which only meant anything while scroll was an input.
 */
function nextTrackIndex(
  state: SceneState,
  sceneId: SceneId,
  _progress: number,
  count: number,
): number {
  const ordinal = SCENE_ORDINAL.tracks;
  const activeOrdinal = SCENE_ORDINAL[sceneId];
  if (activeOrdinal < ordinal) return 0;
  if (activeOrdinal > ordinal) return lastIndex(count);
  if (state.sceneId !== "tracks") return 0;
  return clampInt(state.transitionState.trackIndex, 0, lastIndex(count));
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

/** Film content fades 1 -> 0 across the tail of its OWN scene, and is gone in every later one. */
function nextFilmFade(activeOrdinal: number, progress: number): number {
  const ordinal = SCENE_ORDINAL.films;
  if (activeOrdinal < ordinal) return 1;
  if (activeOrdinal > ordinal) return 0;
  return 1 - clamp01((clamp01(progress) - FILM_FADE_FROM) / (1 - FILM_FADE_FROM));
}

/**
 * Monochrome Mesh descriptor — alive across the three scenes that open the page.
 *
 * The mesh now backs the loader, the thesis and the menu deck, and it runs at `opening` through
 * all three: one uncut field from the portal to the last card, exactly the property the mesh
 * module is built around (its clock is integrated once and never reseeded, so holding one
 * variant across the run is the cheapest way to keep the field continuous).
 *
 * `opening` runs faster than the preset and under a contrast ceiling, because these three scenes
 * carry the page's largest type — see `MESH_OPENING_PEAK_CEILING`.
 *
 * Null everywhere else, because the mesh is no longer the active background there: Tracks and
 * Art Pieces sit on `black`, and the footer's light horizon rises out of that same black.
 *
 * `reading` and `fadeToBlack` are consequently unused by the reducer today. They stay in the
 * module — pure, unit-tested variant helpers — because they describe how the mesh behaves under
 * a reading surface and how it loses contrast into black, and both are wanted again the moment
 * the mesh backs a reading scene or has to hand over to a lit one.
 */
/**
 * Where the lattice starts drawing itself over the menu deck, in that scene's own progress.
 *
 * After the deck is FINISHED WITH, not merely after it stops moving. 0.78 is where the flip
 * window closes, and starting there put the lattice on screen at the exact moment the last card
 * landed — arriving over four fronts the reader had only just been given, and competing with
 * them for the frame. The deck then holds those fronts, unmoving and readable, from 0.78 to 0.9.
 *
 * 0.9 is the end of that hold: the point where the composition has been read and the section
 * starts leaving. The lattice draws itself in across the last tenth, as the cards go.
 *
 * It still has to REACH 1 at progress 1, not after it. Every consecutive scene pair is separated
 * by a full viewport of scroll in which the reducer is frozen at (previous scene, 1), so a ramp
 * with further to travel would stall half-drawn there for a whole screen.
 */
const LATTICE_DRAWS_FROM = 0.9;

/**
 * The mesh descriptor, and the lattice drawn over it.
 *
 * The field now covers four scenes rather than three: the grid statement joins the loader, the
 * thesis and the menu deck, so there is no ground change anywhere between the portal and the
 * pixel transition. What distinguishes the grid statement is the lattice, not the ground.
 *
 * The lattice must reach 1 exactly AT menu progress 1, not after it. Every consecutive scene
 * pair is separated by a full viewport of scroll in which the reducer is frozen at (previous
 * scene, 1) — a ramp that had further to travel would stall there in a half-drawn state for a
 * whole screen of scrolling. Same constraint the dark beat documents, and the same fix.
 */
function nextMesh(sceneId: SceneId, progress: number): MeshDescriptor | null {
  if (sceneId === "loader" || sceneId === "thesis") {
    return { variant: "opening", amount: progress, lattice: 0 };
  }
  if (sceneId === "menu") {
    const lattice = clamp01((clamp01(progress) - LATTICE_DRAWS_FROM) / (1 - LATTICE_DRAWS_FROM));
    return { variant: "opening", amount: progress, lattice };
  }
  if (sceneId === "gridStatement") {
    // Already fully drawn when the scene opens: it was drawn during the deck's hold, which is
    // the point. Holding it at 1 here is what makes the boundary invisible.
    return { variant: "opening", amount: progress, lattice: 1 };
  }
  return null;
}

/**
 * The active background mode.
 *
 * Every scene but the footer takes its fixed mode straight from `SCENE_BACKGROUND_MODE`. The
 * footer keeps a deliberate exception: it holds the PRECEDING scene's ground for the first
 * stretch of its budget, and only then lets `footerLight` take over.
 *
 * The reason is unchanged from when the mesh was still fading here — the canvas runs its own
 * wall-clock crossfade on a mode change, so handing it `footerLight` the instant the footer
 * becomes active would start a reveal that plays out on a timer rather than on scroll, finishing
 * while the user holds still and re-dissolving when they scrub back. Two authorities driving one
 * fade. Delaying the mode change keeps scroll the only authority.
 *
 * What changed is that the held ground is now `black` rather than a mesh mid-fade, so the delay
 * is doing less visible work than it used to: the light horizon simply rises out of black a
 * little later. The handover stays black-to-black and invisible either way.
 */
function nextBackgroundMode(sceneId: SceneId, progress: number): BackgroundMode {
  if (sceneId === "footer" && ramp(progress, MESH_FADE_TO_BLACK_COMPLETE_AT) < 1) {
    return SCENE_BACKGROUND_MODE.artPieces;
  }
  return SCENE_BACKGROUND_MODE[sceneId];
}

/**
 * Scenes that carry NO chrome at all.
 *
 * The loader has never had a header (brief §8: "Loader: no header"). The grid statement and the
 * pixel transition out of it were added by an explicit later direction, which supersedes §8's
 * "from hero onward" for this run: the grid statement is to contain its lattice and one centred
 * line and nothing else, and a mark parked over it is exactly the furniture that scene is a
 * refusal of. The header returns as the films are entered.
 *
 * `pixelB` is deliberately NOT here. It is the transition OUT of the films and back toward the
 * music, so hiding the mark there would take it away again immediately after handing it back —
 * the direction restores the header "during entry into the film scene", and it stays.
 */
const CHROMELESS_SCENES: readonly SceneId[] = ["loader", "gridStatement", "pixelA"];

function nextHeaderVariant(sceneId: SceneId, mode: BackgroundMode): TransitionState["headerVariant"] {
  /*
   * "hidden" is a statement about the MARK, not the ground — the page's text contrast is derived
   * separately from the background mode (see `isLightGround`), so hiding the header here cannot
   * drag the copy's colour with it. That separation was a real defect once and is worth keeping.
   */
  if (CHROMELESS_SCENES.includes(sceneId)) return "hidden";
  return isLightGround(mode) ? "dark" : "light";
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
  return a.variant === b.variant && a.amount === b.amount && a.lattice === b.lattice;
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
      darkBeat: sceneId === "pixelB" && progress >= DARK_BEAT_FROM && progress < 1,
      footerReveal: sceneId === "footer" ? progress : 0,
      filmFade: nextFilmFade(activeOrdinal, progress),
      loaderComplete: previous.loaderComplete,
      headerVariant: nextHeaderVariant(sceneId, backgroundMode),
    },
  };

  return sameSceneState(state, next) ? state : next;
}

/**
 * Move the carousel, WRAPPING at both ends.
 *
 * The field was already a ring — `ringOffset` in the scene puts track 0 next to the last one, so
 * the reader can see the playlist join up. The index clamped instead, which meant the two
 * disagreed: the case after the last one was visible on screen and unreachable by going forward.
 *
 * A clamp is also the wrong shape for a carousel that advances itself. It ran to the end and
 * then sat there, and every later step — a swipe, a key, the timer — did nothing at all. What
 * looked like the autoplay having died was the index having arrived.
 *
 * Stepping wraps; `carouselTo` still CLAMPS, because a jump to an index out of range is a
 * mistake to be contained rather than a lap to be taken.
 */
function stepTrackIndex(state: SceneState, delta: number, counts: LensCounts): SceneState {
  const total = Math.max(1, counts.tracks);
  const current = state.transitionState.trackIndex;
  // `%` keeps the sign of the dividend in JS, so a step back from 0 needs the extra `+ total`.
  const wrapped = (((current + delta) % total) + total) % total;
  if (wrapped === current) return state;
  return {
    ...state,
    transitionState: { ...state.transitionState, trackIndex: wrapped },
  };
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
 * Carousel events are accepted in any scene — the tracks carousel is the only consumer. Stepping
 * wraps around the playlist; `carouselTo` clamps to `0..counts.tracks - 1`.
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
      return stepTrackIndex(state, 1, counts);

    case "carouselPrev":
      return stepTrackIndex(state, -1, counts);

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
