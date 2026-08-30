/**
 * `offWhiteGlow` — the background behind the pinned lens thesis and the menu deck.
 *
 * Brief Section 7.2: "Minimal off-white full-screen scene … A subtle atmospheric glow grows from
 * the lower edge. Use DROP orange/purple energy rather than copying Opacity's blue exactly," and
 * "The bottom glow slowly expands and contracts with progress but never reduces text contrast."
 *
 * That last clause is the design constraint that outranks every other choice here. The glow is
 * therefore built as a *tint*, not a light: the field never leaves DROP off-white by more than
 * {@link GLOW_CEILING}, and the energy is confined to the lower part of the frame by
 * {@link LOWER_EDGE_FADE_TO}. Worst-case measured contrast of `--drop-ink` over the fully bloomed
 * glow stays far above WCAG AA — see the constant docs below. When tuning by eye, bias conservative:
 * brief Section 14 forbids "shader motion that lowers text contrast".
 *
 * The module is pure data + GLSL. It knows nothing about scenes, React, GSAP or the DOM: every
 * value it reacts to arrives on the `BackgroundFrame` the canvas hands it (scene progress comes
 * from the scene-state reducer, never from a scroll listener of its own).
 */

import { Vector2, type IUniform } from "three";

import {
  GLSL_BRAND_COLORS,
  type BackgroundFrame,
  type BackgroundShaderModule,
} from "./shader-contract";

/* ------------------------------------------------------------------ tuning */

/**
 * Hard ceiling on how far the field may be pulled away from `--drop-off-white` (#f2f2f2).
 *
 * At this blend the darkest sampled frame is roughly `rgb(215, 203, 224)` (full purple energy),
 * whose relative luminance keeps `--drop-ink` (#111111) above a 12:1 contrast ratio — comfortably
 * clear of the 4.5:1 AA floor, with headroom for the grain term. Raising it is a contrast
 * regression, not a style choice.
 */
const GLOW_CEILING = 0.16;

/** Above this height the glow has fully faded out, so centred display type sits over clean paper. */
const LOWER_EDGE_FADE_TO = 0.54;

/** Radius of the bloom at rest, in aspect-corrected screen units. */
const BLOOM_BASE = 0.42;
/** How much of the bloom radius is driven by scene progress (expand, then contract). */
const BLOOM_FROM_PROGRESS = 0.34;
/** Ambient breathing amplitude — keeps the field alive with no pointer and no scroll. */
const BLOOM_FROM_TIME = 0.06;

/** Horizontal pointer nudge, in screen units. Desktop enhancement only; never required. */
const POINTER_SHIFT = 0.05;

/* ------------------------------------------------------------------- glsl */

