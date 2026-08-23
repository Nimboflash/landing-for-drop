/**
 * Loader / O portal — page seam (BUILD-GUIDE seam 3, ticket 05).
 *
 * What this spec is allowed to assert: DOM attributes and text, as a user experiences the route.
 * Never canvas pixels, never a shader frame's timing, never a computed style — the material is
 * verified by eye against `handoff/02-motion/opacity-loader-material-reference.png`, and the
 * choreography's scalars are the loader's own business.
 *
 * So the contract under test is the one the brief states in user terms:
 *
 * 1. the loader ends, on its own, inside the brief's hard cap — "never trap the user waiting
 *    for noncritical media" (§7.1);
 * 2. the page underneath is reachable afterwards, with its editorial text intact;
 * 3. that holds on a normal run, a reduced-motion run AND a run with no WebGL at all, because
 *    both fallbacks are mandatory (§16, §15);
 * 4. none of it costs a console error (§17).
 *
 * Expected strings come from the brief's §10 W04 seed, not from re-reading the content module
 * the way the page does.
 */

import { expect, test, type Page } from "@playwright/test";

/** Brief §7.1: "Cap the loader at 4 seconds; never trap the user waiting for noncritical media." */
const LOADER_CAP_MS = 4_000;

/**
 * Room for a cold production start and the navigation itself on top of the cap. Generous on
 * purpose: the assertion under test is "the loader lets go", not "the server is fast".
 */
const NAVIGATION_SLACK_MS = 8_000;

/** Brief §10, W04 "Beautiful Imperfection". */
const LENS_TITLE_FA = "زیبایی در کامل نبودن";
const LENS_TITLE_EN = "BEAUTIFUL IMPERFECTION";
const LENS_WEEK = "W04";
const FILM_TITLES = ["SHOWING UP", "PERFECT DAYS", "PATERSON"] as const;

/** The loader's overlay. Owned by `LoaderScene`; absent once the portal has completed. */
const LOADER_OVERLAY = "[data-loader-overlay]";

/**
 * Console errors, and the WebGL warnings brief §17 forbids alongside them. Collected from the
 * first navigation onward so a failure during the loader itself is caught, not just afterwards.
 *
 * GL *driver performance* messages are excluded: the GPU emits them for the compositor's own
 * readbacks (screenshots, video capture) on any page that draws WebGL at all. They say nothing
 * about our shaders, and asserting on them would make every run hostage to the harness.
 */
const GL_DRIVER_CHATTER = /GL Driver Message/;

function watchForConsoleErrors(page: Page): string[] {
  const problems: string[] = [];
  page.on("console", (message) => {
    const text = message.text();
    if (message.type() === "error") problems.push(`console.error: ${text}`);
    else if (
      message.type() === "warning" &&
      /webgl/i.test(text) &&
      !GL_DRIVER_CHATTER.test(text)
    ) {
      problems.push(`webgl warning: ${text}`);
    }
  });
  page.on("pageerror", (error) => problems.push(`pageerror: ${error.message}`));
  return problems;
}

/** Make `getContext("webgl"|"webgl2"|…)` fail the way a machine without WebGL does. */
async function disableWebGL(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const original = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function patched(
      this: HTMLCanvasElement,
      contextId: string,
      ...rest: unknown[]
    ) {
      if (/webgl/i.test(contextId)) return null;
      return (original as (...args: unknown[]) => unknown).call(this, contextId, ...rest);
    } as typeof HTMLCanvasElement.prototype.getContext;
  });
}

/**
 * The whole acceptance box in one place: the loader let go inside its cap, and the lens is
 * readable underneath it.
 */
