/**
 * Pixel mosaic — the signature scroll-driven transition, in both directions of the page.
 *
 * One implementation serves both `pixelA` (grid statement -> films, brief Section 7.5) and
 * `pixelB` (films -> music, brief Section 7.7). They differ only in which pair of backgrounds
 * they dissolve between and how much spectral energy the frontier carries; the cell lattice,
 * the threshold field and the seed are shared, which is exactly what Section 7.7 asks for:
 * "Pixel coordinates should remain consistent with Transition A."
 *
 * What the brief forbids, and what this module therefore is not:
 *
 * - not a wipe, blur, crossfade or gradient dissolve — every cell switches **hard**, on its own
 *   threshold, and the outgoing background stays untouched inside a cell until that cell flips;
 * - not a straight rising line — the threshold field is bottom-weighted but broken up by a
 *   multi-octave column relief, so the front reads as an irregular stepped skyline with towers,
 *   notches and a dithered frontier;
 * - not a colour flood — transition B's orange/purple energy lives only in the band of cells
 *   near their own flip point, screen-blended so it can never blow out to a fill.
 *
 * **Reversibility is structural, not incidental.** A cell's threshold is a pure function of
 * `(cellX, cellY, seed, rows)` and "replaced" is `progress >= threshold`. There is no
 * accumulator, no latch, no frame history: the set of replaced cells at progress `p` is the
 * same set whether the scroll arrived at `p` going forward or backward. The GLSL evaluates the
 * identical formula per fragment, so the picture inherits the property from the maths.
 *
 * The threshold field lives in ONE place — the {@link FIELD} record and the pure helpers below —
 * and the GLSL is generated from it (`#define`s + a mirrored function body), so the shader
 * cannot drift from the unit-tested formula. The TypeScript arithmetic is rounded through
 * `Math.fround` at every step so it evaluates in the same single precision the GPU uses.
 *
 * Progress and seed are never computed here. They arrive as the reducer's `{ seed, progress }`
 * descriptor on `frame.transitionState.pixelA` / `.pixelB` (scene-state seam), and this module
 * only reads them.
 *
 * The two backgrounds a transition dissolves between are rendered inside this one program — the
 * incoming background is revealed *through* the cells, so it has to exist per-fragment rather
 * than as a layer underneath. The dot floor comes from `WavyDotsShader` itself, on the same clock,
 * so that side of both transitions is the real thing; the green grid and the mono mesh are local
 * stand-ins for the modules that own those modes (see {@link GREEN_GRID_LOOK_GLSL} and
 * {@link MONO_MESH_LOOK_GLSL}).
 */

import type { IUniform } from "three";

import type { BackgroundMode, PixelDescriptor, TransitionState } from "@/lib/scene";
import { PIXEL_SEED } from "@/lib/scene";
import {
  GLSL_BRAND_COLORS,
  GRID_CELL_PX,
  type BackgroundFrame,
  type BackgroundShaderModule,
} from "./shader-contract";
import {
  WAVY_DOTS_DEFAULT_DETAIL,
  WAVY_DOTS_DEFAULT_MIN_CELL_PX,
  WAVY_DOTS_FIELD_GLSL,
  glslFloat,
  wavyDotsDetailLevel,
  wavyDotsMinCellPx,
  wavyDotsTime,
} from "./WavyDotsShader";
import {
  MESH_FIELD_GLSL,
  MESH_FIELD_UNIFORMS_GLSL,
  MESH_VARIANT_TARGETS,
  MONO_MESH_PRESET,
  createMeshFieldUniforms,
  meshDetailUniforms,
  sharedMeshTime,
  writeMeshFieldUniforms,
} from "./MonochromeMeshShader";

/* -------------------------------------------------------------------------- */
/* The threshold field — single source of truth for TS and GLSL                 */
/* -------------------------------------------------------------------------- */

/**
 * Every constant of the threshold field, in one record. The GLSL below is generated from it as
 * `#define`s, so tuning happens in exactly one place and the shader can never disagree with the
 * unit-tested helpers.
 *
 * The relief terms are measured in **lattice rows**, which is what keeps the skyline looking
 * like the same staircase at any viewport: a three-row tower is three cells tall on a phone and
 * on a 5K display.
 */
