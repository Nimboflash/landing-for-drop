import { expect, test as base, type Page } from "@playwright/test";

import { DPR_CAP, DPR_CAP_RANGE, type QualityTier } from "../../src/lib/performance/quality-tier";

/**
 * Resource hygiene — page seam (BUILD-GUIDE seam 3), ticket 15 box 7, brief §17.
 *
 * Brief §17 ends with a single sentence that this file exists to defend:
 *
 *   > No console errors, WebGL warnings, or accumulating ScrollTriggers.
 *
 * plus "Cap texture size based on quality tier", "Dispose geometries, materials, and textures on
 * unmount", "Avoid layout shift after fonts load", and §15's "Provide a non-WebGL fallback when
 * context creation fails". None of those are visible in a screenshot, and none of them are shader
 * *look*: they are countable facts about the page's resources. That is what makes them automatable
 * at the top seam while 60fps stays a `[manual]` box.
 *
 * ## What this file is allowed to read
 *
 * Attributes and text, as everywhere else at this seam — `data-webgl`, `data-quality-tier`,
 * `data-scene`, `data-active-scene`, `data-loader-overlay` — plus three things that are neither
 * styles nor pixels and have no attribute to hide behind:
 *
 * 1. **How many `<canvas>` elements exist, and how many WebGL contexts are still alive.** Counted
 *    by wrapping `HTMLCanvasElement.getContext` from an init script, then asking each context
 *    `isContextLost()`. Element counts and a browser API's own answer — not a look assertion.
 * 2. **The canvas backing-store size versus its CSS size.** `canvas.width / canvas.clientWidth`
 *    IS the renderer's applied pixel ratio; there is no other way to observe the DPR cap from
 *    outside. Both are element geometry, not a computed style and not an inline transform, and
 *    nothing here reads a single pixel of the drawing buffer.
 * 3. **`layout-shift` PerformanceObserver entries.** The browser's own CLS accounting.
 *
 * Never asserted here: what the background looks like, GSAP timeline internals, uniform values,
 * React tree shape, CSS class names, or an absolute scroll-progress threshold.
 *
 * ## What this file deliberately does NOT claim
 *
 * Frame rate. A Playwright run under a shared, contended machine measures the harness, not the
 * experience, so "60fps on capable desktop / ≥30fps on mid-range mobile" stays `[manual]` — see
 * `docs/qa/performance-notes.md` for the procedure and the hardware it must be named against.
 * Text contrast over the live shaders is `[manual]` for the same reason in reverse: no tool at
 * this seam can sample what the GPU painted behind a paragraph.
 */

/* ------------------------------------------------------ expectations, from the source docs */

/** Brief §6, "Master Experience Sequence" — the ten scenes, in order. */
const SCENE_ORDER_FROM_BRIEF = [
  "loader",
  "thesis",
  "menu",
  "gridStatement",
  "pixelA",
  "films",
  "pixelB",
  "tracks",
  "artPieces",
  "footer",
] as const;

/** Both routes render the same lens template (brief §5). */
const LENS_ROUTES = ["/", "/lens/beautiful-imperfection"] as const;

/** Brief §10, W04 seed — proof the page still has its content after a context loss. */
const LENS_TITLE_FA = "زیبایی در کامل نبودن";
const LENS_WEEK = "W04";

/**
 * Brief §14, "Quality tiers", written out by hand: "High: … DPR capped at 1.75-2 … Medium: DPR
 * capped at 1.5 … Low: DPR 1." The runtime assertions read {@link DPR_CAP} from the module, as
 * the ticket asks; these literals exist so a silent change to that module cannot quietly redefine
 * what the test is testing.
 */
const BRIEF_DPR_CAP: Readonly<Record<QualityTier, number>> = { high: 2, medium: 1.5, low: 1 };
const BRIEF_HIGH_TIER_BAND: readonly [number, number] = [1.75, 2];

/** Brief §17, "Suggested launch targets": "CLS: under 0.1." */
const BRIEF_CLS_TARGET = 0.1;

