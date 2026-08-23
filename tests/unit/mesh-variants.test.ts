/**
 * Monochrome Mesh + footer light-horizon unit tests (tickets 10 and 14).
 *
 * These test the PURE, GPU-FREE helpers the two background shader modules are built from — the
 * variant settings, the continuously integrated clocks, the tier detail knobs, and the static
 * CSS fallbacks. Per BUILD-GUIDE: uniform values are never asserted by reaching into a material,
 * and WebGL pixels are never asserted. Each variant's LOOK is manual visual QA.
 *
 * Expected values are transcribed from the master brief (Sections 7.8, 7.9, 7.10) and from the
 * scene-state seam's own scene -> background-mode map — never recomputed the way the code
 * computes them.
 */

import { describe, expect, it } from "vitest";

import {
  MESH_CONTROL_COLORS,
  MESH_GRID_COLUMNS,
  MESH_GRID_ROWS,
  MESH_PIVOT_RGB,
  MESH_VARIANT_TARGETS,
  MONO_MESH_PRESET,
  advanceMeshClock,
  createMeshClock,
  meshControlColorArray,
  meshDetailUniforms,
  meshSettingsForFrame,
  meshVariantUniforms,
  monoMeshFallbackCss,
  monoMeshShader,
  parseHexColor,
  type MeshVariantSettings,
} from "@/components/webgl/MonochromeMeshShader";
import {
  advanceFooterLightClock,
  createFooterLightClock,
  footerLightDetailUniforms,
  footerLightFallbackCss,
  footerLightShader,
  footerLightUniforms,
} from "@/components/webgl/FooterLightShader";
import type { BackgroundFrame, BackgroundShaderModule } from "@/components/webgl/shader-contract";
import { QUALITY_TIER_SETTINGS } from "@/lib/performance/quality-tier";
import {
  SCENE_BACKGROUND_MODE,
  createInitialSceneState,
  type LensCounts,
  type MeshVariant,
  type TransitionState,
} from "@/lib/scene";

/* ------------------------------------------------------------------ brief */

/** Brief Section 7.8, "Mesh 4x4 control colors", transcribed by hand. */
const BRIEF_MESH_CONTROL_COLORS = [
  ["#141415", "#ABAEB5", "#6C6E75", "#2E3034"],
  ["#696B74", "#2B2C32", "#C8C9CD", "#828694"],
  ["#C5C7CC", "#83868E", "#44464E", "#E4E4E6"],
  ["#42444C", "#E1E2E4", "#9C9FAA", "#5E6069"],
];

/** Brief Section 7.8, the Monochrome Mesh preset block, transcribed by hand. */
const BRIEF_MESH_PRESET = {
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
};

/** The three variants the seam names (scene-state types, ticket 10). */
const MESH_VARIANTS: readonly MeshVariant[] = ["normal", "reading", "fadeToBlack"];

/* --------------------------------------------------------------- helpers */

const SEED_COUNTS: LensCounts = {
  heroMessages: 3,
  menuItems: 2,
  films: 3,
  tracks: 11,
  artPieces: 4,
};

function transitionState(overrides: Partial<TransitionState> = {}): TransitionState {
  return { ...createInitialSceneState(SEED_COUNTS).transitionState, ...overrides };
}

function backgroundFrame(overrides: Partial<BackgroundFrame> = {}): BackgroundFrame {
  return {
    mode: "monoMesh",
    sceneProgress: 0,
    transitionState: transitionState(),
    reducedMotion: false,
    quality: QUALITY_TIER_SETTINGS.high,
    timeSeconds: 0,
    resolution: [1440, 900],
    pointer: [0, 0],
    ...overrides,
  };
}

/** A settings sweep across a variant, fine enough that a jump cannot hide between samples. */
function sweep(variant: MeshVariant, steps = 100): MeshVariantSettings[] {
  const samples: MeshVariantSettings[] = [];
  for (let step = 0; step <= steps; step += 1) {
    samples.push(meshVariantUniforms({ variant, amount: step / steps }));
  }
  return samples;
}

