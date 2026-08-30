import { test, expect, type Page } from "@playwright/test";

/**
 * Background liveness — a regression guard, not a look assertion.
 *
 * BUILD-GUIDE is explicit that WebGL *pixels are never asserted*: shader look is manual visual QA,
 * and shader *state* is proven at the scene-state seam. This spec does not break that rule. It never
 * asserts what the background looks like, only that it is **not frozen** — that the canvas output
 * differs between two scroll positions within the same mode.
 *
 * Why it exists: the canvas once handed each shader module a uniforms object that three.js had
 * already cloned away when it built the material, so every `update()` wrote to an orphaned copy and
 * every progress-driven uniform stayed at its initial value. Every scene still *rendered* — its
 * first frame, forever — so the whole suite stayed green while the pixel transitions, the thesis
 * glow, the mesh variants and the footer reveal were all dead. Nothing at seams 1-3 could catch it:
 * the reducer was correct, the DOM was correct, only the GPU was stale.
 *
 * A frozen background is therefore the one WebGL failure worth automating, and comparing a frame to
 * itself is the weakest assertion that catches it. If this fails, suspect the uniform plumbing in
 * `BackgroundCanvas`, not the shader that appears to be misbehaving.
 */

/** Scroll to a fraction of a scene's own pinned range and let the frame settle. */
async function scrollWithinScene(page: Page, sceneId: string, fraction: number): Promise<void> {
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
  // Two rendered frames: one for the trigger to report, one for the shader to draw it.
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
  await page.waitForTimeout(250);
}

/**
 * The background canvas as raw bytes. Compared only against itself — never against a baseline, so
 * there is no golden image to maintain and no shader look being asserted.
 *
 * Captured by screenshotting the composited element rather than `canvas.toDataURL()`: WebGL clears
 * its drawing buffer after compositing unless `preserveDrawingBuffer` is on, so `toDataURL` returns
 * a blank frame every time — which reads as "identical" and would fail this test even when the
 * background is perfectly alive. Turning that flag on to suit a test would cost real frame time in
 * production; screenshotting the composited result costs nothing.
 */
async function canvasFrame(page: Page): Promise<Buffer> {
  return page.locator("canvas").first().screenshot();
}

test.describe("the shared background is driven by scroll, not frozen on its first frame", () => {
  for (const { scene, from, to } of [
    // The pixel mosaic is the sharpest probe: cells flip as progress climbs.
    { scene: "pixelA", from: 0.1, to: 0.75 },
    // The thesis glow breathes with progress across the same mode.
    { scene: "thesis", from: 0.1, to: 0.85 },
    // The footer light horizon reveals and drifts with scroll.
    { scene: "footer", from: 0.1, to: 0.85 },
  ]) {
    test(`${scene} renders a different frame as its progress advances`, async ({ page }) => {
      await page.goto("/");
      // Past the loader's hard cap, so the shared canvas owns the screen.
      await page.waitForTimeout(4_500);

      await scrollWithinScene(page, scene, from);
      const early = await canvasFrame(page);

      await scrollWithinScene(page, scene, to);
      const late = await canvasFrame(page);

      expect(early.byteLength).toBeGreaterThan(0);
      expect(
        late.equals(early),
        `the ${scene} background produced an identical frame at progress ${from} and ${to}. ` +
          "The canvas is very likely writing uniforms to an object the material does not read.",
      ).toBe(false);
    });
  }
});
