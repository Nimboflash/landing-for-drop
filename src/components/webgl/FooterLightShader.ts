/**
 * Prismatic light horizon — the `footerLight` background mode (brief Section 7.10, ticket 14).
 *
 * A real-time GLSL effect, never a screenshot, GIF, or pre-rendered video. A bright white core
 * band with a blue/cyan edge and restrained orange/purple spectral fringes curves and drifts
 * across the lower half of the frame like a living horizon or a refraction, carrying a broad
 * bloom that reads as illuminating whatever crosses it.
 *
 * The giant outline DROP wordmark is DOM/SVG owned by the footer scene and sits ABOVE this
 * canvas — this module draws only the light and its bloom.
 *
 * ## What drives it
 *
 * - `frame.transitionState.footerReveal` (0..1, from the reducer) drives the main reveal and the
 *   band's vertical drift. It is the only scroll input; reverse scroll re-emits the same value
 *   and {@link footerLightUniforms} is pure, so the reveal is exactly reversible.
 * - The module's own continuously integrated clock keeps the horizon alive with no input at all.
 * - `frame.pointer` adds a subtle LOCAL bump, gated on the tier's `pointerResponse` (desktop
 *   only) — it modulates the effect, it is never required by it.
 * - Reduced motion stops the clock and drops the fine harmonics, leaving a static blurred
 *   gradient ribbon; `fallbackCss` ships the same ribbon in CSS for the no-WebGL path.
 *
 * Only the pure, GPU-free helpers below are unit-tested; canvas pixels are never asserted and
 * uniform values are never read back out of a material.
 */

import type { IUniform } from "three";

import type { QualityTierSettings } from "@/lib/performance/quality-tier";

import { GLSL_BRAND_COLORS } from "./shader-contract";
import type { BackgroundFrame, BackgroundShaderModule } from "./shader-contract";

/* ------------------------------------------------------------- geometry */

/**
 * Where the band sits, in UV-y (0 = bottom of the frame, 1 = top). Both values stay in the lower
 * half of the frame, per the brief. Tuned by feel against the supplied reference frame.
 */
const HORIZON_ENTRY_Y = 0.06;
const HORIZON_SETTLED_Y = 0.38;

/** Faint glow already present at reveal 0, so the light rises into frame instead of switching on. */
const CORE_INTENSITY_MIN = 0.05;
const CORE_INTENSITY_MAX = 1;
const BLOOM_MIN = 0.06;
const BLOOM_MAX = 0.85;

/**
 * Spectral fringe amount. Restrained on purpose: brief Section 4 keeps orange and purple as
 * atmospheric energy only, never a large generic fill.
 */
const FRINGE_MIN = 0.04;
const FRINGE_MAX = 0.22;

/** Half-width of the white core in UV-y at full reveal. */
const CORE_WIDTH = 0.006;

/** Overall descent from left to right, in UV-y. */
const HORIZON_TILT = -0.16;

/** Reveal used by the static fallback when no frame is supplied — the settled ribbon. */
const FALLBACK_DEFAULT_REVEAL = 1;

/* ------------------------------------------------------------- settings */

export type FooterLightSettings = {
  /** The clamped reveal the rest of the values were derived from. */
  reveal: number;
  /** Brightness of the white core and its cyan edge. */
  coreIntensity: number;
  /** Broad blue bloom around the band — what makes the outline read as illuminated. */
  bloom: number;
  /** Orange/purple spectral fringe amount. */
  fringe: number;
  /** Band centre in UV-y (0 = bottom). Drifts upward as the reveal advances. */
  horizonY: number;
  /** Pointer x in UV space, 0..1. Centred when there is no pointer. */
  pointerX: number;
  /** Pointer y as a signed push, -1..1. Zero when there is no pointer. */
  pointerY: number;
  /** 0 whenever there is no usable pointer — the effect must be complete at this value. */
  pointerStrength: number;
};

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

function clampSigned(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < -1) return -1;
  if (value > 1) return 1;
  return value;
}

function mix(from: number, to: number, t: number): number {
  return from + (to - from) * t;
}

/** Smoothstep: the light arrives and settles without a jolt at either end of the reveal. */
function ease(value: number): number {
  const t = clamp01(value);
  return t * t * (3 - 2 * t);
}

/**
 * Everything the horizon needs for one frame, derived from the reducer's `footerReveal` and the
 * (optional) pointer. Pure: the same inputs always yield the same settings, so reverse scroll
 * restores the same light.
 *
 * Pass `null` for the pointer on touch devices, on tiers without pointer response, and under
 * reduced motion. Every returned value except the three pointer fields is identical with and
 * without a pointer — that is the "stays alive without pointer input" requirement expressed as
 * a property rather than a hope.
 */
