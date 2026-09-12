/**
 * The `acidLime` background mode — the ground behind the Tracks carousel.
 *
 * A soft pool of deep green light lying along the floor of an almost-black frame, waving slowly,
 * swaying side to side and breathing. Written from a supplied metalforge `spike-lime` configuration,
 * which defines composition and motion intent only: none of that site's shader source, assets or
 * copy is used here, per the repo's rule against shipping reference-site material. The numbers below
 * are this file's own.
 *
 * WHY IT POOLS LOW. The Tracks scene carries the page's largest Persian heading, an all-caps Latin
 * one under it, and eleven pieces of cover art that are themselves mostly dark. The ground has to be
 * a ground. So the field is near-black everywhere the type and the carousel are, and the green lives
 * along the bottom edge where nothing sits.
 *
 * WHY THERE IS ONLY ONE GREEN. {@link ACID} is a directed colour, and the field resolves to exactly
 * it at the brightest point of the pool rather than adding lighter tints on top of it. Everything
 * else in the frame is that same green mixed down toward the ground, so the scene reads as one light
 * falling off rather than as a gradient between two invented colours.
 *
 * MOTION. Three independent slow cycles, none of them synchronised: the pool rides a wave across the
 * frame, its light sways horizontally, and the whole field breathes. Nothing here is scroll-driven,
 * so the scene is alive whether or not the reader is moving — which is the point of a ground that
 * sits under a carousel the reader drives by hand. Under reduced motion all three stop, because the
 * clock stops; see {@link update}.
 */

import { Vector2, type IUniform } from "three";

import {
  FULLSCREEN_QUAD_VERTEX_SHADER,
  type BackgroundFrame,
  type BackgroundShaderModule,
} from "./shader-contract";
import { wavyDotsTime } from "./WavyDotsShader";

/* ------------------------------------------------------------------ palette */

/** The ground: near-black, carrying just enough of the green to sit under the pool rather than beside it. */
const BG = [0.02, 0.024, 0.016] as const;

/**
 * The green. A directed value — rgb(6, 59, 0) — and the only chromatic colour in this field.
 *
 * Written as plain sRGB over 255, which is the convention every shader here uses (see
 * `GLSL_BRAND_COLORS`, where DROP off-white is 0.94902 rather than a linearised 0.887).
 */
const ACID = [6 / 255, 59 / 255, 0 / 255] as const;

/* ------------------------------------------------------------------ tuning */

/**
 * The brightest the field is ever allowed to get, as a luminance.
 *
 * DROP off-white copy is #f2f2f2, and 4.5:1 allows a background luminance of at most 0.158. The
 * green at full strength sits far under that, so on the current palette this guard never engages —
 * it is here so that a later retune toward a brighter green fails safe instead of quietly dropping
 * the caption below the bar. Applied to luminance rather than per channel, which keeps the hue
 * exactly where it is; clamping channels would desaturate the crest toward white.
 */
export const LIME_PEAK_CEILING = 0.42;

/** How far up the frame the light is allowed to reach, as a fraction of height from the bottom. */
const ACID_POOL_HEIGHT = 0.4;
/** Wave speed, cycles per second, from the supplied animSpeed. */
const ACID_WAVE_SPEED = 0.178;
/** Spatial frequency of the wave across the frame. */
const ACID_WAVE_FREQ = 3.8;
/** How much the wave displaces the crest, in fractions of frame height. */
const ACID_WAVE_AMOUNT = 0.084;
/** Side-to-side sway of the light, cycles per second. */
const ACID_SWAY_SPEED = 0.11;
/** Breathing of the whole field, cycles per second. */
const ACID_PULSE_SPEED = 0.14;
/** How deep the breath goes, as a fraction of the field's strength. */
const ACID_PULSE_DEPTH = 0.22;

const f = (n: number) => n.toFixed(5);

/* -------------------------------------------------------------------- glsl */

/**
 * The field, as a function of position and time.
 *
 * Shared verbatim with PixelMosaicShader's `dropAcidLimeLook`, on the same clock, so transition B
 * resolves INTO this exact frame cell by cell rather than into a re-derived lookalike — the same
 * arrangement WavyDotsShader already has with that file. Retuning one means retuning both.
 */