/* ------------------------------------------------------ control colors */

describe("monochrome mesh control colors", () => {
  it("uses the brief's exact 4x4 control grid", () => {
    expect(MESH_CONTROL_COLORS).toEqual(BRIEF_MESH_CONTROL_COLORS);
  });

  it("is a 4x4 grid, matching the preset's grid size", () => {
    expect(MESH_GRID_ROWS).toBe(4);
    expect(MESH_GRID_COLUMNS).toBe(4);
    expect(MONO_MESH_PRESET.grid).toBe(4);
    for (const row of MESH_CONTROL_COLORS) {
      expect(row).toHaveLength(4);
    }
  });

  it("parses each hex into 0..1 channels", () => {
    // 0x14 = 20, 0x15 = 21, 0xAB = 171, 0xAE = 174, 0xB5 = 181, 0xE4 = 228, 0xE6 = 230.
    expect(parseHexColor("#141415")).toEqual([20 / 255, 20 / 255, 21 / 255]);
    expect(parseHexColor("#ABAEB5")).toEqual([171 / 255, 174 / 255, 181 / 255]);
    expect(parseHexColor("#E4E4E6")).toEqual([228 / 255, 228 / 255, 230 / 255]);
    // 0x5E = 94, 0x60 = 96, 0x69 = 105.
    expect(parseHexColor("#5E6069")).toEqual([94 / 255, 96 / 255, 105 / 255]);
  });

  it("rejects anything that is not a 6-digit hex color", () => {
    expect(() => parseHexColor("#FFF")).toThrow();
    expect(() => parseHexColor("rgb(1,2,3)")).toThrow();
  });

  it("uploads one vec3 per control color, in row-major order", () => {
    const flat = meshControlColorArray();
    expect(flat).toHaveLength(16 * 3);
    // First control color of the brief's first row: #141415.
    expect(flat[0]).toBeCloseTo(20 / 255, 5);
    expect(flat[1]).toBeCloseTo(20 / 255, 5);
    expect(flat[2]).toBeCloseTo(21 / 255, 5);
    // Last control color of the brief's last row: #5E6069.
    expect(flat[45]).toBeCloseTo(94 / 255, 5);
    expect(flat[46]).toBeCloseTo(96 / 255, 5);
    expect(flat[47]).toBeCloseTo(105 / 255, 5);
  });

  it("hands out a fresh color array per canvas mount", () => {
    expect(meshControlColorArray()).not.toBe(meshControlColorArray());
  });

  it("collapses contrast toward a value inside the field's own range, not an invented gray", () => {
    // #141415 is the darkest control color and #E4E4E6 the lightest.
    for (const channel of MESH_PIVOT_RGB) {
      expect(channel).toBeGreaterThan(20 / 255);
      expect(channel).toBeLessThan(230 / 255);
    }
  });
});

describe("monochrome mesh preset", () => {
  it("matches the brief's preset block", () => {
    expect(MONO_MESH_PRESET).toEqual(BRIEF_MESH_PRESET);
  });
});

/* ----------------------------------------------------------- variants */

