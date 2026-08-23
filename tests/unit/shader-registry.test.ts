/**
 * Unit seam for the shared background canvas (ticket 04).
 *
 * The registry and the shader modules are tested AS DATA. Nothing here touches a GPU, a material,
 * or a uniform's value: the canvas owns those, and BUILD-GUIDE is explicit that "WebGL pixels are
 * never asserted" and that reaching into materials for uniform values is not a seam.
 *
 * What is worth proving mechanically is the part that fails silently in production — a mode with no
 * module (blank screen), a module filed under the wrong key (wrong background for a scene), a
 * fallback that returns nothing (blank page with WebGL disabled), uniforms shared between mounts
 * (state leaking across a route change), or an `update` that throws at an endpoint of the scroll.
 *
 * Expected values come from the brief and from the seed lens, never from re-running the
 * implementation's own arithmetic.
 */

import { describe, expect, it } from "vitest";

import { beautifulImperfectionLens } from "@/content";
import { QUALITY_TIER_SETTINGS } from "@/lib/performance/quality-tier";
import {
  SCENE_BACKGROUND_MODE,
  SCENE_ORDER,
  createInitialSceneState,
  lensCounts,
  sceneStateReducer,
  type BackgroundMode,
  type SceneId,
  type SceneState,
} from "@/lib/scene";
import {
  GREEN_GRID_CELL_PX,
  greenGridLattice,
} from "@/components/webgl/GreenGridShader";
import {
  GRID_CELL_PX,
  type BackgroundFrame,
} from "@/components/webgl/shader-contract";
import {
  BACKGROUND_MODES,
  BACKGROUND_SHADERS,
  backgroundShaderFor,
} from "@/components/webgl/shader-registry";

/**
 * The seven modes of brief Section 14 ("Shared canvas state"), transcribed. This list is the spec —
 * it is deliberately NOT derived from the registry, so a mode that quietly disappears from the
 * implementation fails a test instead of passing one.
 */
const BRIEF_BACKGROUND_MODES = [
  "offWhiteGlow",
  "greenGrid",
  "pixelA",
  "wavyDots",
  "pixelB",
  "monoMesh",
  "footerLight",
] as const satisfies readonly BackgroundMode[];

const COUNTS = lensCounts(beautifulImperfectionLens);

/** The first scene the brief maps to a given mode — the state the canvas will actually see. */
function sceneForMode(mode: BackgroundMode): SceneId {
  const scene = SCENE_ORDER.find(
    (candidate) => SCENE_BACKGROUND_MODE[candidate] === mode && candidate !== "loader",
  );
  if (scene === undefined) throw new Error(`no scene maps to background mode "${mode}"`);
  return scene;
}

/** Real reducer output for a mode at a given scroll position — no hand-written descriptors. */
function stateForMode(mode: BackgroundMode, progress: number): SceneState {
  return sceneStateReducer(
    createInitialSceneState(COUNTS),
    { type: "scrollProgress", sceneId: sceneForMode(mode), progress },
    COUNTS,
  );
}

type FrameOptions = {
  progress: number;
  reducedMotion: boolean;
  tier: "high" | "medium" | "low";
};

function frameForMode(mode: BackgroundMode, options: FrameOptions): BackgroundFrame {
  const state = stateForMode(mode, options.progress);
  return {
    mode,
    sceneProgress: state.sceneProgress,
    transitionState: state.transitionState,
    reducedMotion: options.reducedMotion,
    quality: QUALITY_TIER_SETTINGS[options.tier],
    timeSeconds: 12.5,
    // Brief Section 21 QA matrix: the desktop viewport.
    resolution: [1440, 900],
    pointer: [0.42, -0.18],
  };
}

/** Every combination the canvas can hand a module at the extremes of a scene. */
const FRAME_CASES: readonly FrameOptions[] = [
  { progress: 0, reducedMotion: false, tier: "high" },
  { progress: 1, reducedMotion: false, tier: "high" },
  { progress: 0.5, reducedMotion: false, tier: "medium" },
  { progress: 0, reducedMotion: true, tier: "low" },
  { progress: 1, reducedMotion: true, tier: "low" },
];

describe("background shader registry", () => {
  it("registers a module for every background mode in the brief", () => {
    for (const mode of BRIEF_BACKGROUND_MODES) {
      expect(BACKGROUND_SHADERS[mode], `no module registered for "${mode}"`).toBeDefined();
    }
    expect([...BACKGROUND_MODES].sort()).toEqual([...BRIEF_BACKGROUND_MODES].sort());
  });

  it("files each module under its own mode", () => {
    for (const mode of BRIEF_BACKGROUND_MODES) {
      expect(backgroundShaderFor(mode).mode).toBe(mode);
    }
  });

  it("covers every mode the scene map can put the canvas in", () => {
    const modesTheReducerEmits = new Set(Object.values(SCENE_BACKGROUND_MODE));
    for (const mode of modesTheReducerEmits) {
      expect(BACKGROUND_SHADERS[mode], `scene map emits unregistered mode "${mode}"`).toBeDefined();
    }
  });
});