const FIELD = {
  /** Hash input offsets — they keep the lattice origin off the hash's fixed point at (0,0,0). */
  HASH_XO: 0.13,
  HASH_YO: 0.71,
  HASH_KO: 0.37,
  /** Hash mixing constants (fract/multiply only: no `sin`, so it is stable across drivers). */
  HASH_XS: 0.1031,
  HASH_YS: 0.103,
  HASH_KS: 0.0973,
  HASH_MIX: 31.32,
  /** Hash channels, so one seed yields several decorrelated fields. */
  CH_BROAD: 1.0,
  CH_MEDIUM: 2.0,
  CH_SHARP: 3.0,
  CH_DITHER: 4.0,
  CH_CHROMA: 8.0,
  CH_TWINKLE: 9.0,
  /** Column relief, in rows: broad blocks, medium steps, per-column sharpness. */
  BROAD_ROWS: 4.0,
  BROAD_PERIOD: 4.0,
  MEDIUM_ROWS: 2.2,
  MEDIUM_PERIOD: 1.9,
  SHARP_ROWS: 1.8,
  /** Per-cell dither, in rows. Keeps the frontier ragged without turning the field into snow. */
  DITHER_ROWS: 1.4,
  /** Half-width, in rows, of the relief band folded into the normalisation. */
  NORM_SPAN_ROWS: 3.0,
  /** Threshold range. Strictly inside 0..1 so progress 0 replaces nothing and 1 replaces all. */
  START: 0.03,
  END: 0.97,
} as const;

const f32 = Math.fround;

function fract32(x: number): number {
  return f32(x - Math.floor(x));
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return value < 0 ? 0 : value > 1 ? 1 : value;
}

/**
 * Three-input value hash: uniform on [0,1), decorrelated between neighbouring cells, and built
 * from `fract` and multiplication only — no `sin`, whose large-argument precision differs
 * between GPUs and would make the field driver-dependent.
 *
 * Mirrored operation-for-operation by `dropMosaicHash` in the GLSL below.
 */
export function mosaicHash(x: number, y: number, k: number): number {
  let a = fract32(f32(f32(x + FIELD.HASH_XO) * FIELD.HASH_XS));
  let b = fract32(f32(f32(y + FIELD.HASH_YO) * FIELD.HASH_YS));
  let c = fract32(f32(f32(k + FIELD.HASH_KO) * FIELD.HASH_KS));
  const d = f32(
    f32(f32(a * f32(c + FIELD.HASH_MIX)) + f32(b * f32(b + FIELD.HASH_MIX))) +
      f32(c * f32(a + FIELD.HASH_MIX)),
  );
  a = f32(a + d);
  b = f32(b + d);
  c = f32(c + d);
  return fract32(f32(f32(a + b) * c));
}

/** Smoothstep-interpolated value noise along the column axis. */
function mosaicNoise1D(x: number, channel: number, seedKey: number): number {
  const i = Math.floor(x);
  const t = f32(x - i);
  const a = mosaicHash(i, channel, seedKey);
  const b = mosaicHash(i + 1, channel, seedKey);
  const u = f32(f32(t * t) * f32(3 - f32(2 * t)));
  return f32(a + f32(u * f32(b - a)));
}

/**
 * The seed, folded into a value the GPU can hold exactly.
 *
 * `PIXEL_SEED` is larger than 2^24, so it cannot survive a single-precision uniform intact —
 * and a seed that rounds differently on CPU and GPU would silently give the two a different
 * field. Folding it to a fraction with a power-of-two denominator keeps it exact in both.
 */
export function pixelSeedKey(seed: number): number {
  const whole = Number.isFinite(seed) ? Math.abs(Math.trunc(seed)) : 0;
  return (whole % 65536) / 65536;
}

/** The cell lattice for a given drawing buffer. Cells are `GRID_CELL_PX` — the green grid's own. */
export type MosaicGrid = {
  columns: number;
  rows: number;
  cellPx: number;
};

/**
 * Cell counts for a drawing buffer, in CSS pixels. Row 0 is the **bottom** row: the lattice is
 * indexed the way the shader samples it (y-up UV space), which is also the axis the field is
 * weighted along.
 */
export function mosaicGrid(resolution: readonly [number, number]): MosaicGrid {
  const width = Number.isFinite(resolution[0]) ? resolution[0] : 0;
  const height = Number.isFinite(resolution[1]) ? resolution[1] : 0;
  return {
    columns: Math.max(1, Math.ceil(width / GRID_CELL_PX)),
    rows: Math.max(1, Math.ceil(height / GRID_CELL_PX)),
    cellPx: GRID_CELL_PX,
  };
}

/**
 * How many rows a column's front is pushed up or down, before the per-cell dither. Three octaves:
 * broad blocks a few columns wide, a medium step, and per-column sharpness. The sum is what turns
 * a rising line into a skyline.
 */
