/**
 * Monochrome Mesh — the `monoMesh` background mode (brief Sections 7.8 and 7.9, ticket 10).
 *
 * The MetalForge-inspired preset rebuilt as a web shader: a 4x4 mesh gradient over the brief's
 * exact control colors, smoothly interpolated, drifting slowly, with the frame edges pinned
 * (`fixEdges`) and a fine grain on top. No MetalForge embed, no recorded video — everything here
 * is GLSL over a fullscreen quad.
 *
 * ## One uncut field across three scenes
 *
 * Brief Section 7.9: "The Monochrome Mesh continues from Tracks without restarting or cutting."
 * The mesh is the background for Tracks and Art Pieces, then loses contrast and fades to black as
 * the footer is entered. Those three looks are the {@link MeshVariant} values the reducer emits.
 *
 * They are NOT three shaders and NOT three clocks. There is exactly one continuously integrated
 * clock ({@link advanceMeshClock}) and one set of interpolated uniforms ({@link meshVariantUniforms}).
 * A variant change alters the RATE the clock advances and the brightness/contrast it is drawn
 * with — never the clock's value, never a seed, never any module state. That is what makes the
 * hand-off uncut, and it is why the settings of each variant are pinned to the settled state of
 * the variant before it:
 *
 * ```
 *   normal      : constant, full liveliness            (Tracks)
 *   reading     : normal      -> READING at amount 1   (Art Pieces: slower, darker)
 *   fadeToBlack : READING     -> BLACK   at amount 1   (Footer entry: contrast loss to black)
 * ```
 *
 * Every boundary is therefore an exact equality, not a crossfade: `reading@0 === normal`, and
 * `fadeToBlack@0 === reading@1`. Reverse scroll re-emits the same descriptors and so restores the
 * same uniforms — the variant helpers are pure functions of the descriptor.
 *
 * ## Testing
 *
 * Only the pure, GPU-free helpers below are unit-tested (tests/unit/mesh-variants.test.ts).
 * Uniform values are never asserted by reaching into a material, and canvas pixels are never
 * asserted; each variant's look is manual visual QA.
 */

import type { IUniform } from "three";

import type { QualityTierSettings } from "@/lib/performance/quality-tier";
import type {
  BackgroundMode,
  MeshDescriptor,
  MeshVariant,
  TransitionState,
} from "@/lib/scene";

import type { BackgroundFrame, BackgroundShaderModule } from "./shader-contract";

/* ------------------------------------------------------------------ preset */

/**
 * The brief's Section 7.8 preset, transcribed verbatim. Kept as data so the GLSL below reads
 * its knobs from one traceable place instead of scattering magic numbers.
 *
 * `filter: "none"` switches the preset's post filter off, so the `f*` values describe a chain
 * that is not applied — with one deliberate exception: `fGrain` is honoured as the fine grain
 * the mesh needs to keep a dark gradient from banding on 8-bit displays.
 */
export const MONO_MESH_PRESET = Object.freeze({
  effect: "mesh",
  grid: 4,
  style: "mono",
  smooth: 1,
  background: "#000000",
  animate: 1,
  speed: 1,
  drift: 0.35,
  hue: 0,
  fixEdges: 1,
  filter: "none",
  fBlur: 8,
  fFade: 0.45,
  fAmount: 0.5,
  fSoft: 0.5,
  fBrightness: 0,
  fContrast: 1,
  fSaturation: 1,
  fGrain: 16,
  fAngle: 0,
  fScale: 5,
  fInset: 0.08,
  fRound: 0.45,
  fBevel: 0.3,
} as const);

/**
 * The brief's Section 7.8 mesh control colors, exactly as written there. Row 0 is the BOTTOM row
 * of the field (GLSL `uv.y = 0` is the bottom edge); the CSS fallback flips the row order so both
 * paths place the same color in the same corner.
 */
export const MESH_CONTROL_COLORS: readonly (readonly string[])[] = Object.freeze([
  Object.freeze(["#141415", "#ABAEB5", "#6C6E75", "#2E3034"]),
  Object.freeze(["#696B74", "#2B2C32", "#C8C9CD", "#828694"]),
  Object.freeze(["#C5C7CC", "#83868E", "#44464E", "#E4E4E6"]),
  Object.freeze(["#42444C", "#E1E2E4", "#9C9FAA", "#5E6069"]),
]);