export const ACID_LIME_FIELD_GLSL = /* glsl */ `
  const vec3  ACID_BG          = vec3(${f(BG[0])}, ${f(BG[1])}, ${f(BG[2])});
  const vec3  ACID_GREEN       = vec3(${f(ACID[0])}, ${f(ACID[1])}, ${f(ACID[2])});
  const float ACID_POOL_HEIGHT = ${f(ACID_POOL_HEIGHT)};
  const float ACID_WAVE_SPEED  = ${f(ACID_WAVE_SPEED)};
  const float ACID_WAVE_FREQ   = ${f(ACID_WAVE_FREQ)};
  const float ACID_WAVE_AMOUNT = ${f(ACID_WAVE_AMOUNT)};
  const float ACID_SWAY_SPEED  = ${f(ACID_SWAY_SPEED)};
  const float ACID_PULSE_SPEED = ${f(ACID_PULSE_SPEED)};
  const float ACID_PULSE_DEPTH = ${f(ACID_PULSE_DEPTH)};
  const float ACID_CEIL        = ${f(LIME_PEAK_CEILING)};

  /*
   * One band of light: full strength below its crest, falling off above it over "softness". The
   * crest rides a wave, so the horizon between light and ground moves rather than sitting still.
   */
  float acidBand(vec2 p, float crest, float softness, float phase, float t) {
    float wave = sin(p.x * ACID_WAVE_FREQ + t * ACID_WAVE_SPEED * 6.2831853 + phase) * ACID_WAVE_AMOUNT;
    float above = max(0.0, p.y - (crest + wave));
    return exp(-above * above / max(softness * softness, 1e-5));
  }

  vec3 acidLimeField(vec2 uv, float aspect, float t) {
    // No flip: uv.y is already 0 along the BOTTOM edge, and the pool is a floor, not a ceiling.
    vec2 p = vec2(uv.x + sin(t * ACID_SWAY_SPEED * 6.2831853) * 0.12, uv.y);

    // Two bands at different heights and phases, so the horizon is never one clean sine.
    float low = acidBand(p, ACID_POOL_HEIGHT * 0.34, 0.17, 2.1, t);
    float high = acidBand(p, ACID_POOL_HEIGHT * 0.62, 0.26, 0.0, t);

    // Bounded well under 1 in both directions, so the breath is a change of light, not a strobe.
    float breath = 1.0 - ACID_PULSE_DEPTH * 0.5 + ACID_PULSE_DEPTH * 0.5 * sin(t * ACID_PULSE_SPEED * 6.2831853);

    float pool = clamp((low * 0.62 + high * 0.46) * breath, 0.0, 1.0);
    vec3 color = mix(ACID_BG, ACID_GREEN, pool);

    float lum = dot(color, vec3(0.2126, 0.7152, 0.0722));
    if (lum > ACID_CEIL) color *= ACID_CEIL / lum;

    // A gentle vignette, so the frame closes rather than running off its own edges.
    vec2 centred = (uv - 0.5) * vec2(aspect, 1.0);
    color *= 1.0 - 0.22 * smoothstep(0.25, 0.95, length(centred));

    return max(color, 0.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  precision highp float;

  varying vec2 vUv;

  uniform float uTime;
  uniform vec2  uResolution;

${ACID_LIME_FIELD_GLSL}

  void main() {
    float aspect = max(uResolution.x, 1.0) / max(uResolution.y, 1.0);
    gl_FragColor = vec4(acidLimeField(vUv, aspect, uTime), 1.0);
  }
`;

/* ------------------------------------------------------------------ module */

function createUniforms(): Record<string, IUniform> {
  return {
    uTime: { value: 0 },
    uResolution: { value: new Vector2(1, 1) },
  };
}

function update(
  uniforms: Record<string, IUniform>,
  frame: BackgroundFrame,
): void {
  /*
   * The dots' clock, not raw seconds.
   *
   * Transition B dissolves the dot floor into this field, and the mosaic drives BOTH of its looks
   * from `wavyDotsTime`. Running this module on its own clock would put the pool at a different
   * point in its wave on the two sides of the handover, and the crossfade would end on a step.
   *
   * It also carries reduced motion, which is why this module has no branch of its own for it:
   * `wavyDotsTime` returns a fixed pose when the reader has asked for less motion, so the field
   * simply stops on a frame. A second freeze here — at t = 0, say — would freeze the two copies
   * of the field on DIFFERENT frames, which is the one case where the seam would actually show.
   */
  uniforms.uTime.value = wavyDotsTime(frame);
  const resolution = uniforms.uResolution.value as Vector2;
  resolution.set(frame.resolution[0], frame.resolution[1]);
}

/**
 * No-WebGL / context-lost fallback: the same composition in static gradients — a near-black ground
 * with the green pooled along the bottom — so the scene still reads as itself rather than as a flat
 * panel (brief §15).
 */
function fallbackCss(): string {
  return [
    "radial-gradient(120% 46% at 50% 104%, rgba(6, 59, 0, 0.92) 0%, rgba(6, 59, 0, 0) 64%)",
    "radial-gradient(150% 62% at 38% 118%, rgba(6, 59, 0, 0.66) 0%, rgba(6, 59, 0, 0) 72%)",
    "#050604",
  ].join(", ");
}

/** The `acidLime` background mode — the Tracks ground. */
export const acidLimeShader: BackgroundShaderModule = {
  mode: "acidLime",
  vertexShader: FULLSCREEN_QUAD_VERTEX_SHADER,
  fragmentShader: FRAGMENT_SHADER,
  createUniforms,
  update,
  fallbackCss,
};
