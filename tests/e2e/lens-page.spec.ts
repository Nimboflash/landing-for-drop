import { expect, test as base, type Page } from "@playwright/test";

/**
 * Page seam (BUILD-GUIDE seam 3) for the immersive lens routes.
 *
 * Rules this file obeys:
 *
 * - **Attributes and text only.** Every assertion reads a DOM attribute the scenes reflect their
 *   logical state into (`data-scene`, `data-active`, `aria-current`, `data-header-variant`) or
 *   text content. Never inline transforms, opacity, computed styles, GSAP internals or WebGL
 *   pixels — those are the animation engine's business, and Playwright's visibility heuristic is
 *   wrong for them anyway.
 * - **Expected values come from the brief and the W04 seed**, written out below, never recomputed
 *   the way the page computes them.
 * - **Ordinal, never absolute.** Scroll budgets are tunable by design, so scroll assertions check
 *   ordering and symmetry — never "scene X is active at Y% of the page".
 * - **Zero console errors** is a standing assertion on every test (auto fixture).
 */

/* ------------------------------------------------------- expectations, from the source docs */

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

/** Both routes render the same template from the same lens (brief §5). */
const LENS_ROUTES = ["/", "/lens/beautiful-imperfection"] as const;

/** W04 seed — `handoff/04-mock-content/.../beautiful-imperfection.mock.json`. */
const LENS_SLUG = "beautiful-imperfection";
const LENS_WEEK = "W04";
const LENS_TITLE_FA = "زیبایی در کامل نبودن";
const LENS_TITLE_EN = "BEAUTIFUL IMPERFECTION";
const HERO_MESSAGE_COUNT = 3;
const MENU_ITEM_COUNT = 2;
const MENU_MAKERS = ["Éclair", "Mochiki"];
const FILM_TITLES = ["SHOWING UP", "PERFECT DAYS", "PATERSON"];
const FILM_DIRECTORS = ["Kelly Reichardt", "Wim Wenders", "Jim Jarmusch"];
const TRACK_TITLES = [
  "Natural Blue",
  "This Time Around",
  "Porcelain",
  "andata",
  "anything",
  "Wild Bill Jones",
  "Ambre",
  "Space 1",
  "Magdalena",
  "Für Alina",
  "Mr. Henri Rousseau's Dream",
];
const ART_PIECE_TITLES = [
  "BRION MEMORIAL",
  "UNTITLED (S.270)",
  "UNTITLED, FROM ILLUMINANCE",
  "THE PRATFALL EFFECT",
];
// The seed uses the same closing line for the grid statement and the footer (brief §7.4, §7.10).
const GRID_STATEMENT_FA = "جایی با یک نگاه مشخص.";
const FOOTER_STATEMENT_FA = "جایی با یک نگاه مشخص.";
/**
 * Brief §7.10, "Footer content": "Bottom metadata slots: Instagram, location, contact, copyright,
 * and legal." The W04 seed carries exactly those five, all disabled. (This constant previously
 * read 4 — a miscount, not a looser rule: the page has rendered five slots since the shell first
 * mapped `footer.links`, so the assertion failed against both source documents.)
 */
const FOOTER_SLOT_COUNT = 5;

/** Hard rule (CLAUDE.md / brief §2): no commerce surface anywhere, in either language. */
const FORBIDDEN_COMMERCE_COPY = [
  "waitlist",
  "join the waitlist",
  "schedule demo",
  "add to cart",
  "buy now",
  "سبد خرید",
  "قیمت",
];

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

/** Scene ids, in the order the DOM presents them. */
async function sceneOrder(page: Page): Promise<(string | null)[]> {
  return page
    .locator("[data-scene]")
    .evaluateAll((sections) => sections.map((section) => section.getAttribute("data-scene")));
}

/** The scene the state machine currently says is active. */
async function activeScene(page: Page): Promise<string | null> {
  return page.locator("[data-active-scene]").first().getAttribute("data-active-scene");
}

/** Scroll to a fraction of the scrollable range and let the machine settle. */
async function scrollToRatio(page: Page, ratio: number): Promise<void> {
  await page.evaluate((value) => {
    const range = document.documentElement.scrollHeight - window.innerHeight;
    window.scrollTo({ top: range * value, behavior: "instant" as ScrollBehavior });
  }, ratio);
  await settle(page);
}

/** Two animation frames: one for the scroll to be observed, one for the render it causes. */
async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

/** Walk down the page, collecting the active scene at each step. */
async function walkScenes(page: Page, steps: number, reverse = false): Promise<string[]> {
  const seen: string[] = [];
  for (let step = 0; step <= steps; step += 1) {
    const ratio = reverse ? 1 - step / steps : step / steps;
    await scrollToRatio(page, ratio);
    const scene = await activeScene(page);
    if (scene && seen[seen.length - 1] !== scene) seen.push(scene);
  }
  return seen;
}