function columnRelief(cellX: number, seedKey: number): number {
  const broad = f32(
    FIELD.BROAD_ROWS *
      f32(mosaicNoise1D(f32(cellX / FIELD.BROAD_PERIOD), FIELD.CH_BROAD, seedKey) - 0.5),
  );
  const medium = f32(
    FIELD.MEDIUM_ROWS *
      f32(mosaicNoise1D(f32(cellX / FIELD.MEDIUM_PERIOD), FIELD.CH_MEDIUM, seedKey) - 0.5),
  );
  const sharp = f32(FIELD.SHARP_ROWS * f32(mosaicHash(cellX, FIELD.CH_SHARP, seedKey) - 0.5));
  return f32(broad + f32(medium + sharp));
}

/**
 * The progress at which a cell flips from the outgoing background to the incoming one.
 *
 * Bottom-weighted: the row index dominates, so cells enter from the bottom of the frame. Broken
 * up: the column relief and per-cell dither displace each column's front by a few rows, so the
 * boundary is a stepped skyline rather than a straight line. Deterministic: same cell, same seed,
 * same frame height, same number — forever, in both directions of scroll.
 *
 * `cellY` counts from the bottom (row 0 is the bottom row). Only the **height** of `resolution`
 * takes part: the field spans the frame vertically, and a width change must never reshuffle it.
 *
 * @returns a threshold strictly inside `(0, 1)`.
 */
export function cellThreshold(
  cellX: number,
  cellY: number,
  seed: number,
  resolution: readonly [number, number],
): number {
  const { rows } = mosaicGrid(resolution);
  const seedKey = pixelSeedKey(seed);
  const dither = f32(
    FIELD.DITHER_ROWS * f32(mosaicHash(cellX, cellY, f32(seedKey + FIELD.CH_DITHER)) - 0.5),
  );
  const raw = f32(f32(cellY + 0.5) + f32(columnRelief(cellX, seedKey) + dither));
  const lo = f32(0.5 - FIELD.NORM_SPAN_ROWS);
  const hi = f32(f32(rows - 0.5) + FIELD.NORM_SPAN_ROWS);
  const norm = clamp01(f32(f32(raw - lo) / f32(hi - lo)));
  return f32(FIELD.START + f32(norm * f32(FIELD.END - FIELD.START)));
}

/**
 * Has this cell been replaced by the incoming background yet?
 *
 * A pure predicate of `(cell, seed, frame height, progress)` — no history. This is the whole of
 * the reversibility guarantee: reverse scroll re-evaluates the same comparison and gets the same
 * answer, cell for cell.
 */
export function isCellReplaced(
  cellX: number,
  cellY: number,
  seed: number,
  resolution: readonly [number, number],
  progress: number,
): boolean {
  return clamp01(progress) >= cellThreshold(cellX, cellY, seed, resolution);
}

/** Every replaced cell at this progress, column-major, as `[cellX, cellY]` pairs. */
export function replacedCells(
  seed: number,
  resolution: readonly [number, number],
  progress: number,
): readonly (readonly [number, number])[] {
  const { columns, rows } = mosaicGrid(resolution);
  const cells: (readonly [number, number])[] = [];
  for (let x = 0; x < columns; x += 1) {
    for (let y = 0; y < rows; y += 1) {
      if (isCellReplaced(x, y, seed, resolution, progress)) cells.push([x, y]);
    }
  }
  return cells;
}

/**
 * Replaced-cell count per column at this progress — the skyline, read left to right. An
 * irregular skyline is a spread of different heights; a wipe would be one repeated number.
 */
export function columnSkyline(
  seed: number,
  resolution: readonly [number, number],
  progress: number,
): readonly number[] {
  const { columns, rows } = mosaicGrid(resolution);
  const heights: number[] = [];
  for (let x = 0; x < columns; x += 1) {
    let filled = 0;
    for (let y = 0; y < rows; y += 1) {
      if (isCellReplaced(x, y, seed, resolution, progress)) filled += 1;
    }
    heights.push(filled);
  }
  return heights;
}

/* -------------------------------------------------------------------------- */
/* GLSL                                                                         */
/* -------------------------------------------------------------------------- */

function defines(prefix: string, values: Readonly<Record<string, number>>): string {
  return Object.entries(values)
    .map(([key, value]) => `#define ${prefix}${key} ${glslFloat(value)}`)
    .join("\n");
}

/**
 * The threshold field in GLSL — a line-for-line mirror of {@link cellThreshold} and its helpers,
 * over the same `#define`d constants. Both sides evaluate in single precision, so the pattern on
 * screen is the pattern the unit tests assert.
 */