/**
 * Brief §14, "Shared canvas state" — the seven background modes, transcribed from the brief's own
 * `BackgroundMode` union rather than imported, so this stays an expectation and not a mirror of
 * the implementation's type. Used only to prove the fallback ground is still publishing a real
 * mode after the GPU is gone; which scene maps to which mode is seam 2's job, not this file's.
 */
const BRIEF_BACKGROUND_MODES = [
  "offWhiteGlow",
  "greenGrid",
  "pixelA",
  "wavyDots",
  "pixelB",
  "monoMesh",
  "footerLight",
] as const;

/**
 * Backing store and CSS box are both integers, so their ratio lands a hair off the ratio the
 * renderer was configured with. Wide enough to absorb that rounding, far too narrow to hide a
 * tier's worth of pixels (the closest two caps are 1.5 and 2).
 */
const DPR_ROUNDING_TOLERANCE = 0.02;

/** Brief §7.1 caps the loader at 4s; a cold production start needs room on top of that. */
const LOADER_SETTLE_TIMEOUT_MS = 20_000;

/**
 * GPU *driver performance* chatter. The compositor emits it for its own readbacks (screenshots,
 * video capture) on any page that draws WebGL at all, so it says nothing about our shaders and
 * asserting on it would make every run hostage to the harness. Same exclusion `loader.spec.ts`
 * already makes, for the same reason.
 */
const GL_DRIVER_CHATTER = /GL Driver Message/;

/**
 * `THREE.Clock: This module has been deprecated` is printed by `@react-three/fiber`'s own store
 * (`node_modules/@react-three/fiber/dist/events-*.esm.js`, `clock: new THREE.Clock()`), not by
 * anything in `src/`. It is a library deprecation notice rather than a WebGL warning, and it
 * cannot be silenced without changing a dependency, so it is excluded explicitly — recorded here
 * rather than swallowed by a loose filter, so the exclusion stays visible.
 */
const DEPENDENCY_DEPRECATION_CHATTER = /THREE\.Clock: This module has been deprecated/;

/* ------------------------------------------------------------------------------- fixtures */

/**
 * Brief §17: "No console errors, WebGL warnings". Both are collected from the first navigation
 * and asserted empty when the test ends, so every test in this file carries the standing
 * assertion whether or not it mentions it.
 */
const test = base.extend<{ consoleProblems: string[] }>({
  consoleProblems: [
    async ({ page }, use) => {
      const problems: string[] = [];
      page.on("console", (message) => {
        const text = message.text();
        if (message.type() === "error") problems.push(`console.error: ${text}`);
        else if (
          message.type() === "warning" &&
          /webgl|three/i.test(text) &&
          !GL_DRIVER_CHATTER.test(text) &&
          !DEPENDENCY_DEPRECATION_CHATTER.test(text)
        ) {
          problems.push(`webgl warning: ${text}`);
        }
      });
      page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
      await use(problems);
      expect(problems, "brief §17: no console errors and no WebGL warnings").toEqual([]);
    },
    { auto: true },
  ],
});

test.describe.configure({ timeout: 150_000 });

/* -------------------------------------------------------------------------------- helpers */

/**
 * Wrap `HTMLCanvasElement.getContext` before any page script runs, so every WebGL context the
 * page creates — the capability probe, the loader's temporary renderer, the persistent
 * background — is accounted for.
 *
 * The report answers the only question that matters for disposal: is the context still **alive**
 * (`isContextLost()` says no), and is its canvas still **in the document**? A renderer that was
 * unmounted but never disposed shows up here as a live context on a detached canvas, which
 * counting `<canvas>` elements alone would miss entirely.
 */