describe("mesh variants", () => {
  it("runs the tracks carousel at full liveliness", () => {
    expect(meshVariantUniforms({ variant: "normal", amount: 0 })).toEqual({
      speedScale: 1,
      brightness: 1,
      contrast: 1,
    });
    expect(meshVariantUniforms({ variant: "normal", amount: 1 })).toEqual({
      speedScale: 1,
      brightness: 1,
      contrast: 1,
    });
  });

  it("reads art pieces slower and darker than tracks", () => {
    const tracks = meshVariantUniforms({ variant: "normal", amount: 1 });
    const artPieces = meshVariantUniforms({ variant: "reading", amount: 1 });

    expect(artPieces.speedScale).toBeLessThan(tracks.speedScale);
    expect(artPieces.brightness).toBeLessThan(tracks.brightness);
    expect(artPieces.contrast).toBeLessThanOrEqual(tracks.contrast);
    // "slightly" — reading comfort, not a blackout.
    expect(artPieces.brightness).toBeGreaterThan(0.5);
    expect(artPieces.speedScale).toBeGreaterThan(0);
  });

  it("gives each variant a distinct settled look", () => {
    const settled = MESH_VARIANTS.map((variant) => meshVariantUniforms({ variant, amount: 1 }));
    const encoded = new Set(settled.map((settings) => JSON.stringify(settings)));
    expect(encoded.size).toBe(MESH_VARIANTS.length);
  });

  it("ends the footer fade at pure black with no contrast left", () => {
    const faded = meshVariantUniforms({ variant: "fadeToBlack", amount: 1 });
    expect(faded.brightness).toBe(0);
    expect(faded.contrast).toBe(0);
    expect(faded).toEqual(MESH_VARIANT_TARGETS.fadeToBlack);
  });

  it("starts the art-pieces variant exactly where tracks left off", () => {
    expect(meshVariantUniforms({ variant: "reading", amount: 0 })).toEqual(
      meshVariantUniforms({ variant: "normal", amount: 1 }),
    );
  });

  it("starts the footer fade exactly where art pieces settled", () => {
    expect(meshVariantUniforms({ variant: "fadeToBlack", amount: 0 })).toEqual(
      meshVariantUniforms({ variant: "reading", amount: 1 }),
    );
  });

  it("never brightens or sharpens while the fade advances", () => {
    const samples = sweep("fadeToBlack");
    for (let index = 1; index < samples.length; index += 1) {
      expect(samples[index].brightness).toBeLessThanOrEqual(samples[index - 1].brightness);
      expect(samples[index].contrast).toBeLessThanOrEqual(samples[index - 1].contrast);
      expect(samples[index].speedScale).toBeLessThanOrEqual(samples[index - 1].speedScale);
    }
  });

  it("crosses tracks -> art pieces -> footer with no jump at any boundary", () => {
    // One continuous mesh across three scenes (brief Section 7.9): the field must never cut.
    const timeline = [...sweep("normal"), ...sweep("reading"), ...sweep("fadeToBlack")];
    const maxStep = 0.03;

    for (let index = 1; index < timeline.length; index += 1) {
      const previous = timeline[index - 1];
      const current = timeline[index];
      expect(current.brightness).toBeLessThanOrEqual(previous.brightness + 1e-12);
      expect(Math.abs(current.brightness - previous.brightness)).toBeLessThan(maxStep);
      expect(Math.abs(current.contrast - previous.contrast)).toBeLessThan(maxStep);
      expect(Math.abs(current.speedScale - previous.speedScale)).toBeLessThan(maxStep);
    }
  });

  it("is a pure function of the descriptor, so reverse scroll restores the field", () => {
    for (const variant of MESH_VARIANTS) {
      for (const amount of [0, 0.17, 0.5, 0.83, 1]) {
        const first = meshVariantUniforms({ variant, amount });
        const second = meshVariantUniforms({ variant, amount });
        expect(second).toEqual(first);
      }
    }

    const forward = sweep("fadeToBlack", 20);
    const backward = [...sweep("fadeToBlack", 20)].reverse();
    expect(backward.reverse()).toEqual(forward);
  });

  it("clamps amounts that arrive outside 0..1", () => {
    expect(meshVariantUniforms({ variant: "fadeToBlack", amount: -3 })).toEqual(
      meshVariantUniforms({ variant: "fadeToBlack", amount: 0 }),
    );
    expect(meshVariantUniforms({ variant: "fadeToBlack", amount: 4 })).toEqual(
      meshVariantUniforms({ variant: "fadeToBlack", amount: 1 }),
    );
    expect(meshVariantUniforms({ variant: "reading", amount: Number.NaN })).toEqual(
      meshVariantUniforms({ variant: "reading", amount: 0 }),
    );
  });

  it("keeps the field alive while pixel B reveals it, and gone once the footer fade finished", () => {
    // The reducer emits no mesh descriptor during pixel B (the mesh is revealed through the
    // cells) nor after the footer fade completes (nothing left to draw).
    expect(meshSettingsForFrame("pixelB", transitionState())).toEqual(MESH_VARIANT_TARGETS.normal);
    expect(meshSettingsForFrame("monoMesh", transitionState())).toEqual(
      MESH_VARIANT_TARGETS.normal,
    );
    expect(meshSettingsForFrame("footerLight", transitionState())).toEqual(
      MESH_VARIANT_TARGETS.fadeToBlack,
    );
    expect(
      meshSettingsForFrame(
        "footerLight",
        transitionState({ mesh: { variant: "fadeToBlack", amount: 0 } }),
      ),
    ).toEqual(meshVariantUniforms({ variant: "reading", amount: 1 }));
  });

  it("never flashes a bright field when scroll jumps straight into the footer", () => {
    // The canvas hands each crossfade layer a frame reporting that layer's OWN mode, so a mesh
    // layer fading out over the footer still sees mode "monoMesh". Only the footer reveal in the
    // reducer's own output distinguishes "the mesh has finished" from "the mesh is arriving".
    const deepInFooter = transitionState({ mesh: null, footerReveal: 1 });
    expect(meshSettingsForFrame("monoMesh", deepInFooter)).toEqual(
      MESH_VARIANT_TARGETS.fadeToBlack,
    );
    expect(meshSettingsForFrame("monoMesh", deepInFooter).brightness).toBe(0);
  });

  it("falls back to the alive field rather than throwing on a frame with no state", () => {
    expect(meshSettingsForFrame("monoMesh", null)).toEqual(MESH_VARIANT_TARGETS.normal);
    expect(meshSettingsForFrame("monoMesh", undefined)).toEqual(MESH_VARIANT_TARGETS.normal);
  });
});