/** Lattice size, derived from the color grid itself — never a literal. */
export const MESH_GRID_ROWS = MESH_CONTROL_COLORS.length;
export const MESH_GRID_COLUMNS = MESH_CONTROL_COLORS[0].length;
const MESH_CONTROL_COUNT = MESH_GRID_ROWS * MESH_GRID_COLUMNS;

export type Rgb = readonly [number, number, number];

const HEX_COLOR_PATTERN = /^#([0-9a-fA-F]{6})$/;

/** Parse `#rrggbb` into linear-ish 0..1 channels. Throws loudly on anything else. */
export function parseHexColor(hex: string): Rgb {
  const match = HEX_COLOR_PATTERN.exec(hex.trim());
  if (!match) {
    throw new Error(`Mesh control color must be a 6-digit hex string, received: ${hex}`);
  }
  const value = Number.parseInt(match[1], 16);
  return [
    ((value >> 16) & 0xff) / 0xff,
    ((value >> 8) & 0xff) / 0xff,
    (value & 0xff) / 0xff,
  ];
}

/** The control grid parsed to 0..1 channels, same row/column order as {@link MESH_CONTROL_COLORS}. */
export const MESH_CONTROL_COLORS_RGB: readonly (readonly Rgb[])[] = Object.freeze(
  MESH_CONTROL_COLORS.map((row) => Object.freeze(row.map(parseHexColor))),
);

/**
 * The control grid flattened for the `uniform vec3 uMeshColors[N]` array, row-major.
 * A fresh array per call so nothing is shared between canvas mounts.
 */
export function meshControlColorArray(): Float32Array {
  const flat = new Float32Array(MESH_CONTROL_COUNT * 3);
  let cursor = 0;
  for (const row of MESH_CONTROL_COLORS_RGB) {
    for (const [r, g, b] of row) {
      flat[cursor] = r;
      flat[cursor + 1] = g;
      flat[cursor + 2] = b;
      cursor += 3;
    }
  }
  return flat;
}

/**
 * The field's own mean color. Contrast loss collapses the mesh toward this value before the
 * brightness fade finishes it off, so the footer entry reads as the field flattening rather than
 * as a plain dip to black. Derived from the control colors — never an invented gray.
 */
export const MESH_PIVOT_RGB: Rgb = (() => {
  let r = 0;
  let g = 0;
  let b = 0;
  for (const row of MESH_CONTROL_COLORS_RGB) {
    for (const channel of row) {
      r += channel[0];
      g += channel[1];
      b += channel[2];
    }
  }
  return [r / MESH_CONTROL_COUNT, g / MESH_CONTROL_COUNT, b / MESH_CONTROL_COUNT];
})();

/* ---------------------------------------------------------------- variants */

/**
 * The three uniform knobs a variant moves. `speedScale` multiplies the RATE of the mesh clock
 * (never its value), `brightness` and `contrast` are applied after the field is sampled.
 */
export type MeshVariantSettings = {
  /** Multiplier on the mesh clock's rate. 1 = the preset's own speed. */
  speedScale: number;
  /** Output multiplier. 0 = pure black. */
  brightness: number;
  /** Collapse toward {@link MESH_PIVOT_RGB}. 1 = the full field, 0 = perfectly flat. */
  contrast: number;
};

/**
 * Ceiling on the brightest channel the `opening` field may reach, so off-white copy stays legible
 * over it. The mesh's counterpart to `OFF_WHITE_GLOW_CEILING`.
 *
 * Derived, not eyeballed. Brief §16 wants AA body text, and brief §14 forbids "shader motion that
 * lowers text contrast" — which for a field that MOVES means the worst frame has to clear the bar,
 * not the average one. Page copy is `--drop-off-white` (#f2f2f2, relative luminance 0.888), so a
 * 4.5:1 ratio allows a background luminance of at most 0.158 — a neutral sRGB channel of 0.4346
 * (111/255). Every value below is solved against that, using the mesh's own brightest control
 * colour (#E4E4E6) rather than an assumed white.
 */
export const MESH_OPENING_PEAK_CEILING = 0.4346;

