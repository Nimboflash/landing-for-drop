/**
 * Scene-state seam contract (BUILD-GUIDE seam 2).
 *
 * The page-level scene-state reducer is the single authority on scene / background-mode /
 * index state. Per-scene ScrollTriggers are dumb progress sources that feed it; scenes and
 * the shared background canvas render EXCLUSIVELY from its output. No scene computes its
 * own scene id, background mode, or active index.
 *
 * Everything here is deterministic and GPU-free: no DOM, no Three.js imports.
 */

/** The ten fixed stages of the page, in brief Section 6 order. */
export type SceneId =
  | "loader"
  | "thesis"
  | "menu"
  | "gridStatement"
  | "pixelA"
  | "films"
  | "pixelB"
  | "tracks"
  | "artPieces"
  | "footer";

/** Brief Section 6 master experience sequence. Order is an acceptance criterion. */
export const SCENE_ORDER: readonly SceneId[] = [
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

/** Shared background canvas state (brief Section 14). One canvas; modes switch by state. */
export type BackgroundMode =
  | "offWhiteGlow"
  | "greenGrid"
  | "pixelA"
  | "wavyDots"
  | "pixelB"
  | "monoMesh"
  | "black"
  | "footerLight";

/**
 * Fixed scene -> background mode mapping.
 *
 * The Monochrome Mesh opens the page (loader / thesis / menu) and Tracks and Art Pieces sit on a
 * flat black ground. The loader still paints its own off-white overlay canvas on top; this is the
 * ground its O portal opens onto.
 */
export const SCENE_BACKGROUND_MODE: Readonly<Record<SceneId, BackgroundMode>> = {
  loader: "monoMesh",
  thesis: "monoMesh",
  menu: "monoMesh",
  /*
   * The mesh, not the green grid.
   *
   * Brief 7.4 asks for a full-screen dark forest-green ground here, and this departs from it by
   * explicit art-direction decision — the same call, and the same reason, as the one that moved
   * the mesh to the opening scenes and put Tracks and Art Pieces on flat black. The grid keeps
   * its lattice and its one centred line; what it loses is the colour and the ground change, so
   * the field now runs uncut from the loader to the pixel transition and the lattice draws
   * itself over that field instead of replacing it.
   *
   * `greenGrid` stays registered and reachable as a mode — the registry is exhaustive over
   * BackgroundMode and its module is still correct — it simply has no scene pointing at it,
   * exactly as `offWhiteGlow` already does.
   */
  gridStatement: "monoMesh",
  pixelA: "pixelA",
  films: "wavyDots",
  pixelB: "pixelB",
  tracks: "black",
  artPieces: "black",
  footer: "footerLight",
} as const;

/**
 * Monochrome Mesh variants (ticket 10). `amount` is a 0..1 scalar for how far into the
 * variant we are.
 *
 * `opening` is the field as it runs behind the loader, thesis and menu deck: faster than the
 * preset and held under a contrast ceiling, because those scenes carry the page's largest type.
 * `normal` / `reading` / `fadeToBlack` are the original Tracks -> Art Pieces -> footer chain.
 */
export type MeshVariant = "opening" | "normal" | "reading" | "fadeToBlack";
/**
 * The mesh's own state.
 *
 * `lattice` is how far the grid statement's lattice has been DRAWN over the field, 0..1. It
 * lives here rather than on the grid scene because the lattice is background, and the shared
 * canvas takes its whole ground from one mode: there is no second layer to put it on, and the
 * one-canvas rule forbids inventing one. Drawing it into the mesh is what lets the field run
 * uncut from the loader through the grid statement while the lattice arrives over the top.
 */
export type MeshDescriptor = { variant: MeshVariant; amount: number; lattice: number };

/**
 * Declarative pixel-transition descriptor. Determinism at this seam means: the same
 * `{seed, progress}` is re-emitted on reverse scroll. Whether the GLSL restores cells
 * from it is manual visual QA.
 */
export type PixelDescriptor = { seed: number; progress: number };

/** Stable seed shared by both pixel transitions so cell coordinates stay consistent (ticket 11). */
export const PIXEL_SEED = 20_040_821;

/**
 * Declarative descriptors only — active indices, transition progress, one-shot flags.
 * Never DOM nodes, never GPU objects.
 */
export type TransitionState = {
  /** Thesis: index into `heroMessages`. */
  messageIndex: number;
  /** Menu deck: number of cards that have flipped face-up, 0..menuItems. */
  flippedCards: number;
  /** Grid statement one-shot: true once revealed, stays true while the scene is at/after reveal. */
  gridStatementRevealed: boolean;
  /** Films: index into `films`. */
  filmIndex: number;
  /** Tracks: index into `tracks`. */
  trackIndex: number;
  /** Art Pieces: index into `artPieces`. */
  artIndex: number;
  /** Pixel transition A (grid -> films); null when not in that transition. */
  pixelA: PixelDescriptor | null;
  /** Pixel transition B (films -> music); null when not in that transition. */
  pixelB: PixelDescriptor | null;
  /** Mono Mesh variant; null when the mesh is not the active background. */
  mesh: MeshDescriptor | null;
  /** Short empty dark beat held at the end of pixel B, before Tracks content enters. */
  darkBeat: boolean;
  /** Footer light-horizon reveal, 0..1. */
  footerReveal: number;
  /** Films fade during pixel B, 1 -> 0. Film content must never disappear abruptly. */
  filmFade: number;
  /** True once the loader's O portal has completed. */
  loaderComplete: boolean;
  /** Header logo contrast variant for the active scene. */
  headerVariant: "dark" | "light" | "hidden";
};

export type SceneState = {
  sceneId: SceneId;
  /** Progress within the active scene, 0..1. */
  sceneProgress: number;
  backgroundMode: BackgroundMode;
  transitionState: TransitionState;
  /** Mirrors the reduced-motion input; scenes render simplified choreography when true. */
  reducedMotion: boolean;
};

/**
 * Ordered raw inputs. Scroll progress updates come from per-scene ScrollTriggers;
 * discrete inputs come from carousel controls and the reduced-motion media query.
 */
export type InputEvent =
  | { type: "scrollProgress"; sceneId: SceneId; progress: number }
  | { type: "carouselNext" }
  | { type: "carouselPrev" }
  | { type: "carouselTo"; index: number }
  | { type: "reducedMotion"; enabled: boolean }
  | { type: "loaderComplete" };

/** Counts derived from the lens data. Every count-driven slot reads from here, never a literal. */
export type LensCounts = {
  heroMessages: number;
  menuItems: number;
  films: number;
  tracks: number;
  artPieces: number;
};
