/**
 * `greenGrid` — the dark forest-green grid statement background.
 *
 * Brief Section 7.4: "Full-screen dark forest-green background. Quiet square grid across the entire
 * viewport. Only one centered statement." and "Grid cells become the coordinate system for the next
 * pixel transition."
 *
 * That last sentence is why the cell size is a published constant rather than a private tuning
 * value: pixel transition A aligns its mosaic to this lattice (brief Section 7.5, "Pixel dimensions
 * align with the existing background grid") and transition B reuses the same coordinates
 * (Section 7.7). The lattice is defined once, in the shader contract, as `GRID_CELL_PX`; this module
 * re-exports it as {@link GREEN_GRID_CELL_PX} together with {@link greenGridLattice} so the
 * transitions consume the resolved lattice instead of re-deriving one that could drift out of sync.
 *
 * "Quiet" is a hard requirement, not a mood: the lines read as structure behind the statement, never
 * as a foreground pattern. Colors are the brief's own tokens — field `--drop-grid-green` (#102b19),
 * lines `--drop-grid-line` (#245236).
 */

import { Vector2, type IUniform } from "three";

import {
  GLSL_BRAND_COLORS,
  GRID_CELL_PX,
  type BackgroundFrame,
  type BackgroundShaderModule,
} from "./shader-contract";

/* ------------------------------------------------------------------ lattice */

/**
 * The resolved grid cell size, in CSS pixels. Identical to `GRID_CELL_PX` by contract — the pixel
 * transitions import this rather than re-deriving a cell size, so the mosaic can never fall out of
 * register with the grid it replaces.
 */
export const GREEN_GRID_CELL_PX: number = GRID_CELL_PX;

/** The lattice covering a viewport, in whole cells. Cells are square and anchored at the origin. */
export type GreenGridLattice = {
  /** Cell edge length, CSS pixels. */
  cellPx: number;
  /** Whole cells needed to cover the width (partial cells at the right edge are counted). */
  columns: number;
  /** Whole cells needed to cover the height (partial cells at the bottom edge are counted). */
  rows: number;
};

/**
 * Resolve the lattice for a viewport size in CSS pixels. Pixel transitions A and B call this to
 * size their mosaic; nothing else in the app should compute a cell count.
 */
export function greenGridLattice(
  resolution: readonly [number, number],
): GreenGridLattice {
  const [width, height] = resolution;
  const safeWidth = Number.isFinite(width) && width > 0 ? width : 0;
  const safeHeight = Number.isFinite(height) && height > 0 ? height : 0;
  return {
    cellPx: GREEN_GRID_CELL_PX,
    columns: Math.ceil(safeWidth / GREEN_GRID_CELL_PX),
    rows: Math.ceil(safeHeight / GREEN_GRID_CELL_PX),
  };
}

/* ------------------------------------------------------------------ tuning */

/** Line thickness in CSS pixels. One hairline; anything heavier stops being quiet. */
const LINE_WIDTH_PX = 1;
/** Strongest the lattice is ever mixed toward `--drop-grid-line`. */
const LINE_CEILING = 0.66;
/** Floor the lattice never drops below, so the scene is never a flat green void. */
const LINE_FLOOR = 0.38;
/** How far the lattice dims toward the corners of the frame. */
const VIGNETTE_DEPTH = 0.28;

/* ------------------------------------------------------------------- glsl */

const FRAGMENT_SHADER = /* glsl */ `
  varying vec2 vUv;

  uniform float uTime;
  uniform float uProgress;
  uniform vec2  uResolution;
  uniform float uCellPx;
  uniform float uLineWidthPx;
  uniform float uReducedMotion;

${GLSL_BRAND_COLORS}

  const float LINE_CEILING = ${LINE_CEILING.toFixed(3)};
  const float LINE_FLOOR = ${LINE_FLOOR.toFixed(3)};
  const float VIGNETTE_DEPTH = ${VIGNETTE_DEPTH.toFixed(3)};

  void main() {
    // vUv spans the viewport, so CSS pixels are recovered without touching gl_FragCoord --
    // the lattice therefore stays exactly uCellPx wide at every device pixel ratio.
    vec2 px = vUv * uResolution;

    float cell = max(uCellPx, 1.0);
    vec2 inCell = fract(px / cell) * cell;
    vec2 edgeDistance = min(inCell, cell - inCell);
    float distanceToLine = min(edgeDistance.x, edgeDistance.y);

    float halfWidth = max(uLineWidthPx, 0.5) * 0.5;
    float lattice = 1.0 - smoothstep(halfWidth, halfWidth + 1.0, distanceToLine);

    float aspect = max(uResolution.x, 1.0) / max(uResolution.y, 1.0);
    vec2 centred = (vUv - 0.5) * vec2(aspect, 1.0);
    float vignette = 1.0 - VIGNETTE_DEPTH * smoothstep(0.18, 0.92, length(centred));

    // The scene rises into place; the lattice settles with it and reverses with reverse scroll.
    float entry = LINE_FLOOR + (LINE_CEILING - LINE_FLOOR) * smoothstep(0.0, 0.24, clamp(uProgress, 0.0, 1.0));
    float breathe = uReducedMotion > 0.5 ? 1.0 : (0.95 + 0.05 * sin(uTime * 0.31));

    float intensity = clamp(lattice * entry * vignette * breathe, 0.0, 1.0);

    vec3 color = mix(DROP_GRID_GREEN, DROP_GRID_LINE, intensity);
    gl_FragColor = vec4(color, 1.0);
  }
`;

/* ------------------------------------------------------------------ module */

function createUniforms(): Record<string, IUniform> {
  return {
    uTime: { value: 0 },
    uProgress: { value: 0 },
    uResolution: { value: new Vector2(1, 1) },
    uCellPx: { value: GREEN_GRID_CELL_PX },
    uLineWidthPx: { value: LINE_WIDTH_PX },
    uReducedMotion: { value: 0 },
  };
}

function update(uniforms: Record<string, IUniform>, frame: BackgroundFrame): void {
  uniforms.uTime.value = frame.timeSeconds;
  uniforms.uProgress.value = frame.sceneProgress;
  uniforms.uReducedMotion.value = frame.reducedMotion ? 1 : 0;
  uniforms.uCellPx.value = GREEN_GRID_CELL_PX;
  uniforms.uLineWidthPx.value = LINE_WIDTH_PX;

  const resolution = uniforms.uResolution.value as Vector2;
  resolution.set(frame.resolution[0], frame.resolution[1]);
}

/**
 * No-WebGL / context-lost fallback: the same lattice drawn with repeating gradients at exactly
 * {@link GREEN_GRID_CELL_PX}, so the statement scene still reads as the dark-green grid rather than
 * a flat panel (brief Section 15).
 */
function fallbackCss(): string {
  const cell = `${GREEN_GRID_CELL_PX}px`;
  const stop = `${LINE_WIDTH_PX}px`;
  return [
    `repeating-linear-gradient(to right, #245236 0 ${stop}, transparent ${stop} ${cell})`,
    `repeating-linear-gradient(to bottom, #245236 0 ${stop}, transparent ${stop} ${cell})`,
    `#102b19`,
  ].join(", ");
}

/** The `greenGrid` background mode (brief Section 7.4). */
export const greenGridShader: BackgroundShaderModule = {
  mode: "greenGrid",
  fragmentShader: FRAGMENT_SHADER,
  createUniforms,
  update,
  fallbackCss,
};
