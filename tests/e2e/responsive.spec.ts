import { expect, test as base, type Page } from "@playwright/test";

/**
 * Page seam (BUILD-GUIDE seam 3) for the brief §21 **Viewports** row, asserted against §15
 * ("Responsive Behavior").
 *
 * ## The four viewports
 *
 * `375x812`, `768x1024`, `1024x768`, `1440x900` — the brief's own list, not a set of convenient
 * ones. They land in the three bands §15 defines: mobile below 768, tablet 768–1199, desktop 1200
 * and wider. Note `1024x768` is a TABLET width by that table even though it is a landscape size.
 *
 * ## What this file asserts, and how
 *
 * Data attributes and text, as everywhere at this seam — plus **element geometry** for the three
 * §15 requirements that are inherently geometric: which side of the frame a column is on, whether
 * a row is one column or two, and whether the document scrolls sideways. Those are read as
 * bounding boxes and `scrollWidth`/`clientWidth`, never as computed styles: the assertion is
 * "the poster is to the right of the information", which is what the brief says and what a reader
 * sees, not "`grid-template-columns` is `3fr 2fr`", which would only re-state the stylesheet.
 *
 * Nothing here reads an inline transform or opacity, and no scroll-progress threshold is asserted.
 *
 * ## Both projects
 *
 * The suite runs under `chromium` and `mobile-safari`, which is deliberate: it gives the QA
 * matrix's Browsers row a WebKit pass over the same responsive expectations. Under
 * `mobile-safari` the viewport is resized to each of the four sizes while the context keeps its
 * touch/mobile emulation — so the desktop rows are also a check that nothing depends on a mouse.
 */

/* ------------------------------------------------------ expectations, from the source docs */

/** Brief §6, "Master Experience Sequence". */
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

type Band = "mobile" | "tablet" | "desktop";

/** Brief §21, "Viewports", banded by the §15 breakpoints. */
const VIEWPORTS: ReadonlyArray<{ label: string; width: number; height: number; band: Band }> = [
  { label: "375x812", width: 375, height: 812, band: "mobile" },
  { label: "768x1024", width: 768, height: 1024, band: "tablet" },
  { label: "1024x768", width: 1024, height: 768, band: "tablet" },
  { label: "1440x900", width: 1440, height: 900, band: "desktop" },
];

/**
 * Brief §15: "Five-position music coverflow where space allows" on desktop, "Three-position
 * coverflow" on tablet. Mobile is specified as swipe-first and is given no number.
 *
 * §15 wrote that mobile line as "Tracks are swipe-first, with visible arrow controls", and §7.8
 * as "Left/right arrow controls are available and keyboard accessible". An explicit ART DIRECTION
 * has since removed the arrow buttons from the composition, so the citation no longer describes
 * anything in the DOM. What it was asking for — a way to step the field that is not the swipe
 * itself — is now carried by a tap on an off-centre case and by the carousel's roving-tabindex
 * keyboard path (ArrowLeft / ArrowRight / Home / End on the `[data-tracks-carousel]` group), both
 * reaching the same reducer actions the arrows did. Mobile is still asserted as "fewer than the
 * desktop field, but a neighbour still peeks on each side to advertise the gesture" rather than
 * against an invented figure — with the arrows gone, that peeking neighbour is also the only
 * thing advertising the gesture, which makes the range below load-bearing rather than decorative.
 */
const COVERFLOW_POSITIONS: Record<"desktop" | "tablet", number> = { desktop: 5, tablet: 3 };
const MOBILE_COVERFLOW_RANGE = { min: 2, max: 3 };

/**
 * How far from the first track the carousel is advanced before the field is counted. The field
 * cannot show two neighbours on the low side while the active track IS the first one, so the
 * five-position claim is only meaningful away from the ends. W04 ships eleven tracks, so index 3
 * has room on both sides at every band.
 */
const COUNT_FIELD_AT_INDEX = 3;

/** Geometry tolerance, in px. Absorbs sub-pixel layout and the scenes' restrained parallax. */
const EPSILON = 2;

/* ------------------------------------------------------------------------------- fixtures */

/** Brief §17: "No console errors, WebGL warnings, or accumulating ScrollTriggers." */
const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
      await use(errors);
      expect(errors, "the page must produce no console errors").toEqual([]);
    },
    { auto: true },
  ],
});

/* -------------------------------------------------------------------------------- helpers */

type Box = { x: number; y: number; width: number; height: number };

async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

async function scrollToRatio(page: Page, ratio: number): Promise<void> {
  await page.evaluate((value) => {
    const range = document.documentElement.scrollHeight - window.innerHeight;
    window.scrollTo({ top: range * value, behavior: "instant" as ScrollBehavior });
  }, ratio);
  await settle(page);
}