/**
 * The settled look of each variant — where it arrives at `amount === 1`.
 *
 * Ordering is the part the brief fixes: Art Pieces is slower and darker than Tracks ("Mesh
 * movement may slow and darken slightly for reading comfort"), and the footer entry ends at pure
 * black with no contrast left ("The Mesh gradually loses contrast and fades to pure black").
 * The exact scalars are tuned by feel.
 *
 * `opening` is the exception whose scalars are NOT free: with `contrast` at 0.85 the brightest
 * cell composites to `pivot + (0.902 - pivot) * 0.85 = 0.845` before brightness, so brightness
 * must stay at or below 0.514 to respect {@link MESH_OPENING_PEAK_CEILING}. It is set to 0.48,
 * which lands the worst cell at ~0.406 (103/255) and measures ~5.0:1 — the slack is deliberate
 * headroom for the grain term, which is added AFTER the brightness multiply. Raising brightness
 * or contrast here is a contrast regression, not a style choice; `speedScale` is the free knob.
 */
export const MESH_VARIANT_TARGETS: Readonly<Record<MeshVariant, MeshVariantSettings>> =
  Object.freeze({
    opening: Object.freeze({ speedScale: 2.4, brightness: 0.48, contrast: 0.85 }),
    normal: Object.freeze({ speedScale: 1, brightness: 1, contrast: 1 }),
    reading: Object.freeze({ speedScale: 0.55, brightness: 0.78, contrast: 0.92 }),
    fadeToBlack: Object.freeze({ speedScale: 0, brightness: 0, contrast: 0 }),
  });

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/** Smoothstep. Zero slope at both ends, so a variant never starts or stops with a jolt. */
function ease(amount: number): number {
  const t = clamp01(amount);
  return t * t * (3 - 2 * t);
}

function blend(from: MeshVariantSettings, to: MeshVariantSettings, t: number): MeshVariantSettings {
  return {
    speedScale: from.speedScale + (to.speedScale - from.speedScale) * t,
    brightness: from.brightness + (to.brightness - from.brightness) * t,
    contrast: from.contrast + (to.contrast - from.contrast) * t,
  };
}

/**
 * The uniform settings for one mesh descriptor. A pure function: the same descriptor always
 * yields the same settings, which is what lets reverse scroll restore the field exactly.
 *
 * Each variant starts from the settled state of the variant before it, so the hand-offs
 * Tracks -> Art Pieces -> Footer are continuous by construction.
 */
export function meshVariantUniforms(
  descriptor: MeshDescriptor | null | undefined,
): MeshVariantSettings {
  if (!descriptor) return { ...MESH_VARIANT_TARGETS.normal };
  const t = ease(descriptor.amount);
  // `opening` is the one variant that does NOT ramp from a predecessor. It is the page's first
  // ground, so there is no earlier settled state to be continuous with — and blending in from
  // `normal` would start every opening scene at full brightness, which is precisely where the
  // display type is least readable. Constant in `amount`, and legible on its very first frame.
  if (descriptor.variant === "opening") {
    return { ...MESH_VARIANT_TARGETS.opening };
  }
  if (descriptor.variant === "reading") {
    return blend(MESH_VARIANT_TARGETS.normal, MESH_VARIANT_TARGETS.reading, t);
  }
  if (descriptor.variant === "fadeToBlack") {
    return blend(MESH_VARIANT_TARGETS.reading, MESH_VARIANT_TARGETS.fadeToBlack, t);
  }
  return { ...MESH_VARIANT_TARGETS.normal };
}

/**
 * Settings for a frame, covering the two moments the reducer emits no mesh descriptor at all:
 *
 * - during pixel transition B the mesh is being revealed through the cells but has no descriptor
 *   yet — it must already be alive underneath;
 * - once the footer fade completes the reducer drops the descriptor for good — the field is gone,
 *   and a scroll jump straight into the footer (refresh at the bottom, back-nav restore) must not
 *   flash a full-brightness mesh while the canvas crossfades the mode out.
 *
 * `footerReveal` is what separates the two, because the canvas hands each crossfade layer a frame
 * reporting that LAYER's own mode — the mesh module never sees `"footerLight"` there. Both inputs
 * are reducer output; nothing here re-derives scene state.
 */
