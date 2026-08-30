/**
 * Wavy Dots — the film scene's background mode (`wavyDots`).
 *
 * Brief Section 7.6 supplies a MetalForge preset as a *reference*, not an embed:
 *
 * ```ts
 * { effect: "dots", style: "wavy", speed: 1, brightness: 1, tint: "#FFFFFF",
 *   background: "#000000", dotSize: 1, gridDensity: 1, patternScale: 1,
 *   vignette: 1, horizon: -0.45, amplitude: 1, depthFade: 1 }
 * ```
 *
 * "Rebuild it for web in GLSL; do not embed a MetalForge editor or use a recorded video."
 * So this module is a from-scratch perspective dot floor: white dots on black, laid on a
 * ground plane under a horizon, undulating with a wave, fading with depth, vignetted at the
 * frame edge. Every preset knob at its default `1` maps to one named constant below, so the
 * preset stays legible in the code instead of dissolving into magic numbers.
 *
 * **Restraint is a requirement, not a taste call.** The film scene's text sits on top of this
 * (brief Section 7.6 layout). `DOTS.BRIGHTNESS` deliberately renders the preset's `brightness: 1`
 * well under full white, the field dissolves before it reaches the horizon, and the vignette
 * pulls the frame edges — where the poster and copy live — back down toward black.
 *
 * Reading `horizon: -0.45`: the preset's sign convention is screen-space (y down), so a
 * negative horizon tilts the camera down and the horizon line sits *above* centre, with the
 * receding floor filling the composition beneath it. That is the reference look, and it is what
 * `DOTS.HORIZON_Y` encodes in this file's y-up UV space.
 *
 * The field is exported as a standalone GLSL function ({@link WAVY_DOTS_FIELD_GLSL}) because
 * pixel transitions A and B dissolve *into* and *out of* this exact background — they call the
 * same function with the same time source ({@link wavyDotsTime}), so the handoff between the
 * mosaic and this mode is seamless rather than a re-derived lookalike.
 */

import type { IUniform } from "three";

import type { QualityTierSettings } from "@/lib/performance/quality-tier";
import {
  GLSL_BRAND_COLORS,
  type BackgroundFrame,
  type BackgroundShaderModule,
} from "./shader-contract";

/* -------------------------------------------------------------------------- */
/* Preset mapping — brief Section 7.6, one constant per knob                    */
/* -------------------------------------------------------------------------- */

/**
 * Every tunable of the dot floor, in one record. The GLSL below is generated from this record
 * as `#define`s, so there is exactly one place to tune the preset and no chance of the shader
 * source drifting from the documented values.
 */
const DOTS = {
  /** `horizon: -0.45` in y-up UV space: the horizon line sits 0.45 above frame centre. */
  HORIZON_Y: 0.45,
  /** Camera height above the ground plane. With the density below it sets the perspective rake. */
  CAMERA_H: 0.35,
  /** `gridDensity: 1` x `patternScale: 1` — lattice cells per world unit. */
  DENSITY: 26.0,
  /** `dotSize: 1` — dot radius in lattice units (a cell is 1x1). */
  RADIUS: 0.12,
  /** `brightness: 1`, mapped to a restrained web level so film text stays readable. */
  BRIGHTNESS: 0.62,
  /** `amplitude: 1` — wave displacement, in lattice rows. */
  AMPLITUDE: 0.42,
  /** `depthFade: 1` — exponential dimming per world unit of depth. */
  DEPTH_FADE: 0.9,
  /** `vignette: 1` — how far the frame edge is pulled back toward black. */
  VIGNETTE: 0.85,
  /** `speed: 1` — lattice rows the floor drifts toward the viewer per second. */
  DRIFT_ROWS: 0.45,
  /** `speed: 1` — wave phase advance per second. */
  WAVE_SPEED: 0.9,
  /** Dot brightness gain on wave crests, so the undulation reads as depth, not just offset. */
  CREST_GAIN: 0.22,
  /** Edge softness target, in device-independent pixels. */
  EDGE_PX: 1.6,
  /** Desktop pointer parallax, in UV units. Enhancement only; never required (contract). */
  POINTER_PARALLAX: 0.02,
} as const;

/**
 * The frozen pose rendered when the visitor prefers reduced motion. Not zero: at t=0 the wave
 * is flat, and a flat frame loses the "wavy" character the preset is named for.
 */
export const WAVY_DOTS_STATIC_POSE_SECONDS = 3.2;

/** Detail levels: wave octaves in the field. 0 = simplified noise (brief Section 14, low tier). */
const DETAIL_LOW = 0;
const DETAIL_HIGH = 2;

/**
 * Detail before a tier has been detected — the server-render / first-frame value, matching the
 * medium default tier. Also the neutral seed for any module that renders this field.
 */
export const WAVY_DOTS_DEFAULT_DETAIL = 1;