const MOSAIC_FIELD_GLSL = /* glsl */ `
${defines("DROP_MOSAIC_", FIELD)}
#define DROP_MOSAIC_CELL_PX ${glslFloat(GRID_CELL_PX)}

float dropMosaicHash(float x, float y, float k) {
  float a = fract((x + DROP_MOSAIC_HASH_XO) * DROP_MOSAIC_HASH_XS);
  float b = fract((y + DROP_MOSAIC_HASH_YO) * DROP_MOSAIC_HASH_YS);
  float c = fract((k + DROP_MOSAIC_HASH_KO) * DROP_MOSAIC_HASH_KS);
  float d = (a * (c + DROP_MOSAIC_HASH_MIX) + b * (b + DROP_MOSAIC_HASH_MIX))
          + c * (a + DROP_MOSAIC_HASH_MIX);
  a += d;
  b += d;
  c += d;
  return fract((a + b) * c);
}

float dropMosaicNoise1D(float x, float channel, float seedKey) {
  float i = floor(x);
  float t = x - i;
  float a = dropMosaicHash(i, channel, seedKey);
  float b = dropMosaicHash(i + 1.0, channel, seedKey);
  float u = t * t * (3.0 - 2.0 * t);
  return a + u * (b - a);
}

float dropMosaicColumnRelief(float cellX, float seedKey) {
  float broad = DROP_MOSAIC_BROAD_ROWS
    * (dropMosaicNoise1D(cellX / DROP_MOSAIC_BROAD_PERIOD, DROP_MOSAIC_CH_BROAD, seedKey) - 0.5);
  float medium = DROP_MOSAIC_MEDIUM_ROWS
    * (dropMosaicNoise1D(cellX / DROP_MOSAIC_MEDIUM_PERIOD, DROP_MOSAIC_CH_MEDIUM, seedKey) - 0.5);
  float sharp = DROP_MOSAIC_SHARP_ROWS
    * (dropMosaicHash(cellX, DROP_MOSAIC_CH_SHARP, seedKey) - 0.5);
  return broad + (medium + sharp);
}

// Mirrors cellThreshold(): bottom-weighted rows, broken up by column relief and per-cell dither.
float dropMosaicThreshold(vec2 cell, float seedKey, float rows) {
  float dither = DROP_MOSAIC_DITHER_ROWS
    * (dropMosaicHash(cell.x, cell.y, seedKey + DROP_MOSAIC_CH_DITHER) - 0.5);
  float raw = (cell.y + 0.5) + (dropMosaicColumnRelief(cell.x, seedKey) + dither);
  float lo = 0.5 - DROP_MOSAIC_NORM_SPAN_ROWS;
  float hi = (rows - 0.5) + DROP_MOSAIC_NORM_SPAN_ROWS;
  float norm = clamp((raw - lo) / (hi - lo), 0.0, 1.0);
  return DROP_MOSAIC_START + norm * (DROP_MOSAIC_END - DROP_MOSAIC_START);
}
`;

/**
 * The dark forest-green square grid of the grid-statement scene, as a look the mosaic can
 * dissolve *out of*. It draws the same `GRID_CELL_PX` lattice the mosaic cells align to
 * (contract: "Pixel dimensions align with the existing background grid"), in the brief's
 * `--drop-grid-green` / `--drop-grid-line` tokens.
 *
 * **Stand-in.** The canonical `greenGrid` mode is ticket 04's. This is the mosaic's own copy of
 * that look, written to the same contract constants; it is exported so the two can be unified
 * (either module adopting this chunk) rather than drifting into a visible pop at the handoff.
 */
export const GREEN_GRID_LOOK_GLSL = /* glsl */ `
vec3 dropGreenGridLook(vec2 fragPx, vec2 res, float t, float detail) {
  vec2 cellUv = fract(fragPx / DROP_MOSAIC_CELL_PX);
  float lineWidth = 1.4 / DROP_MOSAIC_CELL_PX;
  float nearest = min(min(cellUv.x, 1.0 - cellUv.x), min(cellUv.y, 1.0 - cellUv.y));
  float line = 1.0 - smoothstep(0.0, lineWidth, nearest);

  vec3 col = mix(DROP_GRID_GREEN, DROP_GRID_LINE, line * 0.85);

  float aspect = res.x / max(res.y, 1.0);
  float r = length((fragPx / res - 0.5) * vec2(aspect, 1.0));
  col *= 1.0 - 0.42 * smoothstep(0.28, 1.15, r);
  return col;
}
`;

/**
 * The 4x4 monochrome mesh gradient, as a look the mosaic can dissolve *into*. Grays only, kept
 * dark enough to read the tracks scene's white type over (brief Section 7.8 background).
 *
 * **Stand-in**, on the same terms as {@link GREEN_GRID_LOOK_GLSL}: the canonical `monoMesh` mode
 * is ticket 10's. The dark beat the reducer holds at the end of transition B covers the handoff,
 * but the two should be unified rather than left to diverge.
 */