async function instrumentWebGLContexts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    type Entry = { id: number; type: string; gl: WebGLRenderingContext; canvas: HTMLCanvasElement };
    const entries: Entry[] = [];
    let nextId = 0;

    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function patched(
      this: HTMLCanvasElement,
      contextId: string,
      ...rest: unknown[]
    ) {
      const context = (original as (...args: unknown[]) => unknown).call(this, contextId, ...rest);
      if (/webgl/i.test(contextId) && context) {
        // `getContext` returns the SAME context object on repeated calls, so identity dedupes.
        const known = entries.some((entry) => entry.gl === context);
        if (!known) {
          entries.push({
            id: nextId++,
            type: contextId,
            gl: context as WebGLRenderingContext,
            canvas: this,
          });
        }
      }
      return context as never;
    } as typeof HTMLCanvasElement.prototype.getContext;

    (window as unknown as Record<string, unknown>).__dropWebGLContexts = () =>
      entries.map((entry) => ({
        id: entry.id,
        type: entry.type,
        lost: entry.gl.isContextLost(),
        attached: entry.canvas.isConnected,
      }));
  });
}

type ContextRecord = { id: number; type: string; lost: boolean; attached: boolean };

type ResourceSnapshot = {
  /** `<canvas>` elements currently in the document. */
  canvasElements: number;
  /** Every WebGL context the page has ever created, with its current liveness. */
  contexts: ContextRecord[];
  /** Contexts that are neither lost nor detached — the ones actually holding GPU memory. */
  liveContexts: number;
  /** Whether the loader overlay is still mounted. */
  loaderOverlays: number;
};

async function readResources(page: Page): Promise<ResourceSnapshot> {
  return page.evaluate(() => {
    const report = (window as unknown as { __dropWebGLContexts?: () => ContextRecordShape[] })
      .__dropWebGLContexts;
    type ContextRecordShape = { id: number; type: string; lost: boolean; attached: boolean };
    const contexts = report ? report() : [];
    return {
      canvasElements: document.querySelectorAll("canvas").length,
      contexts,
      liveContexts: contexts.filter((entry) => !entry.lost && entry.attached).length,
      loaderOverlays: document.querySelectorAll("[data-loader-overlay]").length,
    };
  });
}

/** Two rendered frames: one for the scroll to be observed, one for the render it causes. */
async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

/** The loader is time-based (brief §7.1); every test waits for its own published hand-over. */
async function waitPastLoader(page: Page): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.dropLoader), {
      timeout: LOADER_SETTLE_TIMEOUT_MS,
      message: "the loader never reported itself complete",
    })
    .toBe("complete");
  await expect(page.locator("[data-loader-overlay]")).toHaveCount(0);
}

async function openLens(page: Page, route: string): Promise<void> {
  const response = await page.goto(route);
  expect(response?.status(), `${route} must be served`).toBe(200);
  await waitPastLoader(page);
}

/**
 * Scroll into a scene by that section's own live geometry, never by a fraction of the document.
 * Positions are inputs, never expectations — no absolute progress threshold is asserted anywhere
 * in this file.
 */
async function scrollIntoScene(page: Page, sceneId: string, fraction: number): Promise<void> {
  await page.evaluate(
    ({ id, f }) => {
      const section = document.querySelector(`[data-scene="${id}"]`) as HTMLElement | null;
      if (section === null) throw new Error(`no section for scene "${id}"`);
      const top = section.getBoundingClientRect().top + window.scrollY;
      const usable = Math.max(0, section.offsetHeight - window.innerHeight);
      window.scrollTo({ top: top + usable * f, behavior: "instant" as ScrollBehavior });
    },
    { id: sceneId, f: fraction },
  );
  await settle(page);
}

/** Walk every scene forward, then every scene back — the full pass, both directions. */
async function fullScrollPass(page: Page): Promise<void> {
  for (const sceneId of SCENE_ORDER_FROM_BRIEF) {
    for (const fraction of [0, 0.5, 1]) await scrollIntoScene(page, sceneId, fraction);
  }
  for (const sceneId of [...SCENE_ORDER_FROM_BRIEF].reverse()) {
    for (const fraction of [1, 0.5, 0]) await scrollIntoScene(page, sceneId, fraction);
  }
}

type SceneDiagnosticsSnapshot = { scrollTriggerCount: number; sceneId: string };

/**
 * The dev-build diagnostics object (BUILD-GUIDE's sanctioned escape hatch), read exactly as
 * `lens-page.spec.ts` reads it. `null` means the block was dead-code-eliminated, which is the
 * correct state of a normal production bundle.
 */