export function meshSettingsForFrame(
  mode: BackgroundMode,
  transitionState: Pick<TransitionState, "mesh" | "footerReveal"> | null | undefined,
): MeshVariantSettings {
  const descriptor = transitionState?.mesh ?? null;
  if (descriptor) return meshVariantUniforms(descriptor);
  if (mode === "footerLight" || (transitionState?.footerReveal ?? 0) > 0) {
    return { ...MESH_VARIANT_TARGETS.fadeToBlack };
  }
  return { ...MESH_VARIANT_TARGETS.normal };
}

/* ------------------------------------------------------------- mesh clock */

/**
 * The mesh's own continuous clock. `meshTime` only ever moves forward, by the elapsed canvas
 * time scaled by the active variant's `speedScale`. Because the scale applies to the increment
 * and never to `meshTime` itself, slowing down (Art Pieces) or stopping (reduced motion, the end
 * of the fade) can never make the field jump, restart, or reseed.
 */
export type MeshClock = {
  /** Seconds of mesh drift accumulated so far. Fed to `uTime`. */
  meshTime: number;
  /** The canvas clock reading at the last update, so the next frame can take a delta. */
  sourceSeconds: number;
};

/**
 * A non-zero starting point, so the very first frame is already mid-drift instead of the
 * degenerate all-phases-aligned state.
 */
export const MESH_CLOCK_ORIGIN = 137.5;

/** Longest frame delta the clock will accept — a backgrounded tab must not fast-forward the field. */
const MAX_FRAME_SECONDS = 1 / 12;

export function createMeshClock(sourceSeconds = 0): MeshClock {
  return {
    meshTime: MESH_CLOCK_ORIGIN,
    sourceSeconds: Number.isFinite(sourceSeconds) ? sourceSeconds : 0,
  };
}

/** Advance the clock by one frame. Never rewinds, never jumps, never throws. */
export function advanceMeshClock(
  clock: MeshClock,
  sourceSeconds: number,
  speedScale: number,
): MeshClock {
  const now = Number.isFinite(sourceSeconds) ? sourceSeconds : clock.sourceSeconds;
  const rawDelta = now - clock.sourceSeconds;
  const delta = rawDelta > 0 ? Math.min(rawDelta, MAX_FRAME_SECONDS) : 0;
  const rate = Number.isFinite(speedScale) && speedScale > 0 ? speedScale : 0;
  return { meshTime: clock.meshTime + delta * rate, sourceSeconds: now };
}

function isMeshClock(value: unknown): value is MeshClock {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<MeshClock>;
  return (
    typeof candidate.meshTime === "number" &&
    Number.isFinite(candidate.meshTime) &&
    typeof candidate.sourceSeconds === "number" &&
    Number.isFinite(candidate.sourceSeconds)
  );
}

/* ----------------------------------------------------------- quality tiers */

/** The tier whose settings are treated as full detail. */
const REFERENCE_MESH_SUBDIVISION = 128;

/** Fine grain amplitude at full detail, tuned from the preset's `fGrain: 16`. */
const GRAIN_AMPLITUDE = 0.018;

export type MeshDetailSettings = {
  /** Domain-warp octaves driving the drift. Fewer octaves = a simpler, cheaper field. */
  warpOctaves: number;
  /** Grain amplitude, 0 when the tier has no grain budget. */
  grain: number;
};

/**
 * Brief Section 14 detail reduction, read from the tier's own settings object rather than
 * re-derived: fewer subdivisions on medium and low, and no grain at all on low.
 */
export function meshDetailUniforms(quality: QualityTierSettings): MeshDetailSettings {
  const detail = clamp01(quality.shaderDetail.meshSubdivision / REFERENCE_MESH_SUBDIVISION);
  const warpOctaves = detail >= 1 ? 3 : detail >= 0.5 ? 2 : 1;
  const grain = quality.shaderDetail.grain ? GRAIN_AMPLITUDE * (0.5 + 0.5 * detail) : 0;
  return { warpOctaves, grain };
}

/* ------------------------------------------------------------------- GLSL */

const LATTICE_MAX_X = `${MESH_GRID_COLUMNS - 1}.0`;
const LATTICE_MAX_Y = `${MESH_GRID_ROWS - 1}.0`;