export function footerLightUniforms(
  reveal: number,
  pointer?: readonly [number, number] | null,
): FooterLightSettings {
  const clampedReveal = clamp01(reveal);
  const t = ease(clampedReveal);

  const usablePointer =
    pointer != null && Number.isFinite(pointer[0]) && Number.isFinite(pointer[1]) ? pointer : null;

  return {
    reveal: clampedReveal,
    coreIntensity: mix(CORE_INTENSITY_MIN, CORE_INTENSITY_MAX, t),
    bloom: mix(BLOOM_MIN, BLOOM_MAX, t),
    fringe: mix(FRINGE_MIN, FRINGE_MAX, t),
    horizonY: mix(HORIZON_ENTRY_Y, HORIZON_SETTLED_Y, t),
    // Pointer x arrives as -1..1 across the canvas; the shader wants the same 0..1 space as UV.
    pointerX: usablePointer ? clamp01(clampSigned(usablePointer[0]) * 0.5 + 0.5) : 0.5,
    pointerY: usablePointer ? clampSigned(usablePointer[1]) : 0,
    pointerStrength: usablePointer ? 1 : 0,
  };
}

/* --------------------------------------------------------- quality tiers */

export type FooterLightDetailSettings = {
  /** Harmonics on the horizon curve: 2 = full living refraction, 0 = a plain static ribbon. */
  harmonics: number;
  /** Dither amplitude — a dark gradient this wide bands badly on 8-bit displays without it. */
  grain: number;
};

const FOOTER_GRAIN_AMPLITUDE = 0.008;
const REFERENCE_MESH_SUBDIVISION = 128;

/**
 * Brief Section 14 detail reduction, read from the tier's settings rather than re-derived.
 * Reduced motion collapses the curve to its base shape — the static ribbon the brief asks for.
 */
export function footerLightDetailUniforms(
  quality: QualityTierSettings,
  reducedMotion: boolean,
): FooterLightDetailSettings {
  if (reducedMotion) {
    return { harmonics: 0, grain: quality.shaderDetail.grain ? FOOTER_GRAIN_AMPLITUDE : 0 };
  }
  const detail = clamp01(quality.shaderDetail.meshSubdivision / REFERENCE_MESH_SUBDIVISION);
  const harmonics = detail >= 1 ? 2 : 1;
  const grain = quality.shaderDetail.grain ? FOOTER_GRAIN_AMPLITUDE * (0.5 + 0.5 * detail) : 0;
  return { harmonics, grain };
}

/* ------------------------------------------------------------ light clock */

/**
 * The horizon's own clock. Like the mesh clock, the rate is scaled and the value is only ever
 * integrated forward, so stopping for reduced motion holds the ribbon still instead of cutting
 * it back to a different frame.
 */
export type FooterLightClock = {
  lightTime: number;
  sourceSeconds: number;
};

export const FOOTER_CLOCK_ORIGIN = 61.25;

const MAX_FRAME_SECONDS = 1 / 12;

export function createFooterLightClock(sourceSeconds = 0): FooterLightClock {
  return {
    lightTime: FOOTER_CLOCK_ORIGIN,
    sourceSeconds: Number.isFinite(sourceSeconds) ? sourceSeconds : 0,
  };
}

export function advanceFooterLightClock(
  clock: FooterLightClock,
  sourceSeconds: number,
  speedScale: number,
): FooterLightClock {
  const now = Number.isFinite(sourceSeconds) ? sourceSeconds : clock.sourceSeconds;
  const rawDelta = now - clock.sourceSeconds;
  const delta = rawDelta > 0 ? Math.min(rawDelta, MAX_FRAME_SECONDS) : 0;
  const rate = Number.isFinite(speedScale) && speedScale > 0 ? speedScale : 0;
  return { lightTime: clock.lightTime + delta * rate, sourceSeconds: now };
}

function isFooterLightClock(value: unknown): value is FooterLightClock {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<FooterLightClock>;
  return (
    typeof candidate.lightTime === "number" &&
    Number.isFinite(candidate.lightTime) &&
    typeof candidate.sourceSeconds === "number" &&
    Number.isFinite(candidate.sourceSeconds)
  );
}

/* ------------------------------------------------------------------- GLSL */

/**
 * The band is built from one signed distance to a drifting curve, sampled at four slightly
 * different offsets — one per spectral component. That offset IS the refraction: the white core
 * sits on the curve, the blue/cyan edge rides just above it, and the orange and purple fringes
 * trail just below, strongest where the curve bends hardest.
 */