async function readDiagnostics(page: Page): Promise<SceneDiagnosticsSnapshot | null> {
  return page.evaluate(() => {
    const diagnostics = (
      window as unknown as {
        __dropSceneDiagnostics?: { scrollTriggerCount: number; sceneId: string };
      }
    ).__dropSceneDiagnostics;
    if (!diagnostics) return null;
    return {
      scrollTriggerCount: diagnostics.scrollTriggerCount,
      sceneId: diagnostics.sceneId,
    };
  });
}

/* ------------------------------------------------------- 1. one persistent WebGL context */

for (const route of LENS_ROUTES) {
  test(`${route} leaves exactly one live WebGL context once the loader hands over`, async ({
    page,
  }) => {
    await instrumentWebGLContexts(page);
    await openLens(page, route);
    await settle(page);

    const afterLoader = await readResources(page);

    // Brief §12 / BUILD-GUIDE: "One shared WebGL canvas … never mount a second persistent canvas."
    expect(afterLoader.loaderOverlays, "the loader overlay must be unmounted").toBe(0);
    expect(afterLoader.canvasElements, "exactly one <canvas> survives the loader").toBe(1);
    expect(afterLoader.liveContexts, "exactly one WebGL context stays alive").toBe(1);

    // The surviving canvas is the shared background's, not an orphan.
    await expect(page.locator("[data-background-canvas] canvas")).toHaveCount(1);

    // Disposal, not just detachment: brief §17, "Dispose geometries, materials, and textures on
    // unmount". The loader's renderer and the capability probe both created a context; every one
    // of them except the survivor must be reported lost by the browser itself.
    const leaked = afterLoader.contexts.filter(
      (context) => !context.lost && !context.attached,
    );
    expect(leaked, "no WebGL context may outlive its canvas").toEqual([]);
    expect(
      afterLoader.contexts.length,
      "the loader's temporary context must have existed and been released",
    ).toBeGreaterThan(1);
  });
}

test("a full scroll pass does not create a second WebGL context", async ({ page }) => {
  await instrumentWebGLContexts(page);
  await openLens(page, "/");

  const before = await readResources(page);
  await fullScrollPass(page);
  const after = await readResources(page);

  // Every one of the seven background modes has been on screen by now. Modes are programs inside
  // one renderer, so the context count must not have moved.
  expect(after.canvasElements, "no scene may mount a canvas of its own").toBe(1);
  expect(after.liveContexts, "mode changes must not create contexts").toBe(1);
  expect(after.contexts.length, "no new context was created by any mode").toBe(
    before.contexts.length,
  );
});

/* --------------------------------------------- 2. ScrollTriggers across route round trips */

test("ScrollTriggers do not accumulate across repeated route round trips", async ({ page }) => {
  await openLens(page, "/");
  const before = await readDiagnostics(page);

  if (before === null) {
    test.info().annotations.push({
      type: "note",
      description:
        "dev-only scene diagnostics are stripped from this build, so the ScrollTrigger count " +
        "could not be read. Re-run against the dev server (PORT=3000) or a production build " +
        "started with NEXT_PUBLIC_DROP_DIAGNOSTICS=1 to exercise the count. The behavioural " +
        "proxy — identical forward and reverse journeys after a route round trip — is asserted " +
        "in journey.spec.ts.",
    });
    test.skip(true, "scene diagnostics are not exposed by this build");
    return;
  }

  // Brief §6 gives ten scenes; one trigger each is the floor, so a count below that would mean
  // the triggers were never built rather than that they were cleaned up.
  expect(before.scrollTriggerCount).toBeGreaterThanOrEqual(SCENE_ORDER_FROM_BRIEF.length);

  // Three round trips, not one: a leak of a single trigger per mount is invisible in a single
  // comparison if the first mount is the one that leaks, and grows linearly here.
  const counts: number[] = [before.scrollTriggerCount];
  for (let trip = 0; trip < 3; trip += 1) {
    await openLens(page, "/lens/beautiful-imperfection");
    await page.goBack();
    await waitPastLoader(page);
    await settle(page);
    const snapshot = await readDiagnostics(page);
    expect(snapshot, "diagnostics must survive the round trip").not.toBeNull();
    counts.push(snapshot!.scrollTriggerCount);
  }

  expect(
    counts,
    `brief §17: no accumulating ScrollTriggers — counts across round trips were ${counts.join(", ")}`,
  ).toEqual(counts.map(() => before.scrollTriggerCount));
});

