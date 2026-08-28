/**
 * `black` — the flat black ground behind Tracks and Art Pieces.
 *
 * The plainest module that can satisfy the background contract: it paints `--drop-black` and
 * nothing else. No field, no drift, no grain, no energy.
 *
 * ## Why a mode and not "turn the canvas off"
 *
 * Brief §12/§14 fix the architecture as ONE shared canvas whose look is switched by state, and
 * the registry is exhaustive over `BackgroundMode` by construction. Expressing "no background"
 * as an absent canvas would put a second authority in charge of the ground — the canvas would
 * have to unmount and remount across these scenes, and the mode crossfade either side of them
 * would have nothing to blend against. A black module keeps one authority and makes the
 * handovers into and out of these scenes ordinary mode changes.
 *
 * ## Why it is genuinely flat
 *
 * Pure black needs no dither: banding appears in a *ramp*, and there is no ramp here. The
 * neighbouring modes each resolve to black at their boundary — the mosaic's dark beat lands on
 * it, and the footer's light horizon rises out of it — so every handover is black-to-black and
 * invisible, exactly as the mesh's `fadeToBlack` handover to `footerLight` used to be.
 *
 * Reduced motion and quality tier are irrelevant to a constant, so `update` is a no-op and the
 * module allocates no uniforms. It is a pure, GPU-cheap floor.
 */

import type { IUniform } from "three";

import { GLSL_BRAND_COLORS, type BackgroundShaderModule } from "./shader-contract";

const FRAGMENT_SHADER = /* glsl */ `
  varying vec2 vUv;

${GLSL_BRAND_COLORS}

  void main() {
    gl_FragColor = vec4(DROP_BLACK, 1.0);
  }
`;

/**
 * No uniforms. The look is a constant, so there is nothing per-mount to own and nothing for the
 * canvas to write each frame.
 */
function createUniforms(): Record<string, IUniform> {
  return {};
}

/** Nothing to advance — the field does not depend on time, scroll, pointer or quality. */
function update(): void {}

/** No-WebGL / context-lost fallback: the same flat ground, as a static CSS colour. */
function fallbackCss(): string {
  return "#000000";
}

/** The `black` background mode — Tracks and Art Pieces. */
export const blackShader: BackgroundShaderModule = {
  mode: "black",
  fragmentShader: FRAGMENT_SHADER,
  createUniforms,
  update,
  fallbackCss,
};