/**
 * `smooth: 1` interpolation. Weights are a separable smootherstep tent, which is a partition of
 * unity with zero first and second derivatives at every lattice line — so cell boundaries are
 * invisible and the field has no seams.
 *
 * The warp is tapered to nothing at the frame edges (`fixEdges: 1`), so the outer control colors
 * stay welded to the frame and the field never pulls away from an edge.
 */
/**
 * Uniforms the shared mesh field reads. Any program that includes {@link MESH_FIELD_GLSL} must
 * declare exactly these, which is why they live here rather than being retyped per shader.
 */
export const MESH_FIELD_UNIFORMS_GLSL = /* glsl */ `
  uniform vec3 uMeshColors[${MESH_CONTROL_COUNT}];
  uniform vec3 uPivot;
  uniform float uBrightness;
  uniform float uContrast;
  uniform float uDrift;
  uniform float uEdgeFix;
  uniform float uWarpOctaves;
  uniform float uGrain;
`;

/**
 * THE mesh field — the single definition of what the Monochrome Mesh looks like.
 *
 * Exported because the pixel mosaic resolves INTO this field at the end of transition B. It used
 * to carry its own cheap approximation (a 3x3 value-noise grey ramp), which meant the cells
 * revealed one field and the next frame painted a different one — a ~1.7x brightness step and a
 * change of structure in a single frame, exactly what brief §19 calls a "major visual jump" and
 * what §7.7 forbids by asking that the new mesh be revealed THROUGH the cells. One definition,
 * included by both programs, is what makes that swap a no-op.
 */
export const MESH_FIELD_GLSL = /* glsl */ `
  float latticeWeight(float coord, float index) {
    float d = clamp(abs(coord - index), 0.0, 1.0);
    float s = d * d * d * (d * (d * 6.0 - 15.0) + 10.0);
    return 1.0 - s;
  }

  vec3 latticeColor(vec2 p) {
    vec2 g = vec2(p.x * ${LATTICE_MAX_X}, p.y * ${LATTICE_MAX_Y});
    vec3 acc = vec3(0.0);
    for (int y = 0; y < ${MESH_GRID_ROWS}; y++) {
      float wy = latticeWeight(g.y, float(y));
      for (int x = 0; x < ${MESH_GRID_COLUMNS}; x++) {
        float wx = latticeWeight(g.x, float(x));
        acc += uMeshColors[y * ${MESH_GRID_COLUMNS} + x] * (wx * wy);
      }
    }
    return acc;
  }

  vec2 meshWarp(vec2 p, float aspect, float t) {
    float x = (p.x - 0.5) * aspect + 0.5;
    float y = p.y;
    vec2 w = vec2(
      sin(y * 1.90 + t * 0.29) + 0.70 * sin(x * 1.30 - t * 0.21),
      cos(x * 2.10 - t * 0.24) + 0.70 * cos(y * 1.50 + t * 0.18)
    );
    if (uWarpOctaves > 1.5) {
      w += 0.42 * vec2(
        sin(y * 3.70 - t * 0.41 + 1.3),
        cos(x * 3.10 + t * 0.37 - 0.7)
      );
    }
    if (uWarpOctaves > 2.5) {
      w += 0.18 * vec2(
        sin(x * 6.30 + t * 0.53),
        cos(y * 5.90 - t * 0.47)
      );
    }
    return w * 0.16;
  }

  float edgeTaper(vec2 p) {
    vec2 lower = smoothstep(vec2(0.0), vec2(0.30), p);
    vec2 upper = smoothstep(vec2(0.0), vec2(0.30), vec2(1.0) - p);
    return lower.x * lower.y * upper.x * upper.y;
  }

  // Hash without sine (Dave Hoskins). The cheaper fract(p.x * p.y) variants have degenerate
  // columns that read as a hairline seam down a gradient this smooth.
  float hash21(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
  }

  vec3 dropMeshFieldColor(vec2 p, float aspect, float t) {
    float taper = mix(1.0, edgeTaper(p), clamp(uEdgeFix, 0.0, 1.0));
    vec2 sampled = clamp(p + meshWarp(p, aspect, t) * uDrift * taper, 0.0, 1.0);

    vec3 field = latticeColor(sampled);

    // Contrast loss collapses the field onto its own mean before brightness finishes the fade,
    // so the footer entry reads as the mesh flattening out rather than a plain dip to black.
    vec3 color = mix(uPivot, field, clamp(uContrast, 0.0, 1.0)) * max(uBrightness, 0.0);

    if (uGrain > 0.0) {
      float g = hash21(gl_FragCoord.xy + floor(t * 24.0)) - 0.5;
      color += g * uGrain * max(uBrightness, 0.0);
    }

    return max(color, 0.0);
  }
`;