/* ---------------------------------------------------------------------- 3. the DPR cap */

/** The module's caps must still be the brief's caps; the runtime assertions read the module. */
test("the tier DPR caps are the brief's caps", async () => {
  expect(DPR_CAP.high).toBeGreaterThanOrEqual(BRIEF_HIGH_TIER_BAND[0]);
  expect(DPR_CAP.high).toBeLessThanOrEqual(BRIEF_HIGH_TIER_BAND[1]);
  expect(DPR_CAP_RANGE.high).toEqual([...BRIEF_HIGH_TIER_BAND]);
  expect(DPR_CAP.medium).toBe(BRIEF_DPR_CAP.medium);
  expect(DPR_CAP.low).toBe(BRIEF_DPR_CAP.low);
});

type PixelRatioReading = {
  tier: string | null;
  backingWidth: number;
  cssWidth: number;
  devicePixelRatio: number;
};

async function readPixelRatio(page: Page): Promise<PixelRatioReading> {
  return page.evaluate(() => {
    const root = document.querySelector("[data-background-canvas]");
    const canvas = root?.querySelector("canvas") as HTMLCanvasElement | null;
    if (!canvas) throw new Error("no background canvas to measure");
    return {
      tier: root?.getAttribute("data-quality-tier") ?? null,
      backingWidth: canvas.width,
      cssWidth: canvas.clientWidth,
      devicePixelRatio: window.devicePixelRatio,
    };
  });
}

function assertPixelRatioWithinCap(reading: PixelRatioReading): number {
  expect(
    reading.tier,
    "the canvas must publish which tier it resolved",
  ).toMatch(/^(high|medium|low)$/);
  const tier = reading.tier as QualityTier;
  const cap = DPR_CAP[tier];

  expect(reading.cssWidth, "the canvas must have a CSS box to measure against").toBeGreaterThan(0);
  const applied = reading.backingWidth / reading.cssWidth;

  // Brief §14, "Never use: … Unbounded DPR."
  expect(
    applied,
    `tier "${tier}" renders at ${applied.toFixed(3)}x, above its ${cap}x cap`,
  ).toBeLessThanOrEqual(cap + DPR_ROUNDING_TOLERANCE);
  // The floor the module documents: never render below 1x, whatever the device reports.
  expect(applied, "the renderer must never drop below 1x").toBeGreaterThanOrEqual(
    1 - DPR_ROUNDING_TOLERANCE,
  );
  // And never above the device's own ratio — a cap must not become an upsample.
  expect(applied, "the renderer must not exceed the device pixel ratio").toBeLessThanOrEqual(
    reading.devicePixelRatio + DPR_ROUNDING_TOLERANCE,
  );
  return applied;
}

test("the renderer never exceeds the DPR cap of the tier it published", async ({ page }) => {
  await openLens(page, "/");
  const reading = await readPixelRatio(page);
  const applied = assertPixelRatioWithinCap(reading);
  test.info().annotations.push({
    type: "dpr",
    description: `tier=${reading.tier} devicePixelRatio=${reading.devicePixelRatio} applied=${applied.toFixed(3)}`,
  });
});

test.describe("on a high-density panel", () => {
  // 3x is the densest panel the brief's mobile guidance contemplates, and above every tier cap —
  // so whatever tier this machine resolves, the cap has to bite here or DPR is unbounded.
  test.use({ deviceScaleFactor: 3 });

  test("the cap actually bites rather than passing by luck", async ({ page }) => {
    await openLens(page, "/");
    const reading = await readPixelRatio(page);
    expect(
      reading.devicePixelRatio,
      "this test is meaningless unless the browser really reports 3x",
    ).toBeGreaterThan(2);

    const applied = assertPixelRatioWithinCap(reading);
    expect(
      applied,
      `a 3x panel must be capped, but the renderer applied ${applied.toFixed(3)}x`,
    ).toBeLessThan(reading.devicePixelRatio - 0.5);
  });
});