/**
 * The mosaic's `monoMesh` look is THE mesh, not a likeness of it.
 *
 * This used to be a 3x3 value-noise grey ramp — cheap, and wrong: the cells revealed one field and
 * the mesh module painted a different one on the very next frame, a measured ~1.7x brightness step
 * plus a change of structure in a single frame. Brief §7.7 asks that the new mesh be revealed
 * THROUGH the cells, and §19 forbids a major visual jump. Calling the shared field with the shared
 * clock is what makes the handover a no-op instead of a cut.
 *
 * `t` and `detail` are ignored deliberately: the mesh runs on its own clock (`uMeshTime`) and its
 * own detail uniforms, so that this program and the mesh program cannot drift apart.
 */
/**
 * The flat black ground, as a look the mosaic can dissolve *into*.
 *
 * Unlike the green-grid and mesh looks this is not a stand-in for anything: `BlackShader` paints
 * exactly this constant, so the mosaic's destination and the mode that follows it are the same
 * colour by construction and the handover cannot drift.
 */
export const BLACK_LOOK_GLSL = /* glsl */ `
  vec3 dropBlackLook(vec2 fragPx, vec2 res, float time, float detail) {
    return DROP_BLACK;
  }
`;

export const MONO_MESH_LOOK_GLSL = /* glsl */ `
vec3 dropMonoMeshLook(vec2 fragPx, vec2 res, float t, float detail) {
  vec2 p = clamp(fragPx / max(res, vec2(1.0)), 0.0, 1.0);
  float aspect = res.x / max(res.y, 1.0);
  return dropMeshFieldColor(p, aspect, uMeshTime);
}
`;

/** Wraps the shared dot floor in the look signature the mosaic calls its two sides with. */
const WAVY_DOTS_LOOK_ADAPTER_GLSL = /* glsl */ `
vec3 dropWavyDotsLook(vec2 fragPx, vec2 res, float t, float detail) {
  return dropWavyDotsField(fragPx / res, res, t, detail, 0.0, uMinCellPx);
}
`;

/* -------------------------------------------------------------------------- */
/* Transition specs                                                             */
/* -------------------------------------------------------------------------- */

/** The background modes this mosaic knows how to render as an outgoing or incoming look. */
type MosaicLookMode = Extract<BackgroundMode, "greenGrid" | "wavyDots" | "monoMesh" | "black">;

/**
 * The GLSL look function per mode. Typed against {@link MosaicLookMode} so a new pairing cannot
 * be declared without also giving it a function to call.
 */
const LOOK_FUNCTION: Readonly<Record<MosaicLookMode, string>> = {
  greenGrid: "dropGreenGridLook",
  wavyDots: "dropWavyDotsLook",
  monoMesh: "dropMonoMeshLook",
  black: "dropBlackLook",
};

/** Which of the reducer's two pixel descriptors this instance renders. */
type PixelTransitionKey = Extract<BackgroundMode, "pixelA" | "pixelB">;

export type PixelTransitionSpec = {
  /** The `BackgroundMode` this instance renders, and the descriptor slot it reads. */
  key: PixelTransitionKey;
  /** Outgoing background — visible in a cell until that cell flips. */
  from: MosaicLookMode;
  /** Incoming background — revealed *through* the cells, never crossfaded underneath them. */
  to: MosaicLookMode;
  /**
   * How much chroma the frontier carries: 0 keeps the energy achromatic, 1 is the brief's
   * restrained DROP orange/purple pass (Section 7.7, step 4).
   */
  spectralMix: number;
  /** Peak frontier energy, screen-blended so it can never flood. */
  energyGain: number;
  /** Whether this transition honours the reducer's `darkBeat` flag (brief Section 7.7, step 6). */
  honorsDarkBeat: boolean;
  /** Static colours for the no-WebGL path. */
  fromCss: string;
  toCss: string;
};

/** A mosaic module, plus the transition it describes — so callers and tests can read the pairing. */
export type PixelMosaicModule = BackgroundShaderModule & {
  readonly transition: PixelTransitionSpec;
  /** Reads this transition's `{ seed, progress }` out of reducer output. Never computes it. */
  readDescriptor(transitionState: TransitionState): PixelDescriptor | null;
};

/**
 * Frontier shaping: how fast the energy falls away ahead of / behind a cell's own flip point.
 * Both are steep on purpose — the energy is a band travelling with the front, and a slow decay
 * would leave the whole replaced area tinted, which is the colour flood the brief rules out.
 */