const MONO_MESH_FRAGMENT_SHADER = /* glsl */ `
  varying vec2 vUv;

  uniform vec2 uResolution;
  // The clock accumulates for as long as the page is open; mediump would judder it.
  uniform highp float uTime;
  // Output alpha. The shared canvas crossfades with a constant blend alpha, so this stays 1;
  // it exists so a consumer that needs per-module opacity has a handle without a fork.
  uniform float uOpacity;

${MESH_FIELD_UNIFORMS_GLSL}
${MESH_FIELD_GLSL}

  void main() {
    vec2 p = clamp(vUv, 0.0, 1.0);
    float aspect = uResolution.x / max(uResolution.y, 1.0);
    gl_FragColor = vec4(dropMeshFieldColor(p, aspect, uTime), uOpacity);
  }
`;

/* -------------------------------------------------------------- fallback */

function channelByte(value: number): number {
  return Math.max(0, Math.min(255, Math.round(value * 255)));
}

function rgbaCss(rgb: Rgb, alpha: number): string {
  const a = Math.max(0, Math.min(1, alpha));
  return `rgba(${channelByte(rgb[0])}, ${channelByte(rgb[1])}, ${channelByte(rgb[2])}, ${Number(
    a.toFixed(3),
  )})`;
}

function percent(value: number): string {
  return `${Number((value * 100).toFixed(2))}%`;
}

/**
 * The no-WebGL / context-lost background: the same sixteen control colors laid out as static
 * radial gradients on the preset's black, dimmed and flattened by the same variant settings the
 * shader uses. Returns a value for the CSS `background` shorthand.
 */
export function monoMeshFallbackCss(settings: MeshVariantSettings): string {
  const layers: string[] = [];

  const dim = 1 - clamp01(settings.brightness);
  if (dim > 0) {
    layers.push(`linear-gradient(${rgbaCss([0, 0, 0], dim)}, ${rgbaCss([0, 0, 0], dim)})`);
  }

  const flatten = 1 - clamp01(settings.contrast);
  if (flatten > 0) {
    layers.push(
      `linear-gradient(${rgbaCss(MESH_PIVOT_RGB, flatten)}, ${rgbaCss(MESH_PIVOT_RGB, flatten)})`,
    );
  }

  MESH_CONTROL_COLORS_RGB.forEach((row, rowIndex) => {
    row.forEach((rgb, columnIndex) => {
      const x = percent(columnIndex / (MESH_GRID_COLUMNS - 1));
      // Row 0 is the bottom row in the shader; CSS percentages grow downward.
      const y = percent(1 - rowIndex / (MESH_GRID_ROWS - 1));
      layers.push(
        `radial-gradient(58% 58% at ${x} ${y}, ${rgbaCss(rgb, 0.92)} 0%, ${rgbaCss(rgb, 0)} 70%)`,
      );
    });
  });

  layers.push(MONO_MESH_PRESET.background);
  return layers.join(", ");
}

/* --------------------------------------------------------------- module */

/**
 * ONE clock for the mesh field, shared by every program that paints it.
 *
 * The pixel mosaic resolves into the mesh at the end of transition B, and the mesh module takes
 * over on the very next frame. If each kept its own clock the two would be at different phases and
 * the handover would jump, however identical the field function is. A module-level singleton is
 * correct here because there is exactly one background canvas by design (brief §12).
 *
 * The guard makes the frame idempotent: whichever module asks first advances the clock, and any
 * other module asking within the same frame reads the same value instead of double-advancing it.
 */
let sharedMeshClock: MeshClock = createMeshClock();
let sharedMeshClockSource = Number.NEGATIVE_INFINITY;

export function sharedMeshTime(sourceSeconds: number, speedScale: number): number {
  if (sourceSeconds !== sharedMeshClockSource) {
    sharedMeshClock = advanceMeshClock(sharedMeshClock, sourceSeconds, speedScale);
    sharedMeshClockSource = sourceSeconds;
  }
  return sharedMeshClock.meshTime;
}