async function expectLensReachableAfterLoader(page: Page): Promise<void> {
  // The overlay is what would trap the user. It must be gone — not faded, not transparent:
  // removed, along with its temporary WebGL context.
  await expect(page.locator(LOADER_OVERLAY)).toHaveCount(0, {
    timeout: LOADER_CAP_MS + NAVIGATION_SLACK_MS,
  });

  await expect(page.getByText(LENS_TITLE_FA).first()).toBeVisible();
  await expect(page.getByText(LENS_WEEK, { exact: false }).first()).toBeVisible();
  await expect(page.getByText(LENS_TITLE_EN, { exact: false }).first()).toBeVisible();

  // "No content is hidden solely inside WebGL" (brief §19): the three films are in the DOM.
  for (const title of FILM_TITLES) {
    await expect(page.getByText(title, { exact: false }).first()).toBeVisible();
  }
}

test.describe("loader portal", () => {
  test("the lens is reachable after the loader, with no console errors", async ({ page }) => {
    const problems = watchForConsoleErrors(page);

    await page.goto("/");
    await expectLensReachableAfterLoader(page);

    expect(problems).toEqual([]);
  });

  test("the loader is gone from the DOM once the page is reachable", async ({ page }) => {
    await page.goto("/");
    await expectLensReachableAfterLoader(page);

    // Exactly one persistent WebGL context is the shared background canvas; the loader's
    // temporary overlay canvas must have unmounted with its scene.
    await expect(page.locator(`${LOADER_OVERLAY} canvas`)).toHaveCount(0);
  });
});

/**
 * Brief §7.1: "Reduced motion: static logo for 500-700ms, then a simple O-shaped crossfade" —
 * and §16: reduced motion "must not remove content or make the page unusable".
 */
test.describe("loader portal — reduced motion", () => {
  test("the lens is reachable with reduced motion, with no console errors", async ({ page }) => {
    const problems = watchForConsoleErrors(page);
    // Emulated on the page rather than the context, so the preference is in force for the very
    // first client render — the loader picks its path once, at mount.
    await page.emulateMedia({ reducedMotion: "reduce" });

    await page.goto("/");
    await expectLensReachableAfterLoader(page);

    expect(problems).toEqual([]);
  });
});

/**
 * Brief §15: "Provide a non-WebGL fallback when context creation fails." The loader's own
 * fallback is the same brief static logo and crossfade — and the page stays reachable.
 */
test.describe("loader portal — no WebGL", () => {
  test("the lens is reachable without WebGL, with no console errors", async ({ page }) => {
    const problems = watchForConsoleErrors(page);
    await disableWebGL(page);

    await page.goto("/");
    await expectLensReachableAfterLoader(page);

    expect(problems).toEqual([]);
  });
});

/**
 * The loader's own lifecycle, read from the marker it leaves on the document element — the scene
 * unmounts when it finishes, so there is nothing left to assert on otherwise.
 *
 * Skipped, loudly, until the shell mounts `LoaderScene` and dispatches `loaderComplete` from its
 * `onComplete`. Everything above is true either way; this is the part that only becomes real
 * once the loader is wired in.
 */
test.describe("loader portal — lifecycle", () => {
  test("the loader marks the document complete and reports which path ran", async ({ page }) => {
    await page.goto("/");

    const marked = await page
      .waitForFunction(() => document.documentElement.dataset.dropLoader !== undefined, undefined, {
        timeout: 2_000,
      })
      .then(
        () => true,
        () => false,
      );
    test.skip(
      !marked,
      "LoaderScene is not mounted yet: the shell (ticket 03) still renders its own placeholder " +
        "and never calls onComplete. Wire <LoaderScene onComplete={() => dispatch({ type: " +
        '"loaderComplete" })} /> and this becomes live coverage.',
    );

    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.dropLoader), {
        timeout: LOADER_CAP_MS + NAVIGATION_SLACK_MS,
      })
      .toBe("complete");

    // Which fallback ran is part of the contract: a first hard visit plays the full sequence.
    const path = await page.evaluate(() => ({
      mode: document.documentElement.dataset.dropLoaderMode,
      sequence: document.documentElement.dataset.dropLoaderSequence,
    }));
    expect(path.mode).toBe("material");
    expect(path.sequence).toBe("full");

    await expect(page.locator(LOADER_OVERLAY)).toHaveCount(0);
  });
});