const ENERGY_PRE_FALLOFF = 30.0;
const ENERGY_POST_FALLOFF = 14.0;
const ENERGY_PRE_GAIN = 0.55;
/**
 * Dark beat: how far the frame dims, and over how much progress it gets there.
 *
 * 0.62 was tuned against the old stand-in mesh, whose grey ramp topped out near 0.46 — dimming
 * that by 0.62 landed genuinely dark. Now that this look paints the REAL field at its resting
 * brightness, the same multiplier leaves a clearly lit frame, and brief §7.7 step 6 asks for a
 * short empty DARK beat. Deepened so the beat reads dark against the true field.
 *
 * The lift back to full brightness as Tracks enters is intended, not a glitch: the beat is meant
 * to give way to the scene. What must not change across that boundary is the field's IDENTITY,
 * and it no longer does — both sides paint `dropMeshFieldColor` on one shared clock.
 */
const DARK_BEAT_DIM = 0.3;
const DARK_BEAT_RAMP = 0.05;
/** Sentinel for "the reducer has not raised the dark beat yet". Progress is never negative. */
const BEAT_UNSET = -1;

function fragmentShader(spec: PixelTransitionSpec): string {
  const fromLook = LOOK_FUNCTION[spec.from];
  const toLook = LOOK_FUNCTION[spec.to];
  // Only transition B resolves into the mesh. Declaring the field's uniforms in transition A's
  // program too would leave them unused, and a uniform the compiler strips is one the canvas then
  // writes to for nothing.
  const usesMesh = spec.from === "monoMesh" || spec.to === "monoMesh";

  return /* glsl */ `
varying vec2 vUv;

uniform vec2 uResolution;
uniform float uProgress;
uniform float uSeedKey;
uniform float uRows;
uniform float uTime;
uniform float uDetail;
uniform float uMinCellPx;
uniform float uReducedMotion;
uniform float uDarkBeat;
${usesMesh ? "uniform highp float uMeshTime;" : ""}
${usesMesh ? MESH_FIELD_UNIFORMS_GLSL : ""}

#define DROP_MOSAIC_SPECTRAL ${glslFloat(spec.spectralMix)}
#define DROP_MOSAIC_ENERGY ${glslFloat(spec.energyGain)}
#define DROP_MOSAIC_ENERGY_PRE_FALLOFF ${glslFloat(ENERGY_PRE_FALLOFF)}
#define DROP_MOSAIC_ENERGY_POST_FALLOFF ${glslFloat(ENERGY_POST_FALLOFF)}
#define DROP_MOSAIC_ENERGY_PRE_GAIN ${glslFloat(ENERGY_PRE_GAIN)}
#define DROP_MOSAIC_BEAT_DIM ${glslFloat(DARK_BEAT_DIM)}

${GLSL_BRAND_COLORS}
${MOSAIC_FIELD_GLSL}
${WAVY_DOTS_FIELD_GLSL}
${WAVY_DOTS_LOOK_ADAPTER_GLSL}
${GREEN_GRID_LOOK_GLSL}
${BLACK_LOOK_GLSL}
${usesMesh ? MESH_FIELD_GLSL : ""}
${usesMesh ? MONO_MESH_LOOK_GLSL : ""}

void main() {
  vec2 res = max(uResolution, vec2(1.0));
  vec2 fragPx = vUv * res;

  vec3 fromColor = ${fromLook}(fragPx, res, uTime, uDetail);
  vec3 toColor = ${toLook}(fragPx, res, uTime, uDetail);

  vec2 cell = floor(fragPx / DROP_MOSAIC_CELL_PX);
  float threshold = dropMosaicThreshold(cell, uSeedKey, uRows);

  // Hard per-cell replacement. The outgoing background is untouched until its cell flips —
  // no blur, no crossfade, no gradient (brief Section 7.5).
  float replaced = step(threshold, uProgress);
  vec3 col = mix(fromColor, toColor, replaced);

  // Frontier energy: a short pre-glow ahead of a cell's flip point, a longer ember behind it,
  // and nothing at all far from the front — an atmospheric band, never a fill. Enveloped so the
  // transition arrives and resolves clean, and screen-blended so it lifts rather than floods.
  float edge = uProgress - threshold;
  float pre = exp(edge * DROP_MOSAIC_ENERGY_PRE_FALLOFF) * DROP_MOSAIC_ENERGY_PRE_GAIN;
  float post = exp(-edge * DROP_MOSAIC_ENERGY_POST_FALLOFF);
  float envelope = smoothstep(0.0, 0.15, uProgress) * (1.0 - smoothstep(0.80, 1.0, uProgress));
  float heat = mix(pre, post, step(0.0, edge)) * envelope;

  float chroma = dropMosaicHash(cell.x, cell.y, uSeedKey + DROP_MOSAIC_CH_CHROMA);
  vec3 spectral = mix(DROP_ORANGE, DROP_PURPLE, chroma);
  vec3 energyColor = mix(DROP_WHITE, spectral, DROP_MOSAIC_SPECTRAL);
  // Separate channel from the hue, so bright cells are not all the same colour.
  float twinkle = 0.55 + 0.45 * dropMosaicHash(cell.x, cell.y, uSeedKey + DROP_MOSAIC_CH_TWINKLE);
  vec3 energy = energyColor * (heat * DROP_MOSAIC_ENERGY * twinkle);
  col = 1.0 - (1.0 - col) * (1.0 - clamp(energy, 0.0, 1.0));

  // Reduced motion: no per-cell stepping, no live field — a plain crossfade to a static frame.
  vec3 calm = mix(fromColor, toColor, smoothstep(0.0, 1.0, uProgress));
  col = mix(col, calm, uReducedMotion);

  // The short empty dark beat the reducer holds at the end of transition B.
  col *= mix(1.0, DROP_MOSAIC_BEAT_DIM, uDarkBeat);

  gl_FragColor = vec4(col, 1.0);
}
`;
}