async function currentRatio(page: Page): Promise<number> {
  return page.evaluate(() => {
    const range = document.documentElement.scrollHeight - window.innerHeight;
    return range <= 0 ? 0 : window.scrollY / range;
  });
}

async function activeScene(page: Page): Promise<string | null> {
  return page.locator("[data-active-scene]").first().getAttribute("data-active-scene");
}

/**
 * Scroll until a scene is active, then a little further into its body.
 *
 * The extra nudge matters: the first scroll position at which a pinned scene becomes active is
 * the position at which its sticky pane has only just engaged, so its content can still be
 * half-way through the frame. Anything that then reads geometry — or asks Playwright to click a
 * control — wants the scene settled in the viewport, not arriving into it.
 */
async function scrollIntoScene(page: Page, sceneId: string, steps = 80): Promise<void> {
  let reached = false;
  for (let step = 0; step <= steps; step += 1) {
    await scrollToRatio(page, step / steps);
    if ((await activeScene(page)) === sceneId) {
      reached = true;
      break;
    }
  }
  if (!reached) throw new Error(`never reached scene "${sceneId}" while scrolling the page`);

  for (let nudge = 0; nudge < 4; nudge += 1) {
    const next = (await currentRatio(page)) + 0.004;
    await scrollToRatio(page, next);
    if ((await activeScene(page)) !== sceneId) {
      await scrollToRatio(page, next - 0.004);
      break;
    }
  }
}

/**
 * Step the tracks carousel from the keyboard, the way a reader without a pointer does.
 *
 * This file used to drive the carousel through its arrow controls; an explicit art direction
 * removed them, and nothing was removed from the interaction model with them. The key handler
 * sits on the `[data-tracks-carousel]` group and the cases use a ROVING TABINDEX — exactly one
 * case is tabbable, the active one — so a key pressed on the centre case bubbles to the group and
 * reaches the same reducer actions the arrows reached: ArrowLeft / ArrowRight step, Home / End
 * jump. The locator is re-resolved on every press on purpose: each step moves which case is
 * centred, and therefore which button is the carousel's single tab stop.
 */
async function pressTrackKey(page: Page, key: string): Promise<void> {
  await page.locator("[data-track][data-active='true'] button").press(key, { timeout: 20_000 });
  await settle(page);
}

/** A required bounding box. Fails loudly rather than letting a `null` disable an assertion. */
async function boxOf(page: Page, selector: string, note: string): Promise<Box> {
  const box = await page.locator(selector).first().boundingBox();
  expect(box, `${note}: "${selector}" has no layout box`).not.toBeNull();
  return box as Box;
}

/** Do two boxes overlap horizontally at all? */
function overlapsHorizontally(a: Box, b: Box): boolean {
  return a.x < b.x + b.width - EPSILON && b.x < a.x + a.width - EPSILON;
}

/** Do two boxes overlap vertically at all? */
function overlapsVertically(a: Box, b: Box): boolean {
  return a.y < b.y + b.height - EPSILON && b.y < a.y + a.height - EPSILON;
}

/** Horizontal document overflow, in px. Must never be positive (brief §15, RESUME.md bug 4). */
async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => {
    const doc = document.documentElement;
    return doc.scrollWidth - doc.clientWidth;
  });
}

/** Open the lens at a given viewport, with the scene machine settled. */
async function openAt(page: Page, width: number, height: number): Promise<void> {
  await page.setViewportSize({ width, height });
  await page.goto("/");
  await settle(page);
}

/* ---------------------------------------------------------------------------------- tests */

test.describe.configure({ timeout: 180_000 });

/* ================================================== no horizontal document scroll, anywhere */

for (const viewport of VIEWPORTS) {
  test(`${viewport.label}: every scene is reachable and the document never scrolls sideways`, async ({
    page,
  }) => {
    await openAt(page, viewport.width, viewport.height);

    // The scene sequence is viewport-independent: §15 changes composition, never scene order.
    const order = await page
      .locator("[data-scene]")
      .evaluateAll((sections) => sections.map((section) => section.getAttribute("data-scene")));
    expect(order).toEqual([...SCENE_ORDER_FROM_BRIEF]);

    const seen = new Set<string>();
    const overflows: string[] = [];
    const STEPS = 56;

    for (let step = 0; step <= STEPS; step += 1) {
      await scrollToRatio(page, step / STEPS);
      const scene = await activeScene(page);
      if (scene) seen.add(scene);
      const overflow = await horizontalOverflow(page);
      if (overflow > 0) {
        overflows.push(`${scene ?? "?"} at step ${step}/${STEPS}: +${overflow}px`);
      }
    }

    // Regression guard. A 190px overflow from the film poster's designed bleed was fixed once
    // here; on an RTL page a wider document moves the viewport origin and drags the fixed canvas
    // off its edge. The footer wordmark may overflow VISUALLY by design (§15) — it must not
    // widen the document.
    expect(overflows, "documentElement.scrollWidth must never exceed clientWidth").toEqual([]);

    // Every scene is reachable at this viewport — no band collapses a scene out of the journey.
    expect([...seen].sort()).toEqual([...SCENE_ORDER_FROM_BRIEF].sort());
  });
}

