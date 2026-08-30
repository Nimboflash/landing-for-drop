/**
 * The shared WebGL background.
 *
 * One fixed canvas, one context, seven modes (brief Sections 12 and 14). Import the canvas and the
 * registry from here; import an individual shader module directly only when a scene genuinely needs
 * that module's own exports (the grid lattice, for instance).
 *
 * `shader-contract.ts` is the frozen interface every mode implements — background modules added
 * later register themselves in `shader-registry.ts` and nothing else changes.
 */

export { BackgroundCanvas, type BackgroundCanvasProps } from "./BackgroundCanvas";

export {
  BACKGROUND_MODES,
  BACKGROUND_SHADERS,
  backgroundShaderFor,
} from "./shader-registry";

export {
  FULLSCREEN_QUAD_VERTEX_SHADER,
  GLSL_BRAND_COLORS,
  GRID_CELL_PX,
  type BackgroundFrame,
  type BackgroundShaderModule,
} from "./shader-contract";

export { offWhiteGlowShader, OFF_WHITE_GLOW_CEILING } from "./OffWhiteGlowShader";

export {
  greenGridShader,
  greenGridLattice,
  GREEN_GRID_CELL_PX,
  type GreenGridLattice,
} from "./GreenGridShader";
