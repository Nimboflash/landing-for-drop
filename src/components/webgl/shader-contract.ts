/**
 * Background shader contract.
 *
 * Brief §12/§14: ONE shared, fixed WebGL canvas. Background scenes are switched by uniforms and
 * state — never by stacking canvases. Every mode is a `BackgroundShaderModule` registered against
 * the `BackgroundMode` union; `BackgroundCanvas` owns the single context and drives them.
 *
 * The loader (ticket 05) is the one sanctioned exception: it renders on its own temporary overlay
 * canvas above the DOM and disposes after the portal completes. It does NOT implement this contract.
 */

import type { IUniform } from "three";
import type { BackgroundMode, TransitionState } from "@/lib/scene";
import type { QualityTierSettings } from "@/lib/performance/quality-tier";

/**
 * Everything a background shader is allowed to know on a given frame. It comes from the scene-state
 * reducer plus frame-local values — a shader NEVER computes scene, mode, or index state itself.
 */
export type BackgroundFrame = {
  /** Active mode from the reducer. A module only runs while this equals its own `mode`. */
  mode: BackgroundMode;
  /** Progress within the active scene, 0..1, from the reducer. */
  sceneProgress: number;
  /** Declarative descriptors: pixel {seed, progress}, mesh variant, footer reveal, etc. */
  transitionState: TransitionState;
  /** When true: static background, brief crossfades only. Mandatory, not optional. */
  reducedMotion: boolean;
  /** DPR caps and shader-detail knobs for the detected tier. */
  quality: QualityTierSettings;
  /** Seconds since canvas mount. Drives ambient motion that must stay alive without input. */
  timeSeconds: number;
  /** Canvas drawing-buffer size in CSS pixels: [width, height]. */
  resolution: readonly [number, number];
  /** Normalized pointer position, [-1..1, -1..1]. Desktop enhancement only; never required. */
  pointer: readonly [number, number];
};

/**
 * A single background mode's GLSL and uniform plumbing.
 *
 * Modules are pure and side-effect free apart from mutating the uniform objects they created.
 * They must not import React, GSAP, or the DOM.
 */
export type BackgroundShaderModule = {
  /** The `BackgroundMode` this module renders. Used as its registry key. */
  mode: BackgroundMode;
  /** Optional override; defaults to `FULLSCREEN_QUAD_VERTEX_SHADER`. */
  vertexShader?: string;
  fragmentShader: string;
  /** Fresh uniform objects per canvas mount, so nothing leaks between mounts. */
  createUniforms(): Record<string, IUniform>;
  /** Called once per frame while this mode is active (or crossfading). Mutates uniforms in place. */
  update(uniforms: Record<string, IUniform>, frame: BackgroundFrame): void;
  /**
   * Static CSS background for the no-WebGL / context-lost fallback. The page must degrade to a
   * styled static background, never a blank or broken page (brief §15, ticket 04).
   */
  fallbackCss(frame?: Pick<BackgroundFrame, "transitionState" | "sceneProgress">): string;
  /** Release any module-owned GPU resources (textures/render targets). Uniforms are freed by the canvas. */
  dispose?(uniforms: Record<string, IUniform>): void;
};

/** Standard fullscreen-quad vertex shader. Modes are screen-space effects on one plane. */
export const FULLSCREEN_QUAD_VERTEX_SHADER = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

/**
 * Brand tokens for GLSL, mirroring brief §4. Keep in sync with src/app/globals.css.
 * Shaders must not invent colors: black/off-white is the base; orange/purple appear only as
 * atmospheric energy (glow, pixel energy, prismatic fringes), never as large generic fills.
 */
export const GLSL_BRAND_COLORS = /* glsl */ `
  const vec3 DROP_BLACK      = vec3(0.0, 0.0, 0.0);
  const vec3 DROP_INK        = vec3(0.06666, 0.06666, 0.06666);
  const vec3 DROP_WHITE      = vec3(1.0, 1.0, 0.99608);
  const vec3 DROP_OFF_WHITE  = vec3(0.94902, 0.94902, 0.94902);
  const vec3 DROP_GRAY       = vec3(0.51373, 0.51373, 0.51373);
  const vec3 DROP_ORANGE     = vec3(1.0, 0.35294, 0.0);
  const vec3 DROP_PURPLE     = vec3(0.28235, 0.0, 0.50980);
  const vec3 DROP_GRID_GREEN = vec3(0.06275, 0.16863, 0.09804);
  const vec3 DROP_GRID_LINE  = vec3(0.14118, 0.32157, 0.21176);
`;

/**
 * Grid cell size in CSS pixels for the dark-green grid. Pixel transition A must align its mosaic
 * cells to exactly this lattice (brief §7.5: "Pixel dimensions align with the existing background
 * grid"), and transition B reuses the same coordinates (brief §7.7).
 */
export const GRID_CELL_PX = 64;