/** Drop the shared clock back to its origin. Canvas unmount only. */
export function resetSharedMeshClock(): void {
  sharedMeshClock = createMeshClock();
  sharedMeshClockSource = Number.NEGATIVE_INFINITY;
}

/** The uniforms {@link MESH_FIELD_GLSL} reads, at the mesh's resting `normal` variant. */
export function createMeshFieldUniforms(): Record<string, IUniform> {
  const initial = MESH_VARIANT_TARGETS.normal;
  return {
    uMeshColors: { value: meshControlColorArray() },
    uPivot: { value: [MESH_PIVOT_RGB[0], MESH_PIVOT_RGB[1], MESH_PIVOT_RGB[2]] },
    uBrightness: { value: initial.brightness },
    uContrast: { value: initial.contrast },
    uDrift: { value: MONO_MESH_PRESET.drift },
    uEdgeFix: { value: MONO_MESH_PRESET.fixEdges },
    uWarpOctaves: { value: 1 },
    uGrain: { value: 0 },
  };
}

/** Write one frame of mesh-field state. Shared so the mosaic cannot drift from the mesh. */
export function writeMeshFieldUniforms(
  uniforms: Record<string, IUniform>,
  settings: Pick<MeshVariantSettings, "brightness" | "contrast">,
  detail: MeshDetailSettings,
): void {
  setNumber(uniforms, "uBrightness", settings.brightness);
  setNumber(uniforms, "uContrast", settings.contrast);
  setNumber(uniforms, "uWarpOctaves", detail.warpOctaves);
  setNumber(uniforms, "uGrain", detail.grain);
}

/** CPU-side bookkeeping carried alongside the GL uniforms; no GLSL uniform matches this key. */
const MESH_CLOCK_KEY = "meshClock";

function setNumber(uniforms: Record<string, IUniform>, key: string, value: number): void {
  const entry = uniforms[key];
  if (entry) entry.value = value;
}

function setVec2(uniforms: Record<string, IUniform>, key: string, x: number, y: number): void {
  const entry = uniforms[key];
  if (!entry) return;
  const target: unknown = entry.value;
  if (Array.isArray(target) && target.length >= 2) {
    target[0] = x;
    target[1] = y;
    return;
  }
  entry.value = [x, y];
}

export const monoMeshShader: BackgroundShaderModule = {
  mode: "monoMesh",
  fragmentShader: MONO_MESH_FRAGMENT_SHADER,

  createUniforms(): Record<string, IUniform> {
    const initial = MESH_VARIANT_TARGETS.normal;
    return {
      uResolution: { value: [1, 1] },
      uTime: { value: MESH_CLOCK_ORIGIN },
      ...createMeshFieldUniforms(),
      uOpacity: { value: 1 },
      [MESH_CLOCK_KEY]: { value: createMeshClock() },
    };
  },

  update(uniforms: Record<string, IUniform>, frame: BackgroundFrame): void {
    const settings = meshSettingsForFrame(frame.mode, frame.transitionState);
    const detail = meshDetailUniforms(frame.quality);

    // Reduced motion holds the field on one static frame; it does not reset it, so toggling the
    // preference mid-scroll stops and resumes the same drift instead of cutting to a new one.
    const rate = frame.reducedMotion ? 0 : settings.speedScale * MONO_MESH_PRESET.speed;

    // The SHARED clock, not a per-module one: the mosaic paints this same field while it resolves
    // at the end of transition B, and the handover is only seamless if both read one phase.
    const meshTime = sharedMeshTime(frame.timeSeconds, rate);
    const clockEntry = uniforms[MESH_CLOCK_KEY];
    if (clockEntry) clockEntry.value = { meshTime, sourceSeconds: frame.timeSeconds };

    setNumber(uniforms, "uTime", meshTime);
    writeMeshFieldUniforms(uniforms, settings, detail);
    setVec2(uniforms, "uResolution", frame.resolution[0], frame.resolution[1]);
  },

  fallbackCss(frame?: Pick<BackgroundFrame, "transitionState" | "sceneProgress">): string {
    return monoMeshFallbackCss(meshVariantUniforms(frame?.transitionState?.mesh ?? null));
  },
};