/** Scroll down until the given scene is the active one. */
async function scrollUntilScene(page: Page, sceneId: string, steps = 60): Promise<void> {
  for (let step = 0; step <= steps; step += 1) {
    await scrollToRatio(page, step / steps);
    if ((await activeScene(page)) === sceneId) return;
  }
  throw new Error(`never reached scene "${sceneId}" while scrolling the page`);
}

type SceneDiagnosticsSnapshot = {
  scrollTriggerCount: number;
  sceneId: string;
  contentMode: string | undefined;
};

/**
 * The dev-build diagnostics object (BUILD-GUIDE's sanctioned escape hatch), or `null` when it has
 * been stripped — which is the correct state of a production bundle.
 */
async function readDiagnostics(page: Page): Promise<SceneDiagnosticsSnapshot | null> {
  return page.evaluate(() => {
    const diagnostics = (
      window as unknown as {
        __dropSceneDiagnostics?: {
          scrollTriggerCount: number;
          sceneId: string;
          contentMode: string | undefined;
        };
      }
    ).__dropSceneDiagnostics;
    if (!diagnostics) return null;
    return {
      scrollTriggerCount: diagnostics.scrollTriggerCount,
      sceneId: diagnostics.sceneId,
      contentMode: diagnostics.contentMode,
    };
  });
}

/* ---------------------------------------------------------------------------------- tests */

test.describe.configure({ timeout: 90_000 });

for (const route of LENS_ROUTES) {
  test(`${route} renders the W04 lens as ten scenes in brief order`, async ({ page }) => {
    const response = await page.goto(route);
    expect(response?.status()).toBe(200);

    await expect(page.locator("html")).toHaveAttribute("lang", "fa");
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
    await expect(page.locator(`[data-lens="${LENS_SLUG}"]`)).toHaveCount(1);

    expect(await sceneOrder(page)).toEqual([...SCENE_ORDER_FROM_BRIEF]);

    await expect(page.locator("[data-lens-title]")).toHaveText(LENS_TITLE_FA);
    await expect(page.locator("[data-lens-label]")).toContainText(LENS_WEEK);
    await expect(page.locator("[data-lens-label]")).toContainText(LENS_TITLE_EN);
  });
}

test("every lens collection is rendered, with counts from the data", async ({ page }) => {
  await page.goto("/");

  await expect(page.locator("[data-hero-message]")).toHaveCount(HERO_MESSAGE_COUNT);
  await expect(page.locator("[data-menu-item]")).toHaveCount(MENU_ITEM_COUNT);
  await expect(page.locator("[data-film]")).toHaveCount(FILM_TITLES.length);
  await expect(page.locator("[data-track]")).toHaveCount(TRACK_TITLES.length);
  await expect(page.locator("[data-art-piece]")).toHaveCount(ART_PIECE_TITLES.length);

  for (const maker of MENU_MAKERS) {
    await expect(page.locator("[data-menu-maker]", { hasText: maker })).toHaveCount(1);
  }
  expect(await page.locator("[data-film-title]").allTextContents()).toEqual(FILM_TITLES);
  expect(await page.locator("[data-film-director]").allTextContents()).toEqual(FILM_DIRECTORS);
  expect(await page.locator("[data-track-title]").allTextContents()).toEqual(TRACK_TITLES);
  expect(await page.locator("[data-art-title]").allTextContents()).toEqual(ART_PIECE_TITLES);

  await expect(page.locator("[data-grid-statement]")).toContainText(GRID_STATEMENT_FA);
  await expect(page.locator("[data-footer-statement]")).toHaveText(FOOTER_STATEMENT_FA);
  await expect(page.locator("[data-footer-link]")).toHaveCount(FOOTER_SLOT_COUNT);
  // Brief §7.10: the slots are named placeholders with no destination — "Do not invent live
  // destinations." A disabled slot must not be an anchor, so it is not focusable as a link.
  await expect(page.locator("[data-footer-link][data-enabled='false'] a")).toHaveCount(0);
});

test("all meaningful text is server-rendered with JavaScript disabled", async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  const page = await context.newPage();
  try {
    const response = await page.goto("/lens/beautiful-imperfection");
    expect(response?.status()).toBe(200);

    expect(await sceneOrder(page)).toEqual([...SCENE_ORDER_FROM_BRIEF]);
    await expect(page.locator("[data-lens-title]")).toHaveText(LENS_TITLE_FA);
    await expect(page.locator("[data-hero-message]")).toHaveCount(HERO_MESSAGE_COUNT);
    await expect(page.locator("[data-track]")).toHaveCount(TRACK_TITLES.length);
    expect(await page.locator("[data-film-title]").allTextContents()).toEqual(FILM_TITLES);
    expect(await page.locator("[data-art-title]").allTextContents()).toEqual(ART_PIECE_TITLES);
    await expect(page.locator("[data-footer-statement]")).toHaveText(FOOTER_STATEMENT_FA);
  } finally {
    await context.close();
  }
});