/* -------------------------------------------------------------- clocks */

describe("mesh clock", () => {
  const FRAME = 1 / 60;

  it("advances by the elapsed time, scaled by the variant speed", () => {
    const start = createMeshClock(0);
    const full = advanceMeshClock(start, FRAME, 1);
    expect(full.meshTime - start.meshTime).toBeCloseTo(FRAME, 6);

    const half = advanceMeshClock(start, FRAME, 0.5);
    expect(half.meshTime - start.meshTime).toBeCloseTo(FRAME / 2, 6);
  });

  it("holds still when reduced motion stops the clock, without rewinding it", () => {
    const start = advanceMeshClock(createMeshClock(0), 2 * FRAME, 1);
    const stopped = advanceMeshClock(start, 3 * FRAME, 0);
    expect(stopped.meshTime).toBe(start.meshTime);

    // Resuming continues from the held value — a stop is not a reset.
    const resumed = advanceMeshClock(stopped, 4 * FRAME, 1);
    expect(resumed.meshTime).toBeGreaterThan(stopped.meshTime);
  });

  it("never restarts or reseeds when the variant changes", () => {
    // Tracks -> art pieces -> footer, one frame at a time, exactly as the canvas drives it.
    const timeline: MeshVariant[] = [
      ...Array<MeshVariant>(20).fill("normal"),
      ...Array<MeshVariant>(20).fill("reading"),
      ...Array<MeshVariant>(20).fill("fadeToBlack"),
    ];

    let clock = createMeshClock(0);
    const origin = clock.meshTime;

    timeline.forEach((variant, index) => {
      const previous = clock;
      const amount = (index % 20) / 19;
      const { speedScale } = meshVariantUniforms({ variant, amount });
      clock = advanceMeshClock(previous, (index + 1) * FRAME, speedScale);

      expect(clock.meshTime).toBeGreaterThanOrEqual(previous.meshTime);
      // One frame of drift at most: no jump, no reseed, no restart at any variant boundary.
      expect(clock.meshTime - previous.meshTime).toBeLessThanOrEqual(FRAME + 1e-9);
      expect(clock.meshTime).toBeGreaterThanOrEqual(origin);
    });

    expect(clock.meshTime).toBeGreaterThan(origin);
  });

  it("refuses to fast-forward after a backgrounded tab or a clock that ran backwards", () => {
    const start = createMeshClock(0);
    const afterGap = advanceMeshClock(start, 45, 1);
    expect(afterGap.meshTime - start.meshTime).toBeLessThan(1);

    const rewound = advanceMeshClock(afterGap, 1, 1);
    expect(rewound.meshTime).toBe(afterGap.meshTime);
  });

  it("survives a non-finite clock reading", () => {
    const start = createMeshClock(0);
    const broken = advanceMeshClock(start, Number.NaN, 1);
    expect(Number.isFinite(broken.meshTime)).toBe(true);
    expect(Number.isFinite(broken.sourceSeconds)).toBe(true);
  });
});