/* -------------------------------------------------------------------------- */
/* Module factory                                                               */
/* -------------------------------------------------------------------------- */

function readDescriptorFor(
  key: PixelTransitionKey,
  transitionState: TransitionState,
): PixelDescriptor | null {
  return key === "pixelA" ? transitionState.pixelA : transitionState.pixelB;
}

/**
 * Dark-beat amount, ramped over progress instead of popping when the flag flips.
 *
 * The reducer owns *whether* the beat is running; the ramp start is latched from the progress at
 * which it said so, so the module never re-derives the reducer's threshold. Scrolling back clears
 * the flag and the latch together, and scrolling forward re-latches at the same progress — so the
 * beat is as reversible as everything else here.
 */
/**
 * How far the dark beat has dimmed the frame, 0..1.
 *
 * This used to ramp on `progress - onset`, where onset was the progress at which the reducer first
 * raised the beat. That ramp could never advance: the beat is raised exactly when this scene's
 * progress SATURATES at 1, and the scene then holds at 1 for the rest of its scroll budget. The
 * first observation captured onset = 1, every later frame took `min(1, 1)`, and the delta stayed
 * 0 — so the dim was dead code and the "dark beat" (brief §7.7 step 6) never darkened. Verified by
 * setting the dim to 0.0 and measuring no change in the frame.
 *
 * Ramping on the APPROACH to 1 instead gives the dim a real scroll signal: it eases in over the
 * last stretch of the mosaic's own progress, then holds while the reducer holds the beat. Still
 * a pure function of scroll state, so it scrubs backwards exactly as it played forwards.
 */
function darkBeatAmount(uniforms: Record<string, IUniform>, progress: number, flagged: boolean): number {
  const onsetUniform = uniforms.uBeatOnset;
  if (flagged) {
    onsetUniform.value = BEAT_UNSET;
    return 1;
  }
  onsetUniform.value = BEAT_UNSET;
  return clamp01((progress - (1 - DARK_BEAT_RAMP)) / DARK_BEAT_RAMP);
}

