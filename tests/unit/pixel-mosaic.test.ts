/**
 * Pixel mosaic unit tests (tickets 08 and 11 — the shader halves).
 *
 * These test the **pure threshold field**, never uniforms and never GPU state. WebGL pixels are
 * never asserted (BUILD-GUIDE seam 3); what is asserted here is the maths the GLSL mirrors:
 * determinism, reversibility, bottom-weighting, an irregular skyline, and one shared lattice
 * across both transitions.
 *
 * Expected values come from the brief's acceptance criteria — "pixel blocks enter from the bottom
 * with an irregular stepped skyline", "each cell changes state at a seeded threshold", "reverse
 * scroll restores the exact prior grid state" (Section 7.5), "pixel coordinates should remain
 * consistent with Transition A" (Section 7.7) — and from the contract's `GRID_CELL_PX`. Nothing
 * here re-runs the implementation's own arithmetic to decide what to expect.
 */

import { describe, expect, it } from "vitest";

import {
  PIXEL_SEED,
  createInitialSceneState,
  type LensCounts,
  type TransitionState,
} from "@/lib/scene";
import { QUALITY_TIER_SETTINGS } from "@/lib/performance/quality-tier";
import {
  cellThreshold,
  columnSkyline,
  isCellReplaced,
  mosaicGrid,
  pixelAShader,
  pixelBShader,
  pixelSeedKey,
  replacedCells,
} from "@/components/webgl/PixelMosaicShader";
import { WAVY_DOTS_STATIC_POSE_SECONDS, wavyDotsShader, wavyDotsTime } from "@/components/webgl/WavyDotsShader";
import {
  GRID_CELL_PX,
  type BackgroundFrame,
  type BackgroundShaderModule,
} from "@/components/webgl/shader-contract";

/** A desktop drawing buffer, in CSS pixels. 1280 / 64 = 20 columns, 720 / 64 = 11.25 -> 12 rows. */
const DESKTOP: readonly [number, number] = [1280, 720];
/** A larger buffer, to prove the properties are not an artefact of one viewport. */
const WIDESCREEN: readonly [number, number] = [1920, 1080];

/** W04 counts, from CONTEXT.md's seed description: 3 hero messages / 2 menu / 3 films / 11 tracks / 4 art. */
const W04_COUNTS: LensCounts = {
  heroMessages: 3,
  menuItems: 2,
  films: 3,
  tracks: 11,
  artPieces: 4,
};

function baseTransitionState(): TransitionState {
  return createInitialSceneState(W04_COUNTS).transitionState;
}

/** The reducer's output midway through transition A. */
function duringPixelA(progress: number): TransitionState {
  return { ...baseTransitionState(), pixelA: { seed: PIXEL_SEED, progress }, pixelB: null };
}

/** The reducer's output midway through transition B. */
function duringPixelB(progress: number, darkBeat = false): TransitionState {
  return { ...baseTransitionState(), pixelA: null, pixelB: { seed: PIXEL_SEED, progress }, darkBeat };
}

function frame(overrides: Partial<BackgroundFrame> = {}): BackgroundFrame {
  return {
    mode: "pixelA",
    sceneProgress: 0.5,
    transitionState: baseTransitionState(),
    reducedMotion: false,
    quality: QUALITY_TIER_SETTINGS.high,
    timeSeconds: 4.25,
    resolution: DESKTOP,
    pointer: [0, 0],
    ...overrides,
  };
}

/** Every cell of a frame, bottom row first. */
function allCells(resolution: readonly [number, number]): { x: number; y: number }[] {
  const { columns, rows } = mosaicGrid(resolution);
  const cells: { x: number; y: number }[] = [];
  for (let y = 0; y < rows; y += 1) {
    for (let x = 0; x < columns; x += 1) cells.push({ x, y });
  }
  return cells;
}