const FOOTER_LIGHT_FRAGMENT_SHADER = /* glsl */ `
  varying vec2 vUv;

  uniform vec2 uResolution;
  // The clock accumulates for as long as the page is open; mediump would judder it.
  uniform highp float uTime;
  uniform float uCoreIntensity;
  uniform float uBloom;
  uniform float uFringe;
  uniform float uHorizonY;
  uniform float uCoreWidth;
  uniform float uTilt;
  uniform vec2 uPointer;
  uniform float uPointerStrength;
  uniform float uHarmonics;
  uniform float uGrain;
  // Output alpha. The shared canvas crossfades with a constant blend alpha, so this stays 1;
  // it exists so a consumer that needs per-module opacity has a handle without a fork.
  uniform float uOpacity;

${GLSL_BRAND_COLORS}

  const vec3 HORIZON_CYAN = vec3(0.42, 0.72, 1.0);
  const vec3 HORIZON_BLUE = vec3(0.16, 0.38, 0.92);

  float gauss(float x) {
    return exp(-x * x);
  }

  // Hash without sine (Dave Hoskins). The cheaper fract(p.x * p.y) variants have degenerate
  // columns that read as a hairline seam across a gradient this smooth.
  float hash21(vec2 p) {
    vec3 q = fract(vec3(p.xyx) * 0.1031);
    q += dot(q, q.yzx + 33.33);
    return fract((q.x + q.y) * q.z);
  }

  /** Band centre at horizontal position x (0..1), in UV-y. */
  float horizonAt(float x, float aspect) {
    float ax = (x - 0.5) * aspect;
    float y = uHorizonY;
    y += uTilt * (x - 0.5);
    y += 0.055 * sin(ax * 2.15 + uTime * 0.19);
    if (uHarmonics > 0.5) {
      y += 0.026 * sin(ax * 3.70 - uTime * 0.14 + 1.7);
    }
    if (uHarmonics > 1.5) {
      y += 0.011 * sin(ax * 7.10 + uTime * 0.11 + 0.6);
    }
    float pd = (x - uPointer.x) * 7.0;
    y += uPointerStrength * 0.05 * uPointer.y * gauss(pd);
    return y;
  }

  void main() {
    vec2 p = vUv;
    float aspect = uResolution.x / max(uResolution.y, 1.0);

    float d = p.y - horizonAt(p.x, aspect);

    // The beam converges toward the right the way the reference frame does.
    float w = max(uCoreWidth * mix(1.45, 0.55, p.x), 0.0005);

    // The core is a hard white centre inside a softer white shoulder, so it clips to white
    // instead of reading as a blue line with a pale middle.
    float core = gauss(d / w) + 0.62 * gauss(d / (w * 2.1));
    float edge = gauss((d - w * 1.30) / (w * 3.6));
    float warm = gauss((d + w * 2.20) / (w * 1.6));
    float violet = gauss((d + w * 4.20) / (w * 2.6));

    float q = d / (w * 8.0);
    float halo = 1.0 / (1.0 + q * q);
    // Light scatters upward and is nearly absent below the band — that dark underside is what
    // leaves room for the warm and violet fringes to read at all.
    float upward = smoothstep(-w * 3.0, w * 3.0, d);
    float bloom = halo * mix(0.10, 1.0, upward);

    // Fringes belong to the bends: this is refraction, not a permanent rainbow.
    float slope = abs(horizonAt(p.x + 0.02, aspect) - horizonAt(p.x - 0.02, aspect)) * 14.0;
    float bend = clamp(0.45 + slope, 0.0, 1.0);

    vec3 color = vec3(0.0);
    color += DROP_WHITE * (core * uCoreIntensity);
    color += HORIZON_CYAN * (edge * 0.52 * uCoreIntensity);
    color += HORIZON_BLUE * (bloom * uBloom);
    color += DROP_ORANGE * (warm * uFringe * bend * 3.2);
    color += DROP_PURPLE * (violet * uFringe * bend * 2.0);

    // A trace of scattered light pooling along the bottom edge.
    color += HORIZON_BLUE * (0.05 * uBloom * (1.0 - smoothstep(0.0, 0.75, p.y)));

    if (uGrain > 0.0) {
      float g = hash21(gl_FragCoord.xy + floor(uTime * 24.0)) - 0.5;
      color += g * uGrain;
    }

    gl_FragColor = vec4(max(color, 0.0), uOpacity);
  }
`;

/* --------------------------------------------------------------- fallback */

function alpha(value: number): number {
  return Number(Math.max(0, Math.min(1, value)).toFixed(3));
}

function percentFromTop(uvY: number, offset = 0): string {
  const value = (1 - Math.max(0, Math.min(1, uvY))) * 100 + offset;
  return `${Number(value.toFixed(2))}%`;
}

/**
 * The no-WebGL / reduced-motion CSS ribbon: the same white core, cyan edge, blue bloom, and
 * restrained warm and violet fringes, stacked as static blurred gradients on black. Returns a
 * value for the CSS `background` shorthand.
 */