/** Sub-pixel cull threshold, in device-independent pixels of lattice-cell height. */
export const WAVY_DOTS_DEFAULT_MIN_CELL_PX = 1.1;
/** Low tier culls earlier: fewer, larger dots — the brief's "simplified" end of the scale. */
const MIN_CELL_PX_LOW = 2.4;

/* -------------------------------------------------------------------------- */
/* GLSL                                                                         */
/* -------------------------------------------------------------------------- */

/** Format a TS number as a GLSL ES 1.00 float literal (which always needs a decimal point). */
export function glslFloat(value: number): string {
  return Number.isInteger(value) ? `${value}.0` : `${value}`;
}

function defines(prefix: string, values: Readonly<Record<string, number>>): string {
  return Object.entries(values)
    .map(([key, value]) => `#define ${prefix}${key} ${glslFloat(value)}`)
    .join("\n");
}

/**
 * The dot floor as a reusable GLSL function:
 *
 * ```glsl
 * vec3 dropWavyDotsField(vec2 uv, vec2 res, float t, float detail, float pointerX, float minCellPx)
 * ```
 *
 * `uv` is y-up (0,0 bottom-left), `res` is the drawing buffer in CSS pixels, `t` comes from
 * {@link wavyDotsTime}, `detail` from {@link wavyDotsDetailLevel} and `minCellPx` from
 * {@link wavyDotsMinCellPx}. Requires {@link GLSL_BRAND_COLORS} earlier in the same program.
 *
 * Anti-aliasing is analytic rather than derivative-based: the perspective mapping is known in
 * closed form, so the on-screen height of one lattice cell is computed directly. That keeps the
 * module free of the `GL_OES_standard_derivatives` extension and gives the same edge width on
 * every driver — and the same value feeds the sub-pixel cull that keeps the far field from
 * turning into moire.
 */
export const WAVY_DOTS_FIELD_GLSL = /* glsl */ `
${defines("DROP_DOTS_", DOTS)}

// Wave octaves. Each detail step adds one, so low tier runs a single sine (brief Section 14).
float dropWavyDotsWave(vec2 g, float t, float detail) {
  float w = sin(g.x * 0.75 + t * DROP_DOTS_WAVE_SPEED);
  float amp = 1.0;
  if (detail > 0.5) {
    w += 0.65 * sin(g.y * 0.55 - t * 0.70 + g.x * 0.35);
    amp += 0.65;
  }
  if (detail > 1.5) {
    w += 0.40 * sin((g.x + g.y) * 0.32 + t * 0.45);
    amp += 0.40;
  }
  return w / amp;
}

vec3 dropWavyDotsField(vec2 uv, vec2 res, float t, float detail, float pointerX, float minCellPx) {
  float aspect = res.x / max(res.y, 1.0);
  vec2 p = (uv - 0.5) * vec2(aspect, 1.0);
  p.x += pointerX * DROP_DOTS_POINTER_PARALLAX;

  vec3 col = DROP_BLACK;

  // Distance below the horizon line. At or above it there is no ground plane to sample.
  float below = DROP_DOTS_HORIZON_Y - p.y;
  if (below > 0.0015) {
    // Pinhole ground plane: screen y maps to depth, screen x scales with that depth.
    float depth = DROP_DOTS_CAMERA_H / below;
    float worldX = p.x * depth;

    vec2 g = vec2(worldX, depth) * DROP_DOTS_DENSITY;
    g.y -= t * DROP_DOTS_DRIFT_ROWS;

    float wave = dropWavyDotsWave(g, t, detail);
    vec2 local = fract(g + vec2(0.0, wave * DROP_DOTS_AMPLITUDE)) - 0.5;

    // On-screen height of one lattice cell, in CSS pixels: d(depth)/d(screen y) = h / below^2.
    float cellPx = (below * below) / (DROP_DOTS_DENSITY * DROP_DOTS_CAMERA_H) * res.y;
    float edge = clamp(DROP_DOTS_EDGE_PX / max(cellPx, 0.001), 0.015, 0.5);

    float radius = DROP_DOTS_RADIUS * (1.0 + DROP_DOTS_CREST_GAIN * wave);
    float mask = 1.0 - smoothstep(radius - edge, radius + edge, length(local));

    float sizeFade = smoothstep(minCellPx, minCellPx * 2.9, cellPx);
    float depthFade = exp(-depth * DROP_DOTS_DEPTH_FADE);
    float horizonFade = smoothstep(0.0, 0.05, below);
    float crest = (1.0 - DROP_DOTS_CREST_GAIN) + DROP_DOTS_CREST_GAIN * (wave * 0.5 + 0.5);

    col = DROP_WHITE * (DROP_DOTS_BRIGHTNESS * mask * sizeFade * depthFade * horizonFade * crest);
  }

  float r = length((uv - 0.5) * vec2(aspect, 1.0)) * 1.35;
  col *= 1.0 - DROP_DOTS_VIGNETTE * smoothstep(0.35, 1.0, r);
  return col;
}
`;