describe("footer light clock", () => {
  const FRAME = 1 / 60;

  it("keeps running with no input at all, and holds still under reduced motion", () => {
    const start = createFooterLightClock(0);
    const alive = advanceFooterLightClock(start, FRAME, 1);
    expect(alive.lightTime).toBeGreaterThan(start.lightTime);

    const stopped = advanceFooterLightClock(alive, 2 * FRAME, 0);
    expect(stopped.lightTime).toBe(alive.lightTime);
  });
});

/* -------------------------------------------------------- quality tiers */

describe("quality tiers", () => {
  it("reduces mesh warp detail from high to low", () => {
    const high = meshDetailUniforms(QUALITY_TIER_SETTINGS.high);
    const medium = meshDetailUniforms(QUALITY_TIER_SETTINGS.medium);
    const low = meshDetailUniforms(QUALITY_TIER_SETTINGS.low);

    expect(high.warpOctaves).toBeGreaterThan(medium.warpOctaves);
    expect(medium.warpOctaves).toBeGreaterThan(low.warpOctaves);
    expect(low.warpOctaves).toBeGreaterThanOrEqual(1);
  });

  it("thins the mesh grain on medium and drops it entirely on low", () => {
    const high = meshDetailUniforms(QUALITY_TIER_SETTINGS.high);
    const medium = meshDetailUniforms(QUALITY_TIER_SETTINGS.medium);
    const low = meshDetailUniforms(QUALITY_TIER_SETTINGS.low);

    expect(high.grain).toBeGreaterThan(medium.grain);
    expect(medium.grain).toBeGreaterThan(0);
    expect(low.grain).toBe(0);
  });

  it("flattens the footer horizon to a plain ribbon under reduced motion", () => {
    const moving = footerLightDetailUniforms(QUALITY_TIER_SETTINGS.high, false);
    const still = footerLightDetailUniforms(QUALITY_TIER_SETTINGS.high, true);

    expect(moving.harmonics).toBeGreaterThan(still.harmonics);
    expect(still.harmonics).toBe(0);
  });

  it("reduces footer horizon detail from high to low", () => {
    const high = footerLightDetailUniforms(QUALITY_TIER_SETTINGS.high, false);
    const medium = footerLightDetailUniforms(QUALITY_TIER_SETTINGS.medium, false);
    const low = footerLightDetailUniforms(QUALITY_TIER_SETTINGS.low, false);

    expect(high.harmonics).toBeGreaterThanOrEqual(medium.harmonics);
    expect(medium.harmonics).toBeGreaterThanOrEqual(low.harmonics);
    expect(low.grain).toBe(0);
  });
});

/* --------------------------------------------------------- footer light */

