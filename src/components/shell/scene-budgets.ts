/**
 * Per-scene scroll budgets (brief §6, "High-level scroll budget").
 *
 * These are CONFIG, not constants inlined at a call site: the shell reads them, the sections
 * size themselves from them, and tuning the pacing means editing this file only. The brief is
 * explicit that the numbers are starting points — "Do not treat these numbers as fixed if
 * pacing feels rushed or empty. The acceptance criterion is intentional rhythm, not a specific
 * page height." Nothing outside this module may depend on a particular value, and no test may
 * assert one (BUILD-GUIDE seam 2: ordinal assertions only).
 *
 * Count-driven budgets take {@link LensCounts} — the tracks scene grows with the playlist and
 * the Art Pieces scene grows with the number of field notes, exactly as the brief specifies.
 * Counts come from array lengths of the validated lens, never from a literal.
 *
 * Units are viewport heights. A scene's section is that many viewport heights tall; a pinned
 * scene holds the viewport for `budget - 100` of them (its sticky child is one viewport tall),
 * which is the window its ScrollTrigger reports 0..1 progress over.
 */

import { SCENE_ORDER, type LensCounts, type SceneId } from "@/lib/scene";

/** One scene's scroll geometry. */
export type SceneBudget = {
  sceneId: SceneId;
  /** Section length in viewport heights. */
  vh: number;
  /** Whether the scene holds the viewport while its budget scrolls past. */
  pin: boolean;
  /**
   * Whether this scene's section is pulled UP under the one before it by
   * {@link SCENE_UNDERLAP_VH}, so the scene is already in place behind its predecessor and is
   * revealed as that predecessor scrolls away over it. See {@link SCENE_UNDERLAP_VH}.
   */
  overlay: boolean;
};

/* ------------------------------------------------------------------ loader timing */

/**
 * The loader is TIME-based, not scroll-based (brief §7.1): "Total target: 3.2 seconds after
 * critical assets are ready" and "Cap the loader at 4 seconds; never trap the user waiting for
 * noncritical media." Ticket 05 owns the material scene; the shell only reserves the stage.
 */
export const LOADER_TARGET_MS = 3_200;
export const LOADER_MAX_MS = 4_000;

/* ----------------------------------------------------------------- count-driven */

/*
 * Brief §6 runs tracks at `max(340vh, trackCount * 55vh)`, and §7.8 adds "Scroll length
 * responds to item count". Both exist for one reason: that length was what advanced the
 * carousel. Scroll no longer advances it — it is swipe, controls, keyboard and the scene's own
 * auto-advance now — so the length is not pacing any more, it is just scroll with nothing on
 * the other end of it. Eleven tracks were buying 605vh, about six screens of a pinned scene
 * holding still.
 *
 * A DEPARTURE FROM THE BRIEF on both counts, recorded rather than slipped in, and downstream
 * of the §7.8 interaction change that was asked for. The scene keeps a single screen of hold
 * so it still arrives and leaves as a pinned scene rather than flicking past.
 */
export const TRACKS_VH_PER_TRACK = 0;
export const TRACKS_MIN_VH = 140;
/**
 * The cap. It no longer binds — with the per-track term at zero every playlist lands on the
 * floor — but it is kept so the function still refuses to run away if the per-track term is
 * ever restored.
 */
export const TRACKS_MAX_VH = 760;

/** Brief §6: Art Pieces run 75-95vh PER ITEM. */
export const ART_PIECE_VH_PER_ITEM = 85;

/** Scroll length of the tracks scene for a given playlist length. */
export function tracksBudgetVh(trackCount: number): number {
  const requested = Math.max(0, trackCount) * TRACKS_VH_PER_TRACK;
  return Math.min(TRACKS_MAX_VH, Math.max(TRACKS_MIN_VH, requested));
}

/** Scroll length of the Art Pieces scene for a given number of field notes. */
export function artPiecesBudgetVh(artPieceCount: number): number {
  return Math.max(1, artPieceCount) * ART_PIECE_VH_PER_ITEM;
}

/* -------------------------------------------------------------------- fixed */

/**
 * Scenes whose budget does not depend on content counts, with the brief's range in the comment
 * so a tuning pass can see how much room it has.
 *
 * The loader's length is nominal: it completes on a timer, and this only guarantees its
 * ScrollTrigger has a non-degenerate window (and gives the portal a little scroll travel if the
 * user scrolls during it).
 */