const WAVY_DOTS_FRAGMENT_SHADER = /* glsl */ `
varying vec2 vUv;

uniform vec2 uResolution;
uniform float uTime;
uniform float uDetail;
uniform float uPointerX;
uniform float uMinCellPx;

${GLSL_BRAND_COLORS}
${WAVY_DOTS_FIELD_GLSL}

void main() {
  vec2 res = max(uResolution, vec2(1.0));
  vec3 col = dropWavyDotsField(vUv, res, uTime, uDetail, uPointerX, uMinCellPx);
  gl_FragColor = vec4(col, 1.0);
}
`;

/* -------------------------------------------------------------------------- */
/* Frame -> uniform mapping                                                     */
/* -------------------------------------------------------------------------- */

/**
 * The single time source for the dot floor.
 *
 * Both pixel transitions render this same field, so they must agree on its phase to the frame:
 * `wavyDots` is the incoming background of transition A and the outgoing background of
 * transition B, and any independently-derived clock would show as a jump at the handoff.
 * Deriving it from `timeSeconds` alone — never from `sceneProgress` — is what keeps the three
 * modes in lockstep.
 *
 * Reduced motion returns the frozen pose, so the field renders as a still image.
 */
export function wavyDotsTime(frame: Pick<BackgroundFrame, "reducedMotion" | "timeSeconds">): number {
  if (frame.reducedMotion) return WAVY_DOTS_STATIC_POSE_SECONDS;
  const seconds = Number.isFinite(frame.timeSeconds) ? frame.timeSeconds : 0;
  return WAVY_DOTS_STATIC_POSE_SECONDS + seconds;
}

/** Wave octaves for the detected tier: 2 on high, 1 on medium, 0 (single sine) on low. */
export function wavyDotsDetailLevel(quality: QualityTierSettings): number {
  if (quality.shaderDetail.noiseDetail === "simplified") return DETAIL_LOW;
  return quality.tier === "high" ? DETAIL_HIGH : WAVY_DOTS_DEFAULT_DETAIL;
}

/** Sub-pixel cull threshold for the detected tier — low tier keeps fewer, larger dots. */
export function wavyDotsMinCellPx(quality: QualityTierSettings): number {
  return quality.tier === "low" ? MIN_CELL_PX_LOW : WAVY_DOTS_DEFAULT_MIN_CELL_PX;
}

function pointerX(frame: BackgroundFrame): number {
  if (frame.reducedMotion || !frame.quality.shaderDetail.pointerResponse) return 0;
  const x = frame.pointer[0];
  return Number.isFinite(x) ? Math.max(-1, Math.min(1, x)) : 0;
}

/**
 * Static background for the no-WebGL / context-lost path (contract: never a blank page).
 * A perspective-squashed dot lattice, a faint ground glow, and the same vignette on top.
 */
export const WAVY_DOTS_FALLBACK_CSS = [
  "radial-gradient(circle at 50% 46%, rgba(0, 0, 0, 0) 18%, rgba(0, 0, 0, 0.92) 96%)",
  "radial-gradient(circle at 50% 50%, rgba(255, 255, 254, 0.32) 0 1px, rgba(0, 0, 0, 0) 1.7px) 0 0 / 46px 30px",
  "radial-gradient(ellipse 120% 60% at 50% 100%, rgba(255, 255, 254, 0.08) 0%, rgba(0, 0, 0, 0) 70%)",
  "#000000",
].join(", ");

/* -------------------------------------------------------------------------- */
/* Module                                                                       */
/* -------------------------------------------------------------------------- */

export const wavyDotsShader: BackgroundShaderModule = {
  mode: "wavyDots",
  fragmentShader: WAVY_DOTS_FRAGMENT_SHADER,

  createUniforms(): Record<string, IUniform> {
    return {
      uResolution: { value: [1, 1] as [number, number] },
      uTime: { value: WAVY_DOTS_STATIC_POSE_SECONDS },
      uDetail: { value: WAVY_DOTS_DEFAULT_DETAIL },
      uPointerX: { value: 0 },
      uMinCellPx: { value: WAVY_DOTS_DEFAULT_MIN_CELL_PX },
    };
  },

  update(uniforms: Record<string, IUniform>, frame: BackgroundFrame): void {
    const resolution = uniforms.uResolution.value as [number, number];
    resolution[0] = Math.max(1, frame.resolution[0]);
    resolution[1] = Math.max(1, frame.resolution[1]);

    uniforms.uTime.value = wavyDotsTime(frame);
    uniforms.uDetail.value = wavyDotsDetailLevel(frame.quality);
    uniforms.uMinCellPx.value = wavyDotsMinCellPx(frame.quality);
    uniforms.uPointerX.value = pointerX(frame);
  },

  fallbackCss(): string {
    return WAVY_DOTS_FALLBACK_CSS;
  },
};