const FRAGMENT_SHADER = /* glsl */ `
  varying vec2 vUv;

  uniform float uTime;
  uniform float uProgress;
  uniform vec2  uResolution;
  uniform vec2  uPointer;
  uniform float uPointerAmount;
  uniform float uReducedMotion;
  uniform float uGrain;

${GLSL_BRAND_COLORS}

  const float PI = 3.141592653589793;
  const float GLOW_CEILING = ${GLOW_CEILING.toFixed(3)};
  const float LOWER_EDGE_FADE_TO = ${LOWER_EDGE_FADE_TO.toFixed(3)};
  const float BLOOM_BASE = ${BLOOM_BASE.toFixed(3)};
  const float BLOOM_FROM_PROGRESS = ${BLOOM_FROM_PROGRESS.toFixed(3)};
  const float BLOOM_FROM_TIME = ${BLOOM_FROM_TIME.toFixed(3)};
  const float POINTER_SHIFT = ${POINTER_SHIFT.toFixed(3)};

  float hash21(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  void main() {
    float aspect = max(uResolution.x, 1.0) / max(uResolution.y, 1.0);

    // Expand, then contract: sin() over the scene's 0..1 progress peaks in the middle of the
    // thesis and returns the field to rest at both ends, so reverse scroll mirrors exactly.
    float breath = sin(clamp(uProgress, 0.0, 1.0) * PI);
    float drift = uReducedMotion > 0.5 ? 0.0 : (sin(uTime * 0.17) * 0.5 + 0.5);
    float bloom = BLOOM_BASE + BLOOM_FROM_PROGRESS * breath + BLOOM_FROM_TIME * drift;

    float centreX = 0.5 + uPointer.x * POINTER_SHIFT * uPointerAmount;

    // Distance from a source sitting just under the lower edge of the frame.
    vec2 q = vec2((vUv.x - centreX) * aspect, vUv.y + 0.06);
    float r = length(q / vec2(1.35, 1.0));
    float glow = pow(1.0 - smoothstep(0.0, bloom, r), 1.6);

    // Keep the energy low in the frame -- display type lives in the middle band.
    glow *= 1.0 - smoothstep(0.0, LOWER_EDGE_FADE_TO, vUv.y);

    // Orange at the floor easing into purple as the glow climbs: DROP energy, not Opacity blue.
    vec3 energy = mix(DROP_ORANGE, DROP_PURPLE, smoothstep(0.01, 0.30, vUv.y));

    vec3 color = mix(DROP_OFF_WHITE, energy, glow * GLOW_CEILING);

    // Static, extremely low-amplitude grain: breaks up banding in the bloom without strobing.
    float grain = (hash21(floor(gl_FragCoord.xy)) - 0.5) * 0.008 * uGrain;
    color += grain;

    gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
  }
`;

/* ------------------------------------------------------------------ module */

function createUniforms(): Record<string, IUniform> {
  return {
    uTime: { value: 0 },
    uProgress: { value: 0 },
    uResolution: { value: new Vector2(1, 1) },
    uPointer: { value: new Vector2(0, 0) },
    uPointerAmount: { value: 0 },
    uReducedMotion: { value: 0 },
    uGrain: { value: 0 },
  };
}

function update(uniforms: Record<string, IUniform>, frame: BackgroundFrame): void {
  const detail = frame.quality.shaderDetail;

  uniforms.uTime.value = frame.timeSeconds;
  uniforms.uProgress.value = frame.sceneProgress;
  uniforms.uReducedMotion.value = frame.reducedMotion ? 1 : 0;
  uniforms.uGrain.value = detail.grain ? 1 : 0;
  uniforms.uPointerAmount.value = detail.pointerResponse && !frame.reducedMotion ? 1 : 0;

  const resolution = uniforms.uResolution.value as Vector2;
  resolution.set(frame.resolution[0], frame.resolution[1]);

  const pointer = uniforms.uPointer.value as Vector2;
  pointer.set(frame.pointer[0], frame.pointer[1]);
}

/**
 * No-WebGL / context-lost fallback. Same composition as the shader — DROP off-white paper with a
 * restrained orange-into-purple bloom hugging the lower edge — expressed as a static CSS
 * background so the scene degrades to something styled rather than blank (brief Section 15).
 */
function fallbackCss(
  frame?: Pick<BackgroundFrame, "transitionState" | "sceneProgress">,
): string {
  const progress = Math.min(Math.max(frame?.sceneProgress ?? 0, 0), 1);
  const breath = Math.sin(progress * Math.PI);
  const spread = Math.round(88 + 34 * breath);
  const height = Math.round(46 + 16 * breath);

  return [
    `radial-gradient(${spread}% ${height}% at 50% 104%,`,
    ` rgba(255, 90, 0, 0.14) 0%,`,
    ` rgba(72, 0, 130, 0.09) 46%,`,
    ` rgba(242, 242, 242, 0) 74%)`,
    `, #f2f2f2`,
  ].join("");
}

/** The `offWhiteGlow` background mode (brief Section 7.2). */
export const offWhiteGlowShader: BackgroundShaderModule = {
  mode: "offWhiteGlow",
  fragmentShader: FRAGMENT_SHADER,
  createUniforms,
  update,
  fallbackCss,
};

/** Ceiling on the glow's departure from off-white — exported so contrast QA can cite it. */
export const OFF_WHITE_GLOW_CEILING = GLOW_CEILING;
