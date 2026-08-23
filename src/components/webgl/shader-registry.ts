/**
 * The background-mode → shader-module registry.
 *
 * Brief Section 14 fixes the seven `BackgroundMode` values the shared canvas can be in. This file is
 * the single place each of them is bound to the GLSL that renders it, so `BackgroundCanvas` never
 * branches on the mode itself — it looks the module up and drives it through the
 * `BackgroundShaderModule` contract.
 *
 * {@link BACKGROUND_SHADERS} is declared `satisfies Readonly<Record<BackgroundMode, …>>`: adding a
 * mode to the union without registering a module is a **compile error**, not a blank screen at
 * runtime. Removing a key, or registering a module whose own `mode` disagrees with its key, fails
 * the same way (the latter is also asserted at the unit seam).
 */

import type { BackgroundMode } from "@/lib/scene";

import { footerLightShader } from "./FooterLightShader";
import { greenGridShader } from "./GreenGridShader";
import { monoMeshShader } from "./MonochromeMeshShader";
import { offWhiteGlowShader } from "./OffWhiteGlowShader";
import { pixelAShader, pixelBShader } from "./PixelMosaicShader";
import { wavyDotsShader } from "./WavyDotsShader";
import type { BackgroundShaderModule } from "./shader-contract";

/**
 * Every background mode and the module that renders it.
 *
 * Keys are listed in brief Section 6 scene order rather than alphabetically, so the table reads as
 * the journey: thesis paper → grid statement → pixel A → films → pixel B → tracks/art → footer.
 */
export const BACKGROUND_SHADERS = {
  offWhiteGlow: offWhiteGlowShader,
  greenGrid: greenGridShader,
  pixelA: pixelAShader,
  wavyDots: wavyDotsShader,
  pixelB: pixelBShader,
  monoMesh: monoMeshShader,
  footerLight: footerLightShader,
} as const satisfies Readonly<Record<BackgroundMode, BackgroundShaderModule>>;

/** Registered modes, in brief Section 6 scene order. */
export const BACKGROUND_MODES = Object.keys(BACKGROUND_SHADERS) as readonly BackgroundMode[];

/**
 * The module for a mode. Total by construction — the registry is exhaustive over `BackgroundMode`,
 * so this never returns `undefined` and callers need no fallback branch.
 */
export function backgroundShaderFor(mode: BackgroundMode): BackgroundShaderModule {
  return BACKGROUND_SHADERS[mode];
}