test("Persian is the document language and Latin runs carry their own direction", async ({
  page,
}) => {
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("lang", "fa");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

  const filmTitle = page.locator("[data-film-title]").first();
  await expect(filmTitle).toHaveAttribute("lang", "en");
  await expect(filmTitle).toHaveAttribute("dir", "ltr");

  // The film scene's left/right composition is held by CSS grid, so its Persian column keeps
  // reading right-to-left rather than being flipped by a document-direction hack.
  await expect(page.locator("[data-film] [dir='rtl']").first()).toBeAttached();
});

test("no commerce surface anywhere on the page", async ({ page }) => {
  await page.goto("/");

  const visibleText = (await page.locator("body").innerText()).toLowerCase();
  for (const phrase of FORBIDDEN_COMMERCE_COPY) {
    expect(visibleText, `"${phrase}" must never appear`).not.toContain(phrase.toLowerCase());
  }

  // Top-right of the header stays empty in V1: the header carries the mark and nothing else.
  await expect(page.locator("header a, header button")).toHaveCount(0);
});

test("the header hides for the loader and adapts its contrast per scene", async ({ page }) => {
  await page.goto("/");

  const header = page.locator("[data-header-variant]");
  await expect(header).toHaveAttribute("data-header-variant", "hidden");

  // Off-white thesis scene: a dark mark. Brief §8 — the logo adapts to scene contrast.
  await scrollUntilScene(page, "thesis");
  await expect(header).toHaveAttribute("data-header-variant", "dark");

  // The films scene runs on the black Wavy Dots background: a light mark.
  await scrollUntilScene(page, "films");
  await expect(header).toHaveAttribute("data-header-variant", "light");
});

test("scroll walks the scenes in order and reverses cleanly back to the top", async ({ page }) => {
  await page.goto("/");
  expect(await activeScene(page)).toBe("loader");

  const forward = await walkScenes(page, 48);
  expect(forward[0]).toBe("loader");
  expect(forward[forward.length - 1]).toBe("footer");

  // Ordinal assertion: the active scene never moves backwards while scrolling forwards.
  const forwardOrdinals = forward.map((scene) =>
    SCENE_ORDER_FROM_BRIEF.indexOf(scene as (typeof SCENE_ORDER_FROM_BRIEF)[number]),
  );
  expect(forwardOrdinals).not.toContain(-1);
  expect([...forwardOrdinals].sort((a, b) => a - b)).toEqual(forwardOrdinals);

  const backward = await walkScenes(page, 48, true);
  expect(backward[0]).toBe("footer");
  expect(backward[backward.length - 1]).toBe("loader");

  const backwardOrdinals = backward.map((scene) =>
    SCENE_ORDER_FROM_BRIEF.indexOf(scene as (typeof SCENE_ORDER_FROM_BRIEF)[number]),
  );
  expect([...backwardOrdinals].sort((a, b) => b - a)).toEqual(backwardOrdinals);

  // Every scene the forward pass saw is seen again on the way back: the journey is reversible.
  expect([...backward].reverse()).toEqual(forward);

  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});

test("navigating away and back leaves the scene machine's triggers un-grown", async ({ page }) => {
  await page.goto("/");
  await scrollUntilScene(page, "films");
  const sceneBefore = await activeScene(page);
  const before = await readDiagnostics(page);

  await page.goto("/lens/beautiful-imperfection");
  await settle(page);
  await page.goBack();
  await settle(page);
  await scrollUntilScene(page, "films");

  // Behavioural proxy, always asserted: the same scroll position produces the same state.
  expect(await activeScene(page)).toBe(sceneBefore);

  const after = await readDiagnostics(page);
  if (before && after) {
    expect(before.scrollTriggerCount).toBeGreaterThanOrEqual(SCENE_ORDER_FROM_BRIEF.length);
    expect(after.scrollTriggerCount).toBe(before.scrollTriggerCount);
    expect(after.contentMode).toBe("development-mock");
  } else {
    test.info().annotations.push({
      type: "note",
      description:
        "dev-only scene diagnostics are stripped from this build; asserted the behavioural proxy only",
    });
  }
});

test("carousel controls route through the same state machine as scroll", async ({ page }) => {
  await page.goto("/");
  // Scroll the tracks scene into play first: a discrete input only outlives scroll while its own
  // scene is the active one (the reducer re-syncs `trackIndex` on entering and leaving).
  await scrollUntilScene(page, "tracks");

  const activeTrack = page.locator("[data-track][data-active='true']");
  const previous = page.locator("[data-carousel-control='prev']");
  const next = page.locator("[data-carousel-control='next']");

  // Rewind past the start: the index clamps at the first track whatever the scroll position was.
  for (let click = 0; click < TRACK_TITLES.length + 1; click += 1) {
    await previous.click();
  }
  await expect(activeTrack).toHaveCount(1);
  await expect(activeTrack).toHaveAttribute("data-index", "0");
  await expect(activeTrack).toHaveAttribute("aria-current", "true");
  await expect(activeTrack).toContainText(TRACK_TITLES[0]);

  await next.click();
  await expect(activeTrack).toHaveAttribute("data-index", "1");
  await expect(activeTrack).toContainText(TRACK_TITLES[1]);
});