test("pinning is preserved across every viewport", async ({ page }) => {
  const perViewport: Record<string, Record<string, string | null>> = {};

  for (const viewport of VIEWPORTS) {
    await openAt(page, viewport.width, viewport.height);
    perViewport[viewport.label] = Object.fromEntries(
      await page.locator("[data-scene]").evaluateAll((sections) =>
        sections.map((section) => [
          section.getAttribute("data-scene") ?? "?",
          section.getAttribute("data-pinned"),
        ]),
      ),
    );
  }

  // Brief §15, tablet: "Preserve scene order and pinning with shorter scroll budgets." The
  // budgets are tunable and are not asserted; which scenes hold the viewport is not.
  const desktop = perViewport["1440x900"];
  expect(Object.keys(desktop).sort()).toEqual([...SCENE_ORDER_FROM_BRIEF].sort());
  for (const viewport of VIEWPORTS) {
    expect(
      perViewport[viewport.label],
      `${viewport.label} must pin the same scenes as the desktop composition`,
    ).toEqual(desktop);
  }
});

/* ============================================================================ §15 coverflow */

for (const viewport of VIEWPORTS) {
  test(`${viewport.label}: the coverflow paints the positions §15 allows`, async ({ page }) => {
    await openAt(page, viewport.width, viewport.height);
    await scrollIntoScene(page, "tracks");

    const carousel = page.locator("[data-tracks-carousel]");
    const active = page.locator("[data-track][data-active='true']");
    const inField = page.locator("[data-track][data-in-field='true']");

    // DELETED, with its subject: the block that took both arrow controls' bounding boxes and
    // required each to have a real box inside the viewport at all four sizes — the geometric half
    // of §15's "visible arrow controls". The arrow buttons and their data hook no longer exist in
    // the DOM by art direction, and "the arrows are on screen" has no weaker form worth
    // asserting, so that coverage is gone rather than watered down. Nothing was substituted for
    // it here: the only on-screen geometry left in the tracks scene belongs to the CASES, and how
    // many of those paint at this band is what the rest of this test already measures. The other
    // half of the citation — keyboard reachability and labelling — is accessibility.spec.ts's.
    await expect(carousel).toHaveCount(1);

    // Drive the carousel to an index with room on both sides. The keyboard is the input under
    // test — no hover, no wheel, no drag. `Home` lands on the first track whatever the scroll
    // left behind, and each `ArrowRight` is one step along the field, which is composed
    // left-to-right whatever `dir` the text inside it carries.
    await pressTrackKey(page, "Home");
    await expect(active).toHaveAttribute("data-index", "0");
    for (let step = 0; step < COUNT_FIELD_AT_INDEX; step += 1) {
      await pressTrackKey(page, "ArrowRight");
    }
    await expect(active).toHaveAttribute("data-index", String(COUNT_FIELD_AT_INDEX));
    // The group reflects the index it was driven to, so the keys reached the machine rather than
    // merely moving focus around the field.
    await expect(carousel).toHaveAttribute("data-track-index", String(COUNT_FIELD_AT_INDEX));

    const painted = await inField.count();
    if (viewport.band === "mobile") {
      expect(painted).toBeGreaterThanOrEqual(MOBILE_COVERFLOW_RANGE.min);
      expect(painted).toBeLessThanOrEqual(MOBILE_COVERFLOW_RANGE.max);
      expect(painted, "mobile must not paint the desktop field").toBeLessThan(
        COVERFLOW_POSITIONS.desktop,
      );
    } else {
      expect(painted, `${viewport.band} coverflow positions`).toBe(
        COVERFLOW_POSITIONS[viewport.band],
      );
    }
  });
}

/* ================================================================== §15 film layout per band */