/* -------------------------------------------------------------- 4. WebGL context loss */

/** Force a real context loss through the browser's own extension. */
async function loseWebGLContext(page: Page): Promise<"lost" | "no-extension" | "no-context"> {
  return page.evaluate(() => {
    const canvas = document.querySelector(
      "[data-background-canvas] canvas",
    ) as HTMLCanvasElement | null;
    if (!canvas) return "no-context" as const;
    const gl = (canvas.getContext("webgl2") ?? canvas.getContext("webgl")) as
      | WebGLRenderingContext
      | null;
    if (!gl) return "no-context" as const;
    const extension = gl.getExtension("WEBGL_lose_context") as {
      loseContext: () => void;
      restoreContext: () => void;
    } | null;
    if (!extension) return "no-extension" as const;
    (window as unknown as Record<string, unknown>).__dropLoseContext = extension;
    extension.loseContext();
    return "lost" as const;
  });
}

test("a lost WebGL context degrades to the styled static background and stays usable", async ({
  page,
}) => {
  await instrumentWebGLContexts(page);
  await openLens(page, "/");
  await expect(page.locator("[data-background-canvas]")).toHaveAttribute("data-webgl", "active");

  const outcome = await loseWebGLContext(page);
  if (outcome !== "lost") {
    test.skip(true, `WEBGL_lose_context is unavailable in this browser (${outcome})`);
    return;
  }

  // Brief §15: "Provide a non-WebGL fallback when context creation fails." The canvas publishes
  // which ground is painted; the styled static background is the fallback, not a blank frame.
  await expect(page.locator("[data-background-canvas]")).toHaveAttribute(
    "data-webgl",
    "fallback",
    { timeout: 5_000 },
  );

  // Not blank: the editorial content is untouched, because it never lived on the GPU.
  await expect(page.locator("[data-lens-title]")).toHaveText(LENS_TITLE_FA);
  await expect(page.locator("[data-lens-label]")).toContainText(LENS_WEEK);
  await expect(page.locator("[data-scene]")).toHaveCount(SCENE_ORDER_FROM_BRIEF.length);

  // Not broken: scroll still drives the scene machine with the GPU gone.
  const backgroundLayer = page.locator("[data-background-canvas]");
  const modeAtFilms = await (async () => {
    await scrollIntoScene(page, "films", 0.5);
    await expect(page.locator("[data-active-scene]").first()).toHaveAttribute(
      "data-active-scene",
      "films",
    );
    return backgroundLayer.getAttribute("data-background-mode");
  })();
  const modeAtFooter = await (async () => {
    await scrollIntoScene(page, "footer", 0.5);
    await expect(page.locator("[data-active-scene]").first()).toHaveAttribute(
      "data-active-scene",
      "footer",
    );
    return backgroundLayer.getAttribute("data-background-mode");
  })();

  // Not blank, and not frozen: the styled ground is still being driven. Both readings must be
  // real brief §14 modes, and they must DIFFER — a fallback that stopped tracking the journey
  // would report the same mode at both ends of the page, and a blank layer would report none.
  // Ordinal only: which mode belongs to which scene is asserted at seam 2, not here.
  expect(BRIEF_BACKGROUND_MODES).toContain(modeAtFilms);
  expect(BRIEF_BACKGROUND_MODES).toContain(modeAtFooter);
  expect(
    modeAtFooter,
    "with the GPU gone the fallback ground must still follow the scene machine",
  ).not.toBe(modeAtFilms);

  // And it recovers when the browser gives the context back, rather than staying degraded.
  await page.evaluate(() => {
    (
      window as unknown as { __dropLoseContext?: { restoreContext: () => void } }
    ).__dropLoseContext?.restoreContext();
  });
  await expect(page.locator("[data-background-canvas]")).toHaveAttribute("data-webgl", "active", {
    timeout: 10_000,
  });
  const restored = await readResources(page);
  expect(restored.canvasElements, "recovery must not add a canvas").toBe(1);
  expect(restored.liveContexts, "recovery must not add a context").toBe(1);

  // The console-error fixture asserts brief §17's other half when this test tears down.
});