describe("footer light horizon", () => {
  it("rises from almost nothing to full brightness across the reveal", () => {
    const start = footerLightUniforms(0);
    const end = footerLightUniforms(1);

    expect(start.coreIntensity).toBeLessThan(0.1);
    expect(end.coreIntensity).toBe(1);
    expect(end.bloom).toBeGreaterThan(start.bloom);
    expect(end.fringe).toBeGreaterThan(start.fringe);
  });

  it("keeps the spectral fringes restrained next to the white core", () => {
    const settled = footerLightUniforms(1);
    expect(settled.fringe).toBeLessThan(settled.coreIntensity / 2);
  });

  it("drifts the band upward but never out of the lower half of the frame", () => {
    let previous = footerLightUniforms(0).horizonY;
    for (let step = 1; step <= 20; step += 1) {
      const current = footerLightUniforms(step / 20).horizonY;
      expect(current).toBeGreaterThanOrEqual(previous);
      expect(current).toBeLessThan(0.5);
      previous = current;
    }
    expect(footerLightUniforms(1).horizonY).toBeGreaterThan(footerLightUniforms(0).horizonY);
  });

  it("stays fully alive without any pointer input", () => {
    const withPointer = footerLightUniforms(0.7, [0.4, -0.2]);
    const withoutPointer = footerLightUniforms(0.7, null);

    expect(withoutPointer.pointerStrength).toBe(0);
    expect(withoutPointer.pointerY).toBe(0);
    expect(withPointer.pointerStrength).toBe(1);

    // Everything that makes the horizon a horizon is untouched by the pointer.
    expect(withoutPointer.coreIntensity).toBe(withPointer.coreIntensity);
    expect(withoutPointer.bloom).toBe(withPointer.bloom);
    expect(withoutPointer.fringe).toBe(withPointer.fringe);
    expect(withoutPointer.horizonY).toBe(withPointer.horizonY);
  });

  it("maps the pointer into the shader's 0..1 horizontal space", () => {
    expect(footerLightUniforms(1, [-1, 0]).pointerX).toBe(0);
    expect(footerLightUniforms(1, [0, 0]).pointerX).toBe(0.5);
    expect(footerLightUniforms(1, [1, 0]).pointerX).toBe(1);
  });

  it("ignores a pointer that reports garbage", () => {
    const broken = footerLightUniforms(0.5, [Number.NaN, 0.5]);
    expect(broken.pointerStrength).toBe(0);
    expect(broken).toEqual(footerLightUniforms(0.5, null));
  });

  it("clamps the reveal and stays reversible", () => {
    expect(footerLightUniforms(-2)).toEqual(footerLightUniforms(0));
    expect(footerLightUniforms(9)).toEqual(footerLightUniforms(1));
    expect(footerLightUniforms(Number.NaN)).toEqual(footerLightUniforms(0));

    for (const reveal of [0, 0.25, 0.5, 0.75, 1]) {
      expect(footerLightUniforms(reveal)).toEqual(footerLightUniforms(reveal));
    }
  });

  it("moves the reveal continuously, with no jump between frames", () => {
    let previous = footerLightUniforms(0);
    for (let step = 1; step <= 100; step += 1) {
      const current = footerLightUniforms(step / 100);
      expect(Math.abs(current.coreIntensity - previous.coreIntensity)).toBeLessThan(0.03);
      expect(Math.abs(current.horizonY - previous.horizonY)).toBeLessThan(0.03);
      previous = current;
    }
  });
});

/* ----------------------------------------------------- module contract */