for (const viewport of VIEWPORTS) {
  test(`${viewport.label}: the film composition follows §15`, async ({ page }) => {
    await openAt(page, viewport.width, viewport.height);
    await scrollIntoScene(page, "films");

    const film = "[data-film][data-active='true']";
    const info = await boxOf(page, `${film} [data-film-title]`, `${viewport.label} film title`);
    const poster = await boxOf(page, `${film} [data-film-poster]`, `${viewport.label} poster`);

    const sideBySide =
      !overlapsHorizontally(info, poster) && info.x + info.width <= poster.x + EPSILON;
    const stacked = !overlapsVertically(info, poster) && poster.y + poster.height <= info.y + EPSILON;

    if (viewport.band === "desktop") {
      // Brief §15 desktop / §19: "Poster is right, information left on desktop."
      expect(sideBySide, "desktop must place the information left and the poster right").toBe(true);
    } else if (viewport.band === "tablet") {
      // §15 tablet: "Film layout remains two-column if readable; otherwise use a compact stacked
      // composition." Either is compliant — what is not compliant is the two colliding.
      expect(
        sideBySide || stacked,
        "tablet must be two-column or cleanly stacked, never overlapping",
      ).toBe(true);
    } else {
      // §15 mobile: "Film poster appears above or behind the text without reducing readability."
      expect(stacked, "mobile must place the poster above the text").toBe(true);
      // Single column: the two share the frame's width rather than splitting it.
      expect(
        overlapsHorizontally(info, poster),
        "mobile must be one column, not a narrowed two-column split",
      ).toBe(true);
      // "…without reducing readability": the topmost element over the title is the title's own
      // subtree, so nothing — poster, paper layer or canvas — is sitting on the words.
      expect(
        await topmostAtCentreIsWithin(page, `${film} [data-film-title]`),
        "something is painted over the film title on mobile",
      ).toBe(true);
    }

    // Whatever the band, the information column stays inside the frame.
    expect(info.x).toBeGreaterThanOrEqual(-EPSILON);
    expect(info.x + info.width).toBeLessThanOrEqual(viewport.width + EPSILON);
  });
}

/* ============================================================= §15 Art Pieces rows per band */

for (const viewport of VIEWPORTS) {
  test(`${viewport.label}: the Art Pieces rows follow §15`, async ({ page }) => {
    await openAt(page, viewport.width, viewport.height);
    await scrollIntoScene(page, "artPieces");

    const row = "[data-art-piece][data-index='0']";
    const text = await boxOf(page, `${row} [data-art-title]`, `${viewport.label} art title`);
    const media = await boxOf(page, `${row} [data-art-media]`, `${viewport.label} art media`);

    if (viewport.band === "mobile") {
      // §15 mobile: "Art Pieces become one column: title/details followed by media."
      expect(
        overlapsHorizontally(text, media),
        "mobile art rows must be one column, not two narrow ones",
      ).toBe(true);
      expect(
        media.y >= text.y + text.height - EPSILON,
        "on mobile the media must follow the title/details, not precede them",
      ).toBe(true);
    } else {
      // §15 desktop/tablet + §7.9: "image or muted loop video on the right", text beside it.
      expect(
        !overlapsHorizontally(text, media),
        `${viewport.band} art rows must be two columns`,
      ).toBe(true);
      expect(
        media.x >= text.x + text.width - EPSILON,
        `${viewport.band} art media must sit on the right of the text`,
      ).toBe(true);
    }

    expect(media.x + media.width).toBeLessThanOrEqual(viewport.width + EPSILON);
  });
}

/* ========================================================= §8/§15 header behavior on mobile */

