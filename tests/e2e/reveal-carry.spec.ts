/**
 * The post-loader carry — shell seam.
 *
 * When the loader lets go, `SmoothScrollProvider` carries the document from the top into the
 * first readable scene. The scenes above it are a full screen of ground with no text in them, so
 * if the carry does not land, the reader is looking at an empty page and has to guess that
 * scrolling will help.
 *
 * Two halves, and they pull against each other — which is why both are pinned here:
 *
 * 1. the carry LANDS. It stalled on an iPhone 17 at 219px of an 856px journey, leaving the first
 *    line of text 607px below the fold, because the guard below mistook the carry's own motion,
 *    reported late by iOS, for somebody else moving the page.
 * 2. the guard still WORKS. A scroll the carry did not perform — a restored offset, a deep link,
 *    a harness — must hand the document straight back, or a reader who refreshes halfway down the
 *    page gets quietly dragged to the hero.
 *
 * Honest about its reach: headless WebKit applies programmatic scroll synchronously, so it does
 * NOT reproduce the report lag that caused the stall — a real device does. These tests pin the
 * contract on both engines; they are not a reproduction of the defect. The device check is
 * `[manual]`: open the lens on a phone, do not touch the screen, and read the first thing shown.
 */

import { expect, test, type Page } from "@playwright/test";

/** Brief §7.1 caps the loader at 4s; the rest is room for a cold start. */
const SETTLE_TIMEOUT_MS = 14_000;

/** Somewhere no carry would ever be heading: several scenes down. */
const FOREIGN_OFFSET_PX = 4_000;

/** The carry's tween is 0.8s; this is comfortably past it plus its 250ms delay. */
const CARRY_WINDOW_MS = 2_000;

async function loaderDone(page: Page): Promise<void> {
  await expect
    .poll(
      () => page.evaluate(() => document.documentElement.dataset.dropLoader),
      {
        timeout: SETTLE_TIMEOUT_MS,
      },
    )
    .toBe("complete");
}

/** Where the document comes to rest, once two consecutive reads agree. */
async function restingScroll(page: Page): Promise<number> {
  let last = -1;
  for (let i = 0; i < 40; i++) {
    const now = await page.evaluate(() => Math.round(window.scrollY));
    if (now === last) return now;
    last = now;
    await page.waitForTimeout(250);
  }
  return last;
}

test.describe("the post-loader carry", () => {
  test("lands the reader on text rather than on empty ground", async ({
    page,
  }) => {
    await page.goto("/");
    await loaderDone(page);
    await restingScroll(page);

    /*
     * Asserted as the reader experiences it — is there anything to read on the screen — rather
     * than as a scroll offset, which would only restate the implementation's own arithmetic.
     */
    const firstText = await page.evaluate(() => {
      const visible = [...document.querySelectorAll("h1,h2,p")]
        .map((element) => ({
          y: element.getBoundingClientRect().y,
          opacity: Number.parseFloat(getComputedStyle(element).opacity),
          text: (element.textContent ?? "").trim(),
        }))
        .filter((entry) => entry.opacity > 0.05 && entry.text.length > 0)
        .sort((a, b) => a.y - b.y);
      return { top: visible[0] ?? null, viewport: window.innerHeight };
    });

    expect(
      firstText.top,
      "nothing readable anywhere on the page",
    ).not.toBeNull();
    expect(
      firstText.top!.y,
      `the first readable line sits ${Math.round(firstText.top!.y)}px down a ${firstText.viewport}px screen`,
    ).toBeLessThan(firstText.viewport);
    expect(firstText.top!.y).toBeGreaterThan(-firstText.viewport);
  });

  test("yields to a scroll it did not perform", async ({ page }) => {
    await page.goto("/");
    await loaderDone(page);

    // Straight into the carry's window: whether this lands before the tween starts or during it,
    // the contract is the same — the page stays where it was put.
    await page.evaluate(
      (offset) => window.scrollTo(0, offset),
      FOREIGN_OFFSET_PX,
    );
    await page.waitForTimeout(CARRY_WINDOW_MS);

    const landed = await page.evaluate(() => Math.round(window.scrollY));
    expect(
      landed,
      `the carry dragged the document back from ${FOREIGN_OFFSET_PX} to ${landed}`,
    ).toBeGreaterThan(FOREIGN_OFFSET_PX / 2);
  });
});