/* ------------------------------------------------- 5. console hygiene over a full pass */

test("a full scroll pass produces no console errors and no WebGL warnings", async ({
  page,
  consoleProblems,
}) => {
  await openLens(page, "/");
  await fullScrollPass(page);

  // Asserted here as well as in the fixture so the failure names the pass that produced it.
  expect(consoleProblems, "the whole journey must stay quiet in both directions").toEqual([]);
});

/* ------------------------------------------------------ 6. layout shift after fonts load */

/**
 * Record every `layout-shift` entry the browser reports, plus the moment `document.fonts.ready`
 * settled. Buffered, so entries from before the observer was created are included.
 */
async function observeLayoutShifts(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const host = window as unknown as Record<string, unknown>;
    host.__dropLayoutShifts = null;
    host.__dropFontsReadyAt = null;
    try {
      const supported = PerformanceObserver.supportedEntryTypes ?? [];
      if (!supported.includes("layout-shift")) return;
      const shifts: { startTime: number; value: number }[] = [];
      host.__dropLayoutShifts = shifts;
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries() as (PerformanceEntry & {
          value: number;
          hadRecentInput: boolean;
        })[]) {
          if (entry.hadRecentInput) continue;
          shifts.push({ startTime: entry.startTime, value: entry.value });
        }
      }).observe({ type: "layout-shift", buffered: true });
    } catch {
      host.__dropLayoutShifts = null;
    }
    document.fonts?.ready.then(() => {
      host.__dropFontsReadyAt = performance.now();
    });
  });
}

test("no layout shift is recorded after the fonts load", async ({ page }) => {
  await observeLayoutShifts(page);
  await openLens(page, "/");
  // The loader hand-over is the last structural change on the page; give it room to land before
  // reading, so a shift it caused would be recorded rather than raced past.
  await page.waitForTimeout(1_500);
  await settle(page);

  const measurement = await page.evaluate(() => {
    const host = window as unknown as {
      __dropLayoutShifts?: { startTime: number; value: number }[] | null;
      __dropFontsReadyAt?: number | null;
    };
    return {
      shifts: host.__dropLayoutShifts ?? null,
      fontsReadyAt: host.__dropFontsReadyAt ?? null,
    };
  });

  if (measurement.shifts === null) {
    test.info().annotations.push({
      type: "note",
      description:
        "this browser does not implement the layout-shift PerformanceObserver entry, so the CLS " +
        "proxy could not run here; the Chromium project and scripts/lighthouse-audit.mjs cover it.",
    });
    test.skip(true, "layout-shift entries are not supported in this browser");
    return;
  }

  expect(measurement.fontsReadyAt, "document.fonts.ready must have settled").not.toBeNull();
  const fontsReadyAt = measurement.fontsReadyAt as number;

  const total = measurement.shifts.reduce((sum, shift) => sum + shift.value, 0);
  const afterFonts = measurement.shifts
    .filter((shift) => shift.startTime >= fontsReadyAt)
    .reduce((sum, shift) => sum + shift.value, 0);

  test.info().annotations.push({
    type: "cls",
    description: `total=${total.toFixed(4)} afterFonts=${afterFonts.toFixed(4)} entries=${measurement.shifts.length}`,
  });

  // Brief §17: "Avoid layout shift after fonts load", and the launch target "CLS: under 0.1".
  expect(
    afterFonts,
    `layout shifted by ${afterFonts.toFixed(4)} after the fonts loaded`,
  ).toBeLessThan(BRIEF_CLS_TARGET);
  expect(total, `total layout shift was ${total.toFixed(4)}`).toBeLessThan(BRIEF_CLS_TARGET);
});
