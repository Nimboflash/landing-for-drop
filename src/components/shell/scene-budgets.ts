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

/** Brief §6: tracks run `max(340vh, trackCount * 55vh)` with a sensible cap. */
export const TRACKS_VH_PER_TRACK = 55;
export const TRACKS_MIN_VH = 340;
/**
 * The "sensible cap" the brief asks for. Beyond this the carousel stops reading as pacing and
 * starts reading as a dead scroll zone; a longer playlist compresses its per-track scroll
 * instead of extending the page (11 seed tracks land at 605vh, well inside the cap).
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
  menu: 300, // brief: 260-320
  gridStatement: 180, // brief: 160-200
  pixelA: 160, // brief: 140-180
  films: 460, // brief: 420-500
  pixelB: 170, // brief: 150-190
  footer: 190, // brief: 160-220
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

/**
 * Every scene's budget, in brief §6 order. The shell maps over this to render the page, so the
 * scene sequence and the scroll rhythm come from one place.
 */
export function sceneBudgets(counts: LensCounts): readonly SceneBudget[] {
  return SCENE_ORDER.map((sceneId) => ({
    sceneId,
    vh: sceneBudgetVh(sceneId, counts),
    pin: scenePins(sceneId),
  }));
}

/** Total page length in viewport heights. Diagnostics and pacing review; never a test expectation. */
export function totalBudgetVh(counts: LensCounts): number {
  return sceneBudgets(counts).reduce((total, budget) => total + budget.vh, 0);
}