test("the mobile header never intercepts scroll or covers primary content", async ({ page }) => {
  const mobile = VIEWPORTS[0];
  await openAt(page, mobile.width, mobile.height);
  await scrollIntoScene(page, "thesis");

  const header = await boxOf(page, "header", "mobile header");
  expect(header.width, "the header must not span more than the frame").toBeLessThanOrEqual(
    mobile.width + EPSILON,
  );

  // "Must not intercept scroll": the page is hit-testable THROUGH the header. Whatever the
  // browser finds at the header's own centre point is not the header or anything inside it.
  const throughHeader = await page.evaluate(
    ({ x, y }) => {
      const element = document.elementFromPoint(x, y);
      return { found: element?.tagName ?? null, inHeader: Boolean(element?.closest("header")) };
    },
    { x: header.x + header.width / 2, y: header.y + header.height / 2 },
  );
  expect(throughHeader.found, "nothing at all is hit-testable under the header").not.toBeNull();
  expect(throughHeader.inHeader, "the header swallows pointer and wheel events").toBe(false);

  // …and it behaves that way: a wheel gesture delivered over the header still scrolls the page.
  //
  // Mobile WebKit has no synthetic wheel (Playwright refuses it on a touch device) and no
  // synthetic touch DRAG either — a JavaScript-dispatched `touchmove` does not drive native
  // scrolling, and Lenis runs with `syncTouch: false` precisely so touch scrolling stays native.
  // So this leg runs where a wheel exists; where it does not, the hit test above is what stands,
  // and the touch case is recorded as a manual check rather than faked.
  const before = await page.evaluate(() => window.scrollY);
  let wheelDelivered = true;
  try {
    await page.mouse.move(header.x + header.width / 2, header.y + header.height / 2);
    await page.mouse.wheel(0, 600);
  } catch (error) {
    if (!/wheel is not supported/i.test(String(error))) throw error;
    wheelDelivered = false;
  }

  if (wheelDelivered) {
    await expect
      .poll(() => page.evaluate(() => window.scrollY), {
        message: "a wheel gesture over the header must scroll the document",
        timeout: 10_000,
      })
      .toBeGreaterThan(before);
  } else {
    test.info().annotations.push({
      type: "manual",
      description:
        "mobile WebKit: no synthetic wheel or touch-drag. Verify by hand that a one-finger drag " +
        "starting on the header scrolls the page. The elementFromPoint check above already " +
        "proves the header is not hit-testable, which is the same guarantee.",
    });
  }

  // "Must not cover primary content": the scene's own title clears the header's box entirely.
  await scrollIntoScene(page, "thesis");
  const title = await boxOf(page, "[data-lens-title]", "lens title");
  expect(
    overlapsVertically(title, header) && overlapsHorizontally(title, header),
    "the header overlaps the lens title on mobile",
  ).toBe(false);
});

/* ================================================================= §15 "no feature may depend on hover" */

test("no feature depends on hover: mobile reads and drives the page without one", async ({
  page,
}) => {
  const mobile = VIEWPORTS[0];
  await openAt(page, mobile.width, mobile.height);

  // Content that a hover-only affordance would have hidden is simply present, from the server.
  await expect(page.locator("[data-menu-name]").first()).not.toHaveText("");
  await expect(page.locator("[data-menu-maker]").first()).not.toHaveText("");
  await expect(page.locator("[data-film-rationale]").first()).not.toHaveText("");
  await expect(page.locator("[data-art-rationale]").first()).not.toHaveText("");

  await scrollIntoScene(page, "tracks");
  const active = page.locator("[data-track][data-active='true']");

  // The carousel advances with no pointer ever resting on the field — the keyboard has no hover
  // state at all (brief §16). Rewound to the first slide first, so the step under test can never
  // be a clamp at the end.
  await pressTrackKey(page, "Home");
  await expect(active).toHaveAttribute("data-index", "0");
  await pressTrackKey(page, "ArrowRight");
  await expect(active).toHaveAttribute("data-index", "1");

  // The keyboard reaches the field on its own, with no pointer having touched it: the roving
  // tabindex keeps exactly one case tabbable — the centre one — and that is the tab stop the
  // arrow keys above were driven from. Asserted here, before any click: a click scrolls its
  // target into view, and a scene that has been nudged out of the viewport lets its tab stop go.
  const activeCase = page.locator("[data-track][data-active='true'] button").first();
  await expect(activeCase).toHaveAttribute("tabindex", "0");
  await activeCase.focus();
  await expect(activeCase).toBeFocused();

  // …and the field advances from a TAP on an off-centre case: a press, never a hover, which is
  // the affordance a touch reader has now that the arrow controls are gone by art direction. The
  // pressed case's own index is read first, so the assertion is "the case you pressed became the
  // centre one" rather than a guess about which neighbour the field was offering.
  const neighbour = page.locator("[data-track][data-in-field='true']:not([data-active='true'])");
  const neighbourIndex = await neighbour.first().getAttribute("data-index");
  expect(neighbourIndex, "the field paints no neighbour to press").not.toBeNull();
  await neighbour.first().locator("button").click({ timeout: 20_000 });
  await expect(active).toHaveAttribute("data-index", String(neighbourIndex));
});

/* ------------------------------------------------------------------------------ tiny helper */

/**
 * Is the topmost element at a target's centre point the target itself, or part of it?
 *
 * A hit test, not a style read: it answers "could the reader see and touch this here", which is
 * what "without reducing readability" and "nothing depends on hover" both come down to.
 */
async function topmostAtCentreIsWithin(page: Page, selector: string): Promise<boolean> {
  return page.evaluate((target) => {
    const element = document.querySelector(target);
    if (!element) return false;
    const rect = element.getBoundingClientRect();
    const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    if (!hit) return false;
    return element.contains(hit) || hit.contains(element);
  }, selector);
}