export function footerLightFallbackCss(settings: FooterLightSettings): string {
  const core = settings.coreIntensity;
  const layers = [
    `radial-gradient(150% 2.2% at 50% ${percentFromTop(settings.horizonY)}, rgba(255, 255, 250, ${alpha(
      core,
    )}) 0%, rgba(255, 255, 250, 0) 100%)`,
    `radial-gradient(150% 9% at 50% ${percentFromTop(settings.horizonY, -1.6)}, rgba(107, 184, 255, ${alpha(
      core * 0.55,
    )}) 0%, rgba(107, 184, 255, 0) 100%)`,
    `radial-gradient(120% 4% at 42% ${percentFromTop(settings.horizonY, 1.8)}, rgba(255, 90, 0, ${alpha(
      settings.fringe,
    )}) 0%, rgba(255, 90, 0, 0) 100%)`,
    `radial-gradient(130% 7% at 58% ${percentFromTop(settings.horizonY, 3.4)}, rgba(72, 0, 130, ${alpha(
      settings.fringe * 0.8,
    )}) 0%, rgba(72, 0, 130, 0) 100%)`,
    `radial-gradient(170% 46% at 50% ${percentFromTop(settings.horizonY)}, rgba(41, 97, 235, ${alpha(
      settings.bloom * 0.42,
    )}) 0%, rgba(41, 97, 235, 0) 72%)`,
    "#000000",
  ];
  return layers.join(", ");
}

/* ----------------------------------------------------------------- module */

/** CPU-side bookkeeping carried alongside the GL uniforms; no GLSL uniform matches this key. */
const FOOTER_CLOCK_KEY = "footerLightClock";

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

export const footerLightShader: BackgroundShaderModule = {
  mode: "footerLight",
  fragmentShader: FOOTER_LIGHT_FRAGMENT_SHADER,

  createUniforms(): Record<string, IUniform> {
    const initial = footerLightUniforms(0, null);
    return {
      uResolution: { value: [1, 1] },
      uTime: { value: FOOTER_CLOCK_ORIGIN },
      uCoreIntensity: { value: initial.coreIntensity },
      uBloom: { value: initial.bloom },
      uFringe: { value: initial.fringe },
      uHorizonY: { value: initial.horizonY },
      uCoreWidth: { value: CORE_WIDTH },
      uTilt: { value: HORIZON_TILT },
      uPointer: { value: [initial.pointerX, initial.pointerY] },
      uPointerStrength: { value: initial.pointerStrength },
      uHarmonics: { value: 0 },
      uGrain: { value: 0 },
      uOpacity: { value: 1 },
      [FOOTER_CLOCK_KEY]: { value: createFooterLightClock() },
    };
  },

  update(uniforms: Record<string, IUniform>, frame: BackgroundFrame): void {
    // Pointer distortion is a desktop enhancement: off under reduced motion and on any tier
    // without pointer response. The horizon's own clock keeps it alive either way.
    const pointerEnabled = frame.quality.shaderDetail.pointerResponse && !frame.reducedMotion;
    const settings = footerLightUniforms(
      frame.transitionState?.footerReveal ?? 0,
      pointerEnabled ? frame.pointer : null,
    );
    const detail = footerLightDetailUniforms(frame.quality, frame.reducedMotion);

    const clockEntry = uniforms[FOOTER_CLOCK_KEY];
    const previous = isFooterLightClock(clockEntry?.value)
      ? clockEntry.value
      : createFooterLightClock();
    const next = advanceFooterLightClock(previous, frame.timeSeconds, frame.reducedMotion ? 0 : 1);
    if (clockEntry) clockEntry.value = next;

    setNumber(uniforms, "uTime", next.lightTime);
    setNumber(uniforms, "uCoreIntensity", settings.coreIntensity);
    setNumber(uniforms, "uBloom", settings.bloom);
    setNumber(uniforms, "uFringe", settings.fringe);
    setNumber(uniforms, "uHorizonY", settings.horizonY);
    setNumber(uniforms, "uPointerStrength", settings.pointerStrength);
    setNumber(uniforms, "uHarmonics", detail.harmonics);
    setNumber(uniforms, "uGrain", detail.grain);
    setVec2(uniforms, "uPointer", settings.pointerX, settings.pointerY);
    setVec2(uniforms, "uResolution", frame.resolution[0], frame.resolution[1]);
  },

  fallbackCss(frame?: Pick<BackgroundFrame, "transitionState" | "sceneProgress">): string {
    const reveal = frame?.transitionState?.footerReveal ?? FALLBACK_DEFAULT_REVEAL;
    return footerLightFallbackCss(footerLightUniforms(reveal, null));
  },
};