describe("background shader modules", () => {
  const modules: readonly BackgroundShaderModule[] = [monoMeshShader, footerLightShader];

  it("registers the modes the reducer maps to tracks, art pieces, and the footer", () => {
    expect(monoMeshShader.mode).toBe("monoMesh");
    expect(footerLightShader.mode).toBe("footerLight");
    expect(monoMeshShader.mode).toBe(SCENE_BACKGROUND_MODE.tracks);
    expect(monoMeshShader.mode).toBe(SCENE_BACKGROUND_MODE.artPieces);
    expect(footerLightShader.mode).toBe(SCENE_BACKGROUND_MODE.footer);
  });

  it("ships a fragment shader and no vertex-shader override", () => {
    for (const shaderModule of modules) {
      expect(typeof shaderModule.fragmentShader).toBe("string");
      expect(shaderModule.fragmentShader.length).toBeGreaterThan(0);
      expect(shaderModule.fragmentShader).toContain("gl_FragColor");
      expect(shaderModule.vertexShader).toBeUndefined();
    }
  });

  it("hands out fresh uniforms per canvas mount, so nothing leaks between mounts", () => {
    for (const shaderModule of modules) {
      const first = shaderModule.createUniforms();
      const second = shaderModule.createUniforms();

      expect(first).not.toBe(second);
      expect(Object.keys(first).sort()).toEqual(Object.keys(second).sort());
      for (const key of Object.keys(first)) {
        expect(first[key]).not.toBe(second[key]);
      }
    }
  });

  it("updates without throwing across progress, variants, tiers, and reduced motion", () => {
    for (const shaderModule of modules) {
      const uniforms = shaderModule.createUniforms();
      let seconds = 0;

      for (const progress of [0, 0.5, 1]) {
        for (const variant of MESH_VARIANTS) {
          for (const reducedMotion of [false, true]) {
            for (const quality of Object.values(QUALITY_TIER_SETTINGS)) {
              seconds += 1 / 60;
              expect(() =>
                shaderModule.update(
                  uniforms,
                  backgroundFrame({
                    mode: shaderModule.mode,
                    sceneProgress: progress,
                    reducedMotion,
                    quality,
                    timeSeconds: seconds,
                    transitionState: transitionState({
                      mesh: { variant, amount: progress },
                      footerReveal: progress,
                    }),
                  }),
                ),
              ).not.toThrow();
            }
          }
        }
      }
    }
  });

  it("updates without throwing when no mesh descriptor is in flight", () => {
    for (const shaderModule of modules) {
      const uniforms = shaderModule.createUniforms();
      expect(() =>
        shaderModule.update(
          uniforms,
          backgroundFrame({ mode: shaderModule.mode, transitionState: transitionState() }),
        ),
      ).not.toThrow();
    }
  });

  it("survives a foreign uniform set rather than throwing on the render loop", () => {
    for (const shaderModule of modules) {
      expect(() => shaderModule.update({}, backgroundFrame({ mode: shaderModule.mode }))).not.toThrow();
    }
  });

  it("degrades to a real static CSS background, never a blank page", () => {
    for (const shaderModule of modules) {
      const css = shaderModule.fallbackCss();
      expect(css).toContain("gradient(");
      expect(css).toContain("#000000");
    }
  });

  it("paints the fallback mesh with the brief's own control colors", () => {
    const css = monoMeshFallbackCss(meshVariantUniforms({ variant: "normal", amount: 0 }));
    // #141415 -> rgb(20, 20, 21) and #E4E4E6 -> rgb(228, 228, 230).
    expect(css).toContain("rgba(20, 20, 21,");
    expect(css).toContain("rgba(228, 228, 230,");
  });

  it("fades the fallback mesh to black alongside the shader", () => {
    const faded = monoMeshShader.fallbackCss({
      sceneProgress: 1,
      transitionState: transitionState({ mesh: { variant: "fadeToBlack", amount: 1 } }),
    });
    expect(faded).toContain("rgba(0, 0, 0, 1)");
  });

  it("draws the footer fallback as a ribbon positioned by the reveal", () => {
    const early = footerLightFallbackCss(footerLightUniforms(0));
    const settled = footerLightFallbackCss(footerLightUniforms(1));
    expect(early).not.toBe(settled);
    expect(settled).toContain("radial-gradient");
  });
});