export function createPixelMosaicShader(spec: PixelTransitionSpec): PixelMosaicModule {
  const readDescriptor = (transitionState: TransitionState) =>
    readDescriptorFor(spec.key, transitionState);

  /** Only transition B resolves into the mesh; transition A never declares the field's uniforms. */
  const paintsMesh = spec.from === "monoMesh" || spec.to === "monoMesh";

  return {
    mode: spec.key,
    transition: spec,
    readDescriptor,
    fragmentShader: fragmentShader(spec),

    createUniforms(): Record<string, IUniform> {
      return {
        uResolution: { value: [1, 1] as [number, number] },
        uProgress: { value: 0 },
        uSeedKey: { value: pixelSeedKey(PIXEL_SEED) },
        uRows: { value: 1 },
        uTime: { value: 0 },
        uDetail: { value: WAVY_DOTS_DEFAULT_DETAIL },
        uMinCellPx: { value: WAVY_DOTS_DEFAULT_MIN_CELL_PX },
        uReducedMotion: { value: 0 },
        uDarkBeat: { value: 0 },
        // CPU-side bookkeeping for the dark-beat ramp; no matching shader uniform.
        uBeatOnset: { value: BEAT_UNSET },
        // Only transition B resolves into the mesh, and only it declares the field's uniforms.
        ...(paintsMesh ? { uMeshTime: { value: 0 }, ...createMeshFieldUniforms() } : {}),
      };
    },

    update(uniforms: Record<string, IUniform>, frame: BackgroundFrame): void {
      const descriptor = readDescriptor(frame.transitionState);

      // While the canvas is crossfading this mode out, the descriptor is already null — hold the
      // last state rather than snapping the field back to zero.
      const progress = descriptor
        ? clamp01(descriptor.progress)
        : clamp01(uniforms.uProgress.value as number);
      const seed = descriptor ? descriptor.seed : PIXEL_SEED;

      const resolution = uniforms.uResolution.value as [number, number];
      resolution[0] = Math.max(1, frame.resolution[0]);
      resolution[1] = Math.max(1, frame.resolution[1]);

      uniforms.uProgress.value = progress;
      uniforms.uSeedKey.value = pixelSeedKey(seed);
      uniforms.uRows.value = mosaicGrid(frame.resolution).rows;
      uniforms.uTime.value = wavyDotsTime(frame);
      uniforms.uDetail.value = wavyDotsDetailLevel(frame.quality);
      uniforms.uMinCellPx.value = wavyDotsMinCellPx(frame.quality);
      uniforms.uReducedMotion.value = frame.reducedMotion ? 1 : 0;
      uniforms.uDarkBeat.value = spec.honorsDarkBeat
        ? darkBeatAmount(uniforms, progress, frame.transitionState.darkBeat)
        : 0;

      if (paintsMesh) {
        // The state the mesh module will be in when it takes over on the next frame: its resting
        // `normal` variant, on the SHARED clock. Reading anything else here would reintroduce the
        // step this look exists to remove.
        const rate = frame.reducedMotion ? 0 : MESH_VARIANT_TARGETS.normal.speedScale * MONO_MESH_PRESET.speed;
        const meshTimeEntry = uniforms.uMeshTime;
        if (meshTimeEntry) meshTimeEntry.value = sharedMeshTime(frame.timeSeconds, rate);
        writeMeshFieldUniforms(uniforms, MESH_VARIANT_TARGETS.normal, meshDetailUniforms(frame.quality));
      }
    },

    fallbackCss(frame?: Pick<BackgroundFrame, "transitionState" | "sceneProgress">): string {
      const descriptor = frame ? readDescriptor(frame.transitionState) : null;
      const progress = clamp01(descriptor ? descriptor.progress : (frame?.sceneProgress ?? 0));
      const edge = `${(progress * 100).toFixed(2)}%`;
      return [
        `repeating-linear-gradient(to right, rgba(0, 0, 0, 0.22) 0 1px, rgba(0, 0, 0, 0) 1px ${GRID_CELL_PX}px)`,
        `repeating-linear-gradient(to top, rgba(0, 0, 0, 0.22) 0 1px, rgba(0, 0, 0, 0) 1px ${GRID_CELL_PX}px)`,
        `linear-gradient(to top, ${spec.toCss} 0 ${edge}, rgba(0, 0, 0, 0) ${edge} 100%)`,
        spec.fromCss,
      ].join(", ");
    },
  };
}

/**
 * Pixel transition A — grid statement to films (brief Section 7.5). No chroma: the grid gives way
 * to the dot floor with an achromatic frontier, keeping the colour pass unique to transition B.
 */
/*
 * `from` is the MESH, not the green grid.
 *
 * The grid statement no longer changes the ground -- it draws a lattice over the same mesh the
 * menu deck runs on -- so the mosaic has to dissolve out of that, or it would spend transition A
 * eating away a green field the reader never saw. The mesh look below carries the lattice at full
 * strength for exactly this reason: at the moment transition A opens, the lattice is always fully
 * drawn, so a constant is the honest value rather than a uniform nobody varies.
 */
export const pixelAShader: PixelMosaicModule = createPixelMosaicShader({
  key: "pixelA",
  from: "monoMesh",
  to: "wavyDots",
  spectralMix: 0,
  energyGain: 0.12,
  honorsDarkBeat: false,
  fromCss: "#050505",
  toCss: "#000000",
});

/**
 * Pixel transition B — films to music (brief Section 7.7). Same seed and lattice as A, so a cell
 * coordinate means the same thing in both; the frontier carries the restrained DROP orange/purple
 * energy on the way to the Monochrome Mesh, and the module honours the reducer's dark beat.
 */
export const pixelBShader: PixelMosaicModule = createPixelMosaicShader({
  key: "pixelB",
  from: "wavyDots",
  to: "black",
  spectralMix: 1,
  energyGain: 0.3,
  honorsDarkBeat: true,
  fromCss: "#000000",
  toCss: "#000000",
});