describe("background shader modules", () => {
  it("every mode ships a non-empty fragment shader", () => {
    for (const mode of BRIEF_BACKGROUND_MODES) {
      const shaderModule = backgroundShaderFor(mode);
      expect(shaderModule.fragmentShader.trim().length, `"${mode}" has no fragment shader`)
        .toBeGreaterThan(0);
      expect(shaderModule.fragmentShader).toContain("void main");
      if (shaderModule.vertexShader !== undefined) {
        expect(shaderModule.vertexShader.trim().length).toBeGreaterThan(0);
      }
    }
  });

  it("every mode has a real no-WebGL fallback background", () => {
    for (const mode of BRIEF_BACKGROUND_MODES) {
      const shaderModule = backgroundShaderFor(mode);

      expect(shaderModule.fallbackCss().trim().length, `"${mode}" has no fallback`)
        .toBeGreaterThan(0);

      for (const options of FRAME_CASES) {
        const frame = frameForMode(mode, options);
        const css = shaderModule.fallbackCss({
          transitionState: frame.transitionState,
          sceneProgress: frame.sceneProgress,
        });
        expect(css.trim().length, `"${mode}" fallback empty at progress ${options.progress}`)
          .toBeGreaterThan(0);
        expect(css).not.toContain("undefined");
        expect(css).not.toContain("NaN");
      }
    }
  });

  it("hands out fresh uniform objects on every mount", () => {
    for (const mode of BRIEF_BACKGROUND_MODES) {
      const shaderModule = backgroundShaderFor(mode);
      const first = shaderModule.createUniforms();
      const second = shaderModule.createUniforms();

      expect(second).not.toBe(first);
      expect(Object.keys(second).sort()).toEqual(Object.keys(first).sort());
      for (const key of Object.keys(first)) {
        expect(second[key], `"${mode}" shares the "${key}" uniform between mounts`)
          .not.toBe(first[key]);
      }
    }
  });

  it("updates without throwing at both ends of a scene, with and without reduced motion", () => {
    for (const mode of BRIEF_BACKGROUND_MODES) {
      const shaderModule = backgroundShaderFor(mode);
      const uniforms = shaderModule.createUniforms();
      for (const options of FRAME_CASES) {
        expect(
          () => shaderModule.update(uniforms, frameForMode(mode, options)),
          `"${mode}" threw at progress ${options.progress} (reducedMotion=${options.reducedMotion})`,
        ).not.toThrow();
      }
    }
  });

  it("disposes without throwing when a module owns GPU resources", () => {
    for (const mode of BRIEF_BACKGROUND_MODES) {
      const shaderModule = backgroundShaderFor(mode);
      const uniforms = shaderModule.createUniforms();
      shaderModule.update(uniforms, frameForMode(mode, FRAME_CASES[0]));
      expect(() => shaderModule.dispose?.(uniforms)).not.toThrow();
    }
  });
});

describe("greenGrid lattice", () => {
  it("uses exactly the shader contract's cell size, so pixel transition A stays in register", () => {
    // Brief Section 7.5: "Pixel dimensions align with the existing background grid."
    expect(GREEN_GRID_CELL_PX).toBe(GRID_CELL_PX);
  });

  it("covers a viewport in whole cells", () => {
    const lattice = greenGridLattice([1440, 900]);
    expect(lattice.cellPx).toBe(GRID_CELL_PX);
    expect(lattice.columns * lattice.cellPx).toBeGreaterThanOrEqual(1440);
    expect(lattice.rows * lattice.cellPx).toBeGreaterThanOrEqual(900);
    expect(Number.isInteger(lattice.columns)).toBe(true);
    expect(Number.isInteger(lattice.rows)).toBe(true);
  });

  it("paints the brief's grid-statement colors in the no-WebGL fallback", () => {
    // Brief Section 4 tokens: --drop-grid-green / --drop-grid-line.
    const css = backgroundShaderFor("greenGrid").fallbackCss();
    expect(css).toContain("#102b19");
    expect(css).toContain("#245236");
    expect(css).toContain(`${GRID_CELL_PX}px`);
  });
});

describe("offWhiteGlow", () => {
  it("keeps DROP off-white as the base of its no-WebGL fallback", () => {
    // Brief Section 7.2: minimal off-white scene; the glow is atmosphere, not a fill.
    const css = backgroundShaderFor("offWhiteGlow").fallbackCss();
    expect(css).toContain("#f2f2f2");
  });

  it("responds to thesis progress in the fallback as well as the shader", () => {
    // Brief Section 7.2: "The bottom glow slowly expands and contracts with progress."
    const shaderModule = backgroundShaderFor("offWhiteGlow");
    const atRest = shaderModule.fallbackCss({
      transitionState: stateForMode("offWhiteGlow", 0).transitionState,
      sceneProgress: 0,
    });
    const bloomed = shaderModule.fallbackCss({
      transitionState: stateForMode("offWhiteGlow", 0.5).transitionState,
      sceneProgress: 0.5,
    });
    expect(bloomed).not.toBe(atRest);
  });
});