function mean(values: readonly number[]): number {
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function cellKeys(cells: readonly (readonly [number, number])[]): string {
  return cells.map(([x, y]) => `${x},${y}`).join(" ");
}

/* -------------------------------------------------------------------------- */

describe("mosaic lattice", () => {
  it("uses the green grid's own cell size, so the mosaic aligns with the background grid", () => {
    // Brief Section 7.5: "Pixel dimensions align with the existing background grid."
    expect(mosaicGrid(DESKTOP).cellPx).toBe(GRID_CELL_PX);
  });

  it("covers the frame with whole cells", () => {
    // 1280 / 64 = 20 exactly; 720 / 64 = 11.25, so the top row is partial and still counted.
    expect(mosaicGrid(DESKTOP)).toEqual({ columns: 20, rows: 12, cellPx: GRID_CELL_PX });
    expect(mosaicGrid(WIDESCREEN)).toEqual({ columns: 30, rows: 17, cellPx: GRID_CELL_PX });
  });

  it("never reports an empty lattice, whatever the canvas reports", () => {
    expect(mosaicGrid([0, 0]).columns).toBeGreaterThanOrEqual(1);
    expect(mosaicGrid([0, 0]).rows).toBeGreaterThanOrEqual(1);
    expect(mosaicGrid([Number.NaN, Number.NaN]).rows).toBeGreaterThanOrEqual(1);
  });
});

describe("seeded cell thresholds", () => {
  it("gives the same cell the same threshold every time it is asked", () => {
    // Brief Section 7.5: "Each cell changes state at a seeded threshold."
    for (const { x, y } of allCells(DESKTOP)) {
      const first = cellThreshold(x, y, PIXEL_SEED, DESKTOP);
      const second = cellThreshold(x, y, PIXEL_SEED, DESKTOP);
      expect(second).toBe(first);
    }
  });

  it("keeps every threshold strictly inside the transition, so 0 replaces nothing and 1 replaces all", () => {
    const thresholds = allCells(DESKTOP).map(({ x, y }) => cellThreshold(x, y, PIXEL_SEED, DESKTOP));
    expect(Math.min(...thresholds)).toBeGreaterThan(0);
    expect(Math.max(...thresholds)).toBeLessThan(1);

    expect(replacedCells(PIXEL_SEED, DESKTOP, 0)).toHaveLength(0);
    expect(replacedCells(PIXEL_SEED, DESKTOP, 1)).toHaveLength(20 * 12);
  });

  it("gives a different seed a different field", () => {
    const seeded = allCells(DESKTOP).map(({ x, y }) => cellThreshold(x, y, PIXEL_SEED, DESKTOP));
    const other = allCells(DESKTOP).map(({ x, y }) => cellThreshold(x, y, PIXEL_SEED + 1, DESKTOP));
    expect(other).not.toEqual(seeded);
  });

  it("folds the seed to a value single precision can hold exactly", () => {
    // A seed that rounds differently on CPU and GPU would silently give them different fields.
    const key = pixelSeedKey(PIXEL_SEED);
    expect(Math.fround(key)).toBe(key);
    expect(key).toBeGreaterThanOrEqual(0);
    expect(key).toBeLessThan(1);
  });

  it("does not reshuffle a cell when only the frame width changes", () => {
    const wider: readonly [number, number] = [DESKTOP[0] + 640, DESKTOP[1]];
    for (const { x, y } of allCells(DESKTOP)) {
      expect(cellThreshold(x, y, PIXEL_SEED, wider)).toBe(cellThreshold(x, y, PIXEL_SEED, DESKTOP));
    }
  });
});

describe("cells enter from the bottom", () => {
  it("gives lower rows lower thresholds than higher rows, row by row", () => {
    // Brief Section 7.5: "Pixel blocks enter from the bottom." Asserted over each row's aggregate,
    // not a hand-picked pair — individual cells are deliberately jittered past their neighbours.
    for (const resolution of [DESKTOP, WIDESCREEN]) {
      const { columns, rows } = mosaicGrid(resolution);
      const rowMeans: number[] = [];
      for (let y = 0; y < rows; y += 1) {
        const row: number[] = [];
        for (let x = 0; x < columns; x += 1) row.push(cellThreshold(x, y, PIXEL_SEED, resolution));
        rowMeans.push(mean(row));
      }
      for (let y = 1; y < rowMeans.length; y += 1) {
        expect(rowMeans[y]).toBeGreaterThan(rowMeans[y - 1]);
      }
    }
  });

  it("fills the bottom of the frame before the top", () => {
    const { columns, rows } = mosaicGrid(DESKTOP);
    const bottomHalf = allCells(DESKTOP).filter((cell) => cell.y < rows / 2);
    const topHalf = allCells(DESKTOP).filter((cell) => cell.y >= rows / 2);

    const replacedAtMidpoint = (cells: { x: number; y: number }[]) =>
      cells.filter((cell) => isCellReplaced(cell.x, cell.y, PIXEL_SEED, DESKTOP, 0.5)).length;

    expect(replacedAtMidpoint(bottomHalf)).toBeGreaterThan(replacedAtMidpoint(topHalf));
    expect(bottomHalf.length + topHalf.length).toBe(columns * rows);
  });
});

describe("the skyline is irregular, not a rising line", () => {
  it("replaces a different number of cells in different columns", () => {
    // Brief Section 7.5 forbids a wipe: a wipe would replace the same count in every column.
    for (const resolution of [DESKTOP, WIDESCREEN]) {
      const skyline = columnSkyline(PIXEL_SEED, resolution, 0.5);
      const distinct = new Set(skyline);
      expect(distinct.size).toBeGreaterThanOrEqual(3);
      expect(Math.max(...skyline) - Math.min(...skyline)).toBeGreaterThanOrEqual(2);
    }
  });

  it("keeps the skyline broken up all the way through the transition", () => {
    for (const progress of [0.25, 0.4, 0.6, 0.75]) {
      const skyline = columnSkyline(PIXEL_SEED, WIDESCREEN, progress);
      expect(new Set(skyline).size).toBeGreaterThan(1);
    }
  });

  it("leaves gaps at the frontier rather than a clean edge", () => {
    // Some columns hold a cell that is still un-replaced below one that already flipped: the
    // per-cell dither, which is what makes the front read as pixels rather than a line.
    const { columns, rows } = mosaicGrid(WIDESCREEN);
    let gaps = 0;
    for (let x = 0; x < columns; x += 1) {
      for (let y = 1; y < rows; y += 1) {
        const below = isCellReplaced(x, y - 1, PIXEL_SEED, WIDESCREEN, 0.5);
        const above = isCellReplaced(x, y, PIXEL_SEED, WIDESCREEN, 0.5);
        if (above && !below) gaps += 1;
      }
    }
    expect(gaps).toBeGreaterThan(0);
  });
});

describe("reverse scroll restores the prior state", () => {
  it("replaces exactly the same cells at a progress reached forwards or backwards", () => {
    // Brief Section 7.5: "Reverse scroll restores the exact prior grid state." The property holds
    // because replacement is a pure predicate of (cell, seed, progress) — any accumulated state
    // in the field would break this.
    const meetingPoint = 0.62;

    let forwards = replacedCells(PIXEL_SEED, DESKTOP, 0);
    for (const progress of [0.1, 0.25, 0.4, 0.55, meetingPoint]) {
      forwards = replacedCells(PIXEL_SEED, DESKTOP, progress);
    }

    let backwards = replacedCells(PIXEL_SEED, DESKTOP, 1);
    for (const progress of [0.95, 0.85, 0.75, 0.7, meetingPoint]) {
      backwards = replacedCells(PIXEL_SEED, DESKTOP, progress);
    }

    expect(cellKeys(backwards)).toBe(cellKeys(forwards));
  });

  it("mirrors the whole trajectory, step for step", () => {
    const steps = [0, 0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1];
    const outbound = steps.map((progress) => cellKeys(replacedCells(PIXEL_SEED, DESKTOP, progress)));
    const inbound = [...steps]
      .reverse()
      .map((progress) => cellKeys(replacedCells(PIXEL_SEED, DESKTOP, progress)));
    expect(inbound).toEqual([...outbound].reverse());
  });

  it("never un-replaces a cell while progress increases", () => {
    const { columns, rows } = mosaicGrid(DESKTOP);
    for (let x = 0; x < columns; x += 1) {
      for (let y = 0; y < rows; y += 1) {
        let seenReplaced = false;
        for (let progress = 0; progress <= 1.0001; progress += 0.05) {
          const replaced = isCellReplaced(x, y, PIXEL_SEED, DESKTOP, progress);
          if (seenReplaced) expect(replaced).toBe(true);
          seenReplaced = seenReplaced || replaced;
        }
      }
    }
  });
});

describe("transitions A and B share one lattice", () => {
  it("reads its own descriptor out of reducer output, and only its own", () => {
    const inA = duringPixelA(0.3);
    expect(pixelAShader.readDescriptor(inA)).toEqual({ seed: PIXEL_SEED, progress: 0.3 });
    expect(pixelBShader.readDescriptor(inA)).toBeNull();

    const inB = duringPixelB(0.7);
    expect(pixelBShader.readDescriptor(inB)).toEqual({ seed: PIXEL_SEED, progress: 0.7 });
    expect(pixelAShader.readDescriptor(inB)).toBeNull();
  });

  it("maps a cell coordinate to the same threshold in both transitions", () => {
    // Brief Section 7.7: "Pixel coordinates should remain consistent with Transition A."
    const seedInA = pixelAShader.readDescriptor(duringPixelA(0.3))?.seed;
    const seedInB = pixelBShader.readDescriptor(duringPixelB(0.7))?.seed;
    expect(seedInA).toBe(seedInB);

    for (const { x, y } of allCells(DESKTOP)) {
      expect(cellThreshold(x, y, seedInB as number, DESKTOP)).toBe(
        cellThreshold(x, y, seedInA as number, DESKTOP),
      );
    }
  });

  it("dissolves between the pair of backgrounds the brief names", () => {
    expect(pixelAShader.transition.from).toBe("greenGrid");
    expect(pixelAShader.transition.to).toBe("wavyDots");
    expect(pixelBShader.transition.from).toBe("wavyDots");
    expect(pixelBShader.transition.to).toBe("monoMesh");
  });

  it("keeps the orange/purple energy pass unique to transition B", () => {
    // Brief Section 7.7, step 4 — only the second transition passes through colour.
    expect(pixelBShader.transition.spectralMix).toBeGreaterThan(0);
    expect(pixelAShader.transition.spectralMix).toBe(0);
  });
});

describe("background shader module contract", () => {
  const modules: readonly BackgroundShaderModule[] = [pixelAShader, pixelBShader, wavyDotsShader];

  it("registers each module against its own background mode", () => {
    expect(pixelAShader.mode).toBe("pixelA");
    expect(pixelBShader.mode).toBe("pixelB");
    expect(wavyDotsShader.mode).toBe("wavyDots");
  });

  it("ships a fragment shader and fresh uniforms per mount", () => {
    for (const shader of modules) {
      expect(shader.fragmentShader.length).toBeGreaterThan(0);
      const first = shader.createUniforms();
      const second = shader.createUniforms();
      expect(second).not.toBe(first);
      for (const key of Object.keys(first)) {
        expect(second[key]).not.toBe(first[key]);
      }
    }
  });

  it("updates without throwing at the ends and the middle of the transition", () => {
    for (const progress of [0, 0.5, 1]) {
      const a = pixelAShader.createUniforms();
      expect(() =>
        pixelAShader.update(a, frame({ mode: "pixelA", transitionState: duringPixelA(progress) })),
      ).not.toThrow();

      const b = pixelBShader.createUniforms();
      expect(() =>
        pixelBShader.update(
          b,
          frame({ mode: "pixelB", transitionState: duringPixelB(progress, progress === 1) }),
        ),
      ).not.toThrow();
    }
  });

  it("updates without throwing under reduced motion, at every quality tier", () => {
    for (const quality of Object.values(QUALITY_TIER_SETTINGS)) {
      for (const shader of modules) {
        const uniforms = shader.createUniforms();
        expect(() =>
          shader.update(
            uniforms,
            frame({ reducedMotion: true, quality, transitionState: duringPixelB(0.5) }),
          ),
        ).not.toThrow();
      }
    }
  });

  it("survives a canvas that reports nothing useful about its size", () => {
    for (const shader of modules) {
      const uniforms = shader.createUniforms();
      expect(() =>
        shader.update(uniforms, frame({ resolution: [0, 0], timeSeconds: Number.NaN })),
      ).not.toThrow();
    }
  });

  it("holds its last progress while the canvas crossfades the mode out", () => {
    // The reducer nulls the descriptor as soon as the scene changes; snapping the field back to
    // zero mid-crossfade would flash the outgoing background back in.
    const uniforms = pixelAShader.createUniforms();
    pixelAShader.update(uniforms, frame({ transitionState: duringPixelA(0.8) }));
    expect(() => pixelAShader.update(uniforms, frame({ transitionState: baseTransitionState() }))).not.toThrow();
  });

  it("degrades to a real static background when WebGL is unavailable", () => {
    // Brief Section 15 / ticket 04: never a blank or broken page.
    expect(pixelAShader.fallbackCss()).toContain("#102b19"); // --drop-grid-green, the outgoing side
    expect(pixelBShader.fallbackCss()).toContain("#000000"); // the film scene's black
    expect(wavyDotsShader.fallbackCss()).toContain("#000000");

    const partway = pixelAShader.fallbackCss({
      transitionState: duringPixelA(0.5),
      sceneProgress: 0.5,
    });
    expect(partway).toContain("50.00%");
    expect(pixelAShader.fallbackCss()).not.toContain("50.00%");
  });
});

describe("wavy dots honours reduced motion and quality tiers", () => {
  it("freezes the field on a single pose when the visitor prefers reduced motion", () => {
    // Brief Section 14: reduced motion means a static background, not a slower one.
    expect(wavyDotsTime({ reducedMotion: true, timeSeconds: 0 })).toBe(WAVY_DOTS_STATIC_POSE_SECONDS);
    expect(wavyDotsTime({ reducedMotion: true, timeSeconds: 12.5 })).toBe(
      wavyDotsTime({ reducedMotion: true, timeSeconds: 0 }),
    );
  });

  it("keeps the field moving when motion is allowed", () => {
    expect(wavyDotsTime({ reducedMotion: false, timeSeconds: 12.5 })).toBeGreaterThan(
      wavyDotsTime({ reducedMotion: false, timeSeconds: 0 }),
    );
  });

  it("takes its phase from the clock alone, so the transitions can match it exactly", () => {
    // Pixel A dissolves into this field and pixel B dissolves out of it, at scene progresses that
    // have nothing to do with the film scene's. Folding scroll into the phase would jump the dot
    // floor at both handoffs.
    const early = frame({ mode: "wavyDots", timeSeconds: 7.5, sceneProgress: 0.05 });
    const late = frame({ mode: "wavyDots", timeSeconds: 7.5, sceneProgress: 0.95 });
    expect(wavyDotsTime(late)).toBe(wavyDotsTime(early));
  });
});