const FIXED_BUDGET_VH = {
  loader: 120, // time-based; see LOADER_TARGET_MS
  thesis: 320, // brief: 320
  // Both at the floor of their brief ranges, deliberately.
  //
  // Measured end to end at 771px of viewport: from the last card settling to the end of the grid
  // statement was 1542px -- two full screens -- of which one whole screen is the menu section
  // leaving, where the reducer is frozen at (menu, 1) and nothing responds to scroll at all. The
  // deck spends everything it has to say by 0.9 and the grid statement is one centred line, so
  // the length past those points was not buying either scene anything.
  menu: 260, // brief: 260-320
  gridStatement: 160, // brief: 160-200
  pixelA: 160, // brief: 140-180
  films: 460, // brief: 420-500
  pixelB: 170, // brief: 150-190
  /*
   * At the TOP of the brief's range, where it used to sit at the middle of it, and the page is
   * 70vh SHORTER for it: the footer is an overlay scene now (see `OVERLAY` and
   * `SCENE_UNDERLAP_VH`), so its section underlaps the art pieces by a viewport and adds 120vh to
   * the document rather than 190vh. What the extra budget buys is the scene's own scroll WINDOW,
   * which grows from 90vh to 120vh — the reveal sweeps a viewport of sheet across roughly 84vh of
   * that window, so it rises at about the speed the page scrolls instead of outrunning it.
   */
  footer: 220, // brief: 160-220
} as const satisfies Partial<Record<SceneId, number>>;

/**
 * Which scenes hold the viewport. Brief §9: "Pin only when the scene benefits from it."
 *
 * Art Pieces is the one flowing scene — it is a vertical editorial sequence (brief §7.9), and
 * pinning a reading surface is exactly the "trapped on mobile" feeling §15 warns about.
 */
const PINNED: Readonly<Record<SceneId, boolean>> = {
  loader: true,
  thesis: true,
  menu: true,
  gridStatement: true,
  pixelA: true,
  films: true,
  pixelB: true,
  tracks: true,
  artPieces: false,
  footer: true,
};

/* ----------------------------------------------------------------- underlap */

/**
 * How far an OVERLAY scene's section is pulled up under the section before it, in viewport
 * heights. Exactly one viewport, and that is structural rather than a taste value.
 *
 * Every consecutive scene pair is separated by one full viewport of scroll — a scene's trigger
 * runs `top top` -> `bottom bottom`, so scene k ends when its section's bottom reaches the
 * viewport's bottom and scene k+1 starts when its section's top reaches the viewport's top, one
 * screen later. That gap is the hand-over, and for every pair but the last one side holds content
 * across it. For art pieces -> footer nothing did: measured at 1440x900, scroll 18349 to 19110 —
 * 761px, more than four fifths of a screen — reported (artPieces, 1) the whole way while the
 * footer block simply slid up from below the fold with nothing responding to scroll.
 *
 * Pulling the footer's section up by exactly one viewport closes that gap: the footer's trigger
 * now starts on the same scroll position the art pieces' trigger ends on, so the screen of scroll
 * that was dead becomes the first screen of the footer's own window — which is what the reveal
 * needs to run at about scroll speed. It must stay EXACTLY one viewport: less leaves a shorter
 * dead gap, and more would make two scene triggers active at once, which the one-way data flow
 * (BUILD-GUIDE seam 2) has no precedence rule for.
 */
export const SCENE_UNDERLAP_VH = 100;

/**
 * Which scenes are revealed from behind the scene before them rather than arriving after it.
 *
 * An overlay scene's section underlaps its predecessor by {@link SCENE_UNDERLAP_VH} and paints
 * its own edge-to-edge surface, so the scene is already in place, behind, while the previous
 * scene scrolls away over it. The footer is the one scene built that way (brief §7.10 asks for a
 * closing scene, not a trailing page block); nothing else opts in.
 */
const OVERLAY: Readonly<Record<SceneId, boolean>> = {
  loader: false,
  thesis: false,
  menu: false,
  gridStatement: false,
  pixelA: false,
  films: false,
  pixelB: false,
  tracks: false,
  artPieces: false,
  footer: true,
};

/* ------------------------------------------------------------------- public API */

/** Scroll length of one scene, in viewport heights, for a lens with these counts. */
export function sceneBudgetVh(sceneId: SceneId, counts: LensCounts): number {
  if (sceneId === "tracks") return tracksBudgetVh(counts.tracks);
  if (sceneId === "artPieces") return artPiecesBudgetVh(counts.artPieces);
  return FIXED_BUDGET_VH[sceneId];
}

/** Whether a scene holds the viewport while its budget scrolls past. */
export function scenePins(sceneId: SceneId): boolean {
  return PINNED[sceneId];
}

/** Whether a scene is revealed from behind the scene before it. */
export function sceneOverlays(sceneId: SceneId): boolean {
  return OVERLAY[sceneId];
}

/**
 * Every scene's budget, in brief §6 order. The shell maps over this to render the page, so the
 * scene sequence and the scroll rhythm come from one place.
 */
export function sceneBudgets(counts: LensCounts): readonly SceneBudget[] {
  return SCENE_ORDER.map((sceneId) => ({
    sceneId,
    vh: sceneBudgetVh(sceneId, counts),
    pin: scenePins(sceneId),
    overlay: sceneOverlays(sceneId),
  }));
}

/**
 * Total page length in viewport heights. Diagnostics and pacing review; never a test expectation.
 *
 * An overlay scene's section overlaps the one before it, so it adds its budget MINUS the underlap
 * to the document — the page is what you can scroll through, not the sum of the sections.
 */
export function totalBudgetVh(counts: LensCounts): number {
  return sceneBudgets(counts).reduce(
    (total, budget) => total + budget.vh - (budget.overlay ? SCENE_UNDERLAP_VH : 0),
    0,
  );
}
