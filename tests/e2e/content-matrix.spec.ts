import { expect, test as base, type Page } from "@playwright/test";

import {
  assertProductionMedia,
  canDisplayAsset,
  PRODUCTION_MEDIA_GUARD_FAILURE,
  reviewMediaRights,
  SHOW_RIGHTS_PENDING_FLAG,
  verdictFor,
  type RightsVerdict,
  type RuntimeEnvironment,
} from "../../src/content/rights";
import type { MediaAsset, WeeklyLens } from "../../src/content/drop-weekly-lens.schema";

/**
 * Page seam (BUILD-GUIDE seam 3) for the brief §21 **Content** and **Rights** rows.
 *
 * ## What this file is for
 *
 * The whole point of the data-driven architecture is that a DIFFERENT lens just works. W04 can
 * never prove that on its own — every count it carries is the count the scenes were built
 * against. So the count fixtures (`src/content/lenses/variable-count-fixture.ts`) are rendered
 * through the real scene components on the development-only route
 * `/dev/fixture/[name]`, and this file asserts that every slot follows the DATA.
 *
 * ## Rules this file obeys
 *
 * - **Attributes and text only.** Every page assertion reads a data attribute a scene reflects its
 *   logical state into, or text content. Never computed styles, inline transforms or opacity, and
 *   never WebGL pixels.
 * - **Expected values come from the fixtures' own specification** — the counts each fixture is
 *   documented to carry, written out below — and from the brief. Nothing is recomputed the way
 *   the page computes it: no test reads `lens.artPieces.length` and compares it to what rendered,
 *   because that assertion would pass however wrong both were.
 * - **Ordinal, never absolute.** No test asserts a scroll-progress threshold; scroll budgets are
 *   tunable by design.
 *
 * ## Two origins, on purpose
 *
 * | assertion | origin |
 * | --- | --- |
 * | fixture lenses render | the DEV server — the fixture route exists in development only |
 * | mock media is WITHHELD behind branded placeholders | the PRODUCTION server (`baseURL`) |
 * | the fixture route 404s | the PRODUCTION server (`baseURL`) |
 *
 * That split is not a workaround, it is the thing being tested. `canDisplayAsset` gates
 * `development-mock` media to development/staging, so a production build showing DROP placeholders
 * instead of the mock pack is CORRECT behavior (brief §11, §18) — and the dev-only fixture route
 * returning 404 in production is what stops test data from ever shipping.
 *
 * The dev origin is `http://localhost:3000` by default and overridable with `DROP_DEV_ORIGIN`.
 * When no dev server is listening the fixture tests SKIP with a note rather than passing quietly.
 */

/* --------------------------------------------------------- the fixtures' specification */

/**
 * `variableCountFixtureLens` — counts deliberately unlike W04's (2 menu / 3 films / 11 tracks /
 * 4 art / 3 hero messages). Films are pinned at exactly 3 by the adopted schema, so the fixture
 * cannot vary them.
 */
const VARIABLE_COUNTS = {
  slug: "variable-count-fixture",
  week: "W98",
  heroMessages: 2,
  menuItems: 5,
  films: 3,
  tracks: 4,
  artPieces: 6,
  /** The Art Pieces heading renders the count as a two-digit editorial number. */
  artHeadingCount: "06",
  footerLinks: 1,
} as const;

/**
 * `minimumCountsFixtureLens` — the schema's MINIMUM allowed content. Brief §11: "A scene
 * gracefully handles the minimum allowed content count."
 */
const MINIMUM_COUNTS = {
  slug: "minimum-counts-fixture",
  week: "W99",
  heroMessages: 1,
  menuItems: 2,
  films: 3,
  tracks: 3,
  artPieces: 1,
  artHeadingCount: "01",
  footerLinks: 1,
} as const;

/** Titles the fixtures generate, per fixture position. Used to prove reachability by name. */
const fixtureTrackTitle = (position: number) => `Fixture Track ${position}`;
const fixtureArtTitle = (position: number) => `FIXTURE ART PIECE ${position}`;

/* ------------------------------------------------------------------ W04 seed expectations */

/** W04's fourth field note carries `duration` + `label` and NO `creator` / `year` (brief §7.9). */
const PRATFALL_INDEX = 3;
const PRATFALL_TITLE = "THE PRATFALL EFFECT";
const PRATFALL_DURATION = "3 MIN READ";
const PRATFALL_LABEL_FA = "اول شایستگی؛ بعد یک لغزش کوچک";
/** The other three field notes carry `creator` + `year` and neither `duration` nor `label`. */
const CREDITED_ART_INDICES = [0, 1, 2] as const;
/** W04 ships 20 mock media assets, all `development-mock` / `productionAllowed: false`. */
const MOCK_ASSET_COUNT = 20;

/* ------------------------------------------------------------------------------ origins */

const DEV_ORIGIN = process.env.DROP_DEV_ORIGIN ?? "http://localhost:3000";
const FIXTURE_ROUTE = (slug: string) => `/dev/fixture/${slug}`;

/* ------------------------------------------------------------------------------ fixtures */

/**
 * Brief §17: "No console errors, WebGL warnings, or accumulating ScrollTriggers."
 *
 * Errors are partitioned before being asserted on. A page opened on the DEV origin also runs
 * Next's development runtime — HMR, react-refresh, the error overlay — none of which is in the
 * shipped bundle, and which under parallel workers can throw while a route is being recompiled.
 * An error whose stack names application source (`/src/…`) is the build's own and FAILS the test;
 * one that names only framework/dev-runtime frames is recorded as a test annotation instead, so
 * it is visible in the report rather than silently swallowed OR silently failing the wrong thing.
 * Production pages are stricter: nothing is excused there.
 */
type CapturedError = { text: string; stack: string | undefined };

const APP_SOURCE = /[/\\]src[/\\]|src%2F/;

const test = base.extend<{ consoleErrors: CapturedError[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: CapturedError[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push({ text: message.text(), stack: undefined });
      });
      page.on("pageerror", (error) =>
        errors.push({ text: `pageerror: ${error.message}`, stack: error.stack }),
      );
      await use(errors);

      const fromDevRuntime = (error: CapturedError): boolean =>
        page.url().startsWith(DEV_ORIGIN) && !!error.stack && !APP_SOURCE.test(error.stack);

      const excused = errors.filter(fromDevRuntime);
      const real = errors.filter((error) => !fromDevRuntime(error));

      for (const error of excused) {
        test.info().annotations.push({
          type: "dev-runtime error (not in the shipped bundle)",
          description: error.text,
        });
      }
      expect(
        real.map((error) => error.text),
        "the page must produce no console errors",
      ).toEqual([]);
    },
    { auto: true },
  ],
});

/* ------------------------------------------------------------------------------- helpers */

/** Two animation frames: one for the scroll to be observed, one for the render it causes. */
async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

/** Scroll to a fraction of the scrollable range and let the machine settle. */
async function scrollToRatio(page: Page, ratio: number): Promise<void> {
  await page.evaluate((value) => {
    const range = document.documentElement.scrollHeight - window.innerHeight;
    window.scrollTo({ top: range * value, behavior: "instant" as ScrollBehavior });
  }, ratio);
  await settle(page);
}

/** The scene the state machine currently says is active. */
async function activeScene(page: Page): Promise<string | null> {
  return page.locator("[data-active-scene]").first().getAttribute("data-active-scene");
}

/** Scroll down until the given scene is the active one. */
async function scrollUntilScene(page: Page, sceneId: string, steps = 72): Promise<void> {
  for (let step = 0; step <= steps; step += 1) {
    await scrollToRatio(page, step / steps);
    if ((await activeScene(page)) === sceneId) return;
  }
  throw new Error(`never reached scene "${sceneId}" while scrolling the page`);
}

/** Walk the page, collecting each distinct active scene in the order it was seen. */
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

/**
 * Open a count fixture on the DEV origin, or skip the test with a note.
 *
 * The fixture route is development-only by construction, so it does not exist on the production
 * server this suite otherwise runs against. A missing dev server must not look like a pass.
 */
async function openFixture(page: Page, slug: string): Promise<void> {
  const url = `${DEV_ORIGIN}${FIXTURE_ROUTE(slug)}`;

  /*
   * Bounded, and retried once.
   *
   * Next's development server compiles a route on first request and serializes those compiles.
   * Several parallel workers asking for a not-yet-compiled route at the same moment — more so
   * when other suites are driving the same server — can stall the first navigation for minutes.
   * Without an explicit bound that stall consumes the whole test timeout and reports as a
   * mysterious hang; with one, the first attempt fails fast, the route is warm by the retry, and
   * a genuine failure still fails rather than being skipped away.
   */
  const NAVIGATION_TIMEOUT_MS = 60_000;
  let response;
  let firstError: unknown;

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      response = await page.goto(url, { waitUntil: "load", timeout: NAVIGATION_TIMEOUT_MS });
      break;
    } catch (error) {
      if (attempt === 1) {
        firstError = error;
        continue;
      }
      // Connection refused on both attempts means there is no dev server at all. That is a
      // missing prerequisite, not a failing build — skip loudly rather than pass quietly.
      if (/ERR_CONNECTION_REFUSED|ECONNREFUSED/.test(String(error))) {
        test.skip(
          true,
          `no development server at ${DEV_ORIGIN}. The count fixtures render only there — ` +
            `start \`npm run dev\` or set DROP_DEV_ORIGIN.`,
        );
        return;
      }
      throw new Error(
        `${url} did not load within ${NAVIGATION_TIMEOUT_MS}ms on two attempts. If other suites ` +
          `are driving the same dev server, this is compile contention rather than a page ` +
          `failure — re-run this file on its own.\nfirst: ${String(firstError)}\nsecond: ${String(error)}`,
      );
    }
  }

  expect(response?.status(), `${url} must render the fixture lens in development`).toBe(200);
}

/** Every scene id, in the DOM's order. */
async function sceneOrder(page: Page): Promise<(string | null)[]> {
  return page
    .locator("[data-scene]")
    .evaluateAll((sections) => sections.map((section) => section.getAttribute("data-scene")));
}

/* ----------------------------------------------------------- rights: synthetic assets */

/** One media asset in a named rights state. Synthetic — these never touch the real content. */
function assetIn(
  rightsStatus: MediaAsset["rightsStatus"],
  productionAllowed: boolean,
  extra: Partial<MediaAsset> = {},
): MediaAsset {
  return {
    src: `/media/probe/${rightsStatus}.webp`,
    alt: { fa: "نمونه‌ی آزمایشی", en: "probe asset" },
    width: 1200,
    height: 1200,
    rightsStatus,
    productionAllowed,
    ...extra,
  } as MediaAsset;
}

/** The thinnest lens shape the guard reads: it only walks the four media collections. */
function lensCarrying(assets: readonly MediaAsset[]): WeeklyLens {
  return {
    slug: "rights-probe",
    week: "W00",
    menuItems: assets.map((image, index) => ({ id: `probe-${index}`, image })),
    films: [],
    tracks: [],
    artPieces: [],
  } as unknown as WeeklyLens;
}

/** Run `body` with an environment variable temporarily set, then restore it exactly. */
function withEnv(name: string, value: string | undefined, body: () => void): void {
  const previous = process.env[name];
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
  try {
    body();
  } finally {
    if (previous === undefined) delete process.env[name];
    else process.env[name] = previous;
  }
}

/* ---------------------------------------------------------------------------------- tests */

test.describe.configure({ timeout: 180_000 });

/* =========================================================== CONTENT ROW — variable counts */

test("the variable-count fixture fills every slot from its own data, not W04's", async ({
  page,
}) => {
  await openFixture(page, VARIABLE_COUNTS.slug);

  await expect(page.locator(`[data-lens="${VARIABLE_COUNTS.slug}"]`)).toHaveCount(1);
  await expect(page.locator("[data-lens-label]")).toContainText(VARIABLE_COUNTS.week);

  // Every collection's slot count follows the fixture, which carries counts W04 cannot supply.
  await expect(page.locator("[data-hero-message]")).toHaveCount(VARIABLE_COUNTS.heroMessages);
  await expect(page.locator("[data-menu-item]")).toHaveCount(VARIABLE_COUNTS.menuItems);
  await expect(page.locator("[data-film]")).toHaveCount(VARIABLE_COUNTS.films);
  await expect(page.locator("[data-track]")).toHaveCount(VARIABLE_COUNTS.tracks);
  await expect(page.locator("[data-art-piece]")).toHaveCount(VARIABLE_COUNTS.artPieces);
  await expect(page.locator("[data-footer-link]")).toHaveCount(VARIABLE_COUNTS.footerLinks);

  // Counts the scenes ANNOUNCE, not just the number of elements they emitted. Brief §11:
  // "Counts displayed in UI derive from array length."
  await expect(page.locator("[data-menu-items]")).toHaveAttribute(
    "data-menu-count",
    String(VARIABLE_COUNTS.menuItems),
  );
  await expect(page.locator("[data-tracks-carousel]")).toHaveAttribute(
    "data-track-count",
    String(VARIABLE_COUNTS.tracks),
  );
  await expect(page.locator("[data-art-count]")).toHaveText(VARIABLE_COUNTS.artHeadingCount);

  // The scene sequence is the lens-independent part: a different lens must not reorder the page.
  expect(await sceneOrder(page)).toEqual([
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
  ]);
});

test("five fixture menu cards fan and flip, and unflip on reverse scroll", async ({ page }) => {
  await openFixture(page, VARIABLE_COUNTS.slug);
  const deck = page.locator("[data-menu-items]");

  // Before the deck is reached, nothing has been dealt.
  await expect(deck).toHaveAttribute("data-deck-phase", "below");
  await expect(deck).toHaveAttribute("data-flipped-count", "0");

  await scrollUntilScene(page, "menu");

  // Walk the deck's own scene until every card the DATA supplies has been turned. `revealed` is
  // the deck's terminal phase; reaching it with a five-card deck is the assertion.
  const observed: string[] = [];
  for (let step = 0; step <= 60; step += 1) {
    if ((await activeScene(page)) !== "menu") break;
    const phase = await deck.getAttribute("data-deck-phase");
    if (phase && observed[observed.length - 1] !== phase) observed.push(phase);
    if (phase === "revealed") break;
    await scrollToRatio(page, (await currentRatio(page)) + 0.006);
  }

  await expect(deck).toHaveAttribute("data-flipped-count", String(VARIABLE_COUNTS.menuItems), {
    timeout: 15_000,
  });
  await expect(page.locator("[data-menu-item][data-flipped='true']")).toHaveCount(
    VARIABLE_COUNTS.menuItems,
  );

  // ORDINAL, not absolute: the deck's phases only ever advance — it rises, fans and reveals in
  // that order and never steps backwards while scrolling forwards. Which phases a given scroll
  // sample lands on depends on the budget, so nothing here requires a particular one.
  const DECK_PHASE_ORDER = ["below", "rising", "fanned", "revealing", "revealed"];
  const ordinals = observed.map((phase) => DECK_PHASE_ORDER.indexOf(phase));
  expect(ordinals, `unknown deck phase in ${observed.join(" → ")}`).not.toContain(-1);
  expect([...ordinals].sort((a, b) => a - b)).toEqual(ordinals);
  // The walk begins once the menu scene is already active, so the first sample is whatever phase
  // the deck had arrived at by then; "below" was asserted above, before the scene was reached.
  expect(observed[observed.length - 1]).toBe("revealed");
  expect(observed.length, "the deck jumped straight to revealed").toBeGreaterThan(1);

  // Every card front carries name + maker and nothing commerce-shaped (brief §7.3).
  await expect(page.locator("[data-menu-name]")).toHaveCount(VARIABLE_COUNTS.menuItems);
  await expect(page.locator("[data-menu-maker]")).toHaveCount(VARIABLE_COUNTS.menuItems);

  // Reversible (brief §19, "Menu"): scrolling back returns the deck to its undealt state.
  await scrollToRatio(page, 0);
  await expect(deck).toHaveAttribute("data-flipped-count", "0");
  await expect(page.locator("[data-menu-item][data-flipped='true']")).toHaveCount(0);
});

test("the fixture's four tracks are each reachable and the field is never empty", async ({
  page,
}) => {
  await openFixture(page, VARIABLE_COUNTS.slug);
  await scrollUntilScene(page, "tracks");

  const active = page.locator("[data-track][data-active='true']");
  const inField = page.locator("[data-track][data-in-field='true']");
  const next = page.locator("[data-carousel-control='next']");
  const previous = page.locator("[data-carousel-control='prev']");

  // Rewind to the first slide whatever the scroll position left behind.
  for (let click = 0; click < VARIABLE_COUNTS.tracks + 1; click += 1) await previous.click();
  await expect(active).toHaveAttribute("data-index", "0");

  for (let position = 1; position <= VARIABLE_COUNTS.tracks; position += 1) {
    await expect(active).toHaveCount(1);
    await expect(active).toContainText(fixtureTrackTitle(position));
    // A coverflow field with nothing painted in it is the failure this guards against.
    expect(await inField.count(), "the coverflow field must never be empty").toBeGreaterThan(0);
    if (position < VARIABLE_COUNTS.tracks) await next.click();
  }

  // Past the last slide the index clamps rather than wrapping into emptiness.
  await next.click();
  await expect(active).toHaveAttribute("data-index", String(VARIABLE_COUNTS.tracks - 1));
  await expect(active).toContainText(fixtureTrackTitle(VARIABLE_COUNTS.tracks));
});

test("six fixture art rows all render and each reveals as the sequence is read", async ({
  page,
}) => {
  await openFixture(page, VARIABLE_COUNTS.slug);

  const rows = page.locator("[data-art-piece]");
  await expect(rows).toHaveCount(VARIABLE_COUNTS.artPieces);
  // The rows are the list's only children — no filler row, and no divider with nothing after it.
  await expect(page.locator("[data-art-pieces] > *")).toHaveCount(VARIABLE_COUNTS.artPieces);

  const titles = await page.locator("[data-art-title]").allTextContents();
  expect(titles).toEqual(
    Array.from({ length: VARIABLE_COUNTS.artPieces }, (_, index) => fixtureArtTitle(index + 1)),
  );

  // Reading the section reveals every row, including the ones past W04's four.
  await scrollUntilScene(page, "artPieces");
  for (let step = 0; step <= 40; step += 1) {
    if ((await activeScene(page)) !== "artPieces") break;
    await scrollToRatio(page, (await currentRatio(page)) + 0.006);
  }
  await expect(page.locator("[data-art-piece][data-art-revealed='true']")).toHaveCount(
    VARIABLE_COUNTS.artPieces,
    { timeout: 15_000 },
  );
});

/* ========================================================== CONTENT ROW — schema minimums */

test("the schema minimums render gracefully, with nothing empty or stranded", async ({ page }) => {
  await openFixture(page, MINIMUM_COUNTS.slug);

  await expect(page.locator(`[data-lens="${MINIMUM_COUNTS.slug}"]`)).toHaveCount(1);

  // One hero message, one art piece, a three-item carousel: the smallest lens the schema allows.
  await expect(page.locator("[data-hero-message]")).toHaveCount(MINIMUM_COUNTS.heroMessages);
  await expect(page.locator("[data-menu-item]")).toHaveCount(MINIMUM_COUNTS.menuItems);
  await expect(page.locator("[data-film]")).toHaveCount(MINIMUM_COUNTS.films);
  await expect(page.locator("[data-track]")).toHaveCount(MINIMUM_COUNTS.tracks);
  await expect(page.locator("[data-art-piece]")).toHaveCount(MINIMUM_COUNTS.artPieces);
  await expect(page.locator("[data-art-count]")).toHaveText(MINIMUM_COUNTS.artHeadingCount);

  // A single art row is a ROW, not a divider with nothing after it: the list holds exactly one
  // child and that child carries its own title and rationale.
  await expect(page.locator("[data-art-pieces] > *")).toHaveCount(MINIMUM_COUNTS.artPieces);
  await expect(page.locator("[data-art-title]")).toHaveText(fixtureArtTitle(1));
  await expect(page.locator("[data-art-rationale]")).not.toHaveText("");

  // A single hero message still presents — the sequence does not need a second message to start.
  await expect(page.locator("[data-hero-message][data-active='true']")).toHaveCount(1);
});

test("a one-row art section still reveals, and the minimum lens scrolls to its end", async ({
  page,
}) => {
  await openFixture(page, MINIMUM_COUNTS.slug);

  // The whole journey completes: every scene is reached, in order, and the page ends at the
  // footer rather than stalling on a pin that a one-item section made degenerate.
  const forward = await walkScenes(page, 56);
  expect(forward[0]).toBe("loader");
  expect(forward[forward.length - 1]).toBe("footer");
  expect(forward).toEqual([
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
  ]);

  // The document really does reach its end — no dead zone at the bottom.
  await scrollToRatio(page, 1);
  const atEnd = await page.evaluate(() => {
    const doc = document.documentElement;
    return Math.abs(doc.scrollHeight - window.innerHeight - window.scrollY) <= 2;
  });
  expect(atEnd, "the minimum lens must scroll all the way to its end").toBe(true);

  // The single row is composed by the time the section has been read.
  await scrollUntilScene(page, "artPieces");
  for (let step = 0; step <= 30; step += 1) {
    if ((await activeScene(page)) !== "artPieces") break;
    await scrollToRatio(page, (await currentRatio(page)) + 0.008);
  }
  await expect(page.locator("[data-art-piece][data-art-revealed='true']")).toHaveCount(
    MINIMUM_COUNTS.artPieces,
    { timeout: 15_000 },
  );

  // Reverse: the journey walks back to the loader without a stranded scene.
  const backward = await walkScenes(page, 56, true);
  expect([...backward].reverse()).toEqual(forward);
  expect(await page.evaluate(() => window.scrollY)).toBe(0);
});

test("a three-item carousel paints a real field, not an empty one", async ({ page }) => {
  await openFixture(page, MINIMUM_COUNTS.slug);
  await scrollUntilScene(page, "tracks");

  const inField = page.locator("[data-track][data-in-field='true']");
  const active = page.locator("[data-track][data-active='true']");
  const next = page.locator("[data-carousel-control='next']");
  const previous = page.locator("[data-carousel-control='prev']");

  for (let click = 0; click < MINIMUM_COUNTS.tracks + 1; click += 1) await previous.click();
  await expect(active).toHaveAttribute("data-index", "0");

  for (let position = 1; position <= MINIMUM_COUNTS.tracks; position += 1) {
    await expect(active).toContainText(fixtureTrackTitle(position));
    expect(await inField.count()).toBeGreaterThan(0);
    if (position < MINIMUM_COUNTS.tracks) await next.click();
  }
  // With only three tracks the whole playlist is inside the field at once — nothing is stranded
  // outside it and nothing is painted that does not exist.
  expect(await inField.count()).toBeLessThanOrEqual(MINIMUM_COUNTS.tracks);
});

/* ================================================ CONTENT ROW — optional fields leave no gaps */

test("optional art-piece fields leave no gap, separator, or dangling label", async ({ page }) => {
  await page.goto("/");

  const pratfall = page.locator(`[data-art-piece][data-index="${PRATFALL_INDEX}"]`);
  await expect(pratfall.locator("[data-art-title]")).toHaveText(PRATFALL_TITLE);

  // This row has duration + label INSTEAD of creator/year (brief §7.9, W04 item 4).
  await expect(pratfall.locator("[data-art-creator]")).toHaveCount(0);
  await expect(pratfall.locator("[data-art-year]")).toHaveCount(0);
  await expect(pratfall.locator("[data-art-duration]")).toHaveText(PRATFALL_DURATION);
  await expect(pratfall.locator("[data-art-label]")).toHaveText(PRATFALL_LABEL_FA);

  // …and the meta line contains ONLY those two values. Removing them must leave nothing but
  // whitespace: no separator glyph, no stray punctuation, no empty span standing in for the
  // fields that are absent. (The rule between fields is a CSS border, which carries no text.)
  const metaText = await pratfall
    .locator("[data-art-line]", { has: page.locator("[data-art-duration]") })
    .textContent();
  const residue = (metaText ?? "").replace(PRATFALL_DURATION, "").replace(PRATFALL_LABEL_FA, "");
  expect(residue.trim(), `meta line left "${residue}" behind after its two fields`).toBe("");

  // The mirror case: the three credited rows carry creator + year and neither of the other two.
  for (const index of CREDITED_ART_INDICES) {
    const row = page.locator(`[data-art-piece][data-index="${index}"]`);
    await expect(row.locator("[data-art-creator]")).toHaveCount(1);
    await expect(row.locator("[data-art-year]")).toHaveCount(1);
    await expect(row.locator("[data-art-duration]")).toHaveCount(0);
    await expect(row.locator("[data-art-label]")).toHaveCount(0);
  }

  // W04 supplies no film `sourceUrl`, so no external-link affordance may be rendered for one.
  await expect(page.locator("[data-film-source-link]")).toHaveCount(0);
});

/* ================================================================== RIGHTS ROW — the four states */

/**
 * The four rights states through the content module's public API (brief §11 "Content rules",
 * §18). This runs in Node with no page: `rights.ts` is the authority every scene consults, so the
 * states are provable at their source. (`tests/unit/content.test.ts` covers the same functions in
 * more depth; this is the QA-matrix row stated as one table.)
 */
test.describe("rights states behave per brief §11", () => {
  const CASES: ReadonlyArray<{
    label: string;
    asset: MediaAsset;
    verdict: RightsVerdict;
    /** Whether the asset may paint, per environment, with no internal flag set. */
    displays: Record<RuntimeEnvironment, boolean>;
  }> = [
    {
      label: "approved",
      asset: assetIn("approved", true),
      verdict: "cleared",
      displays: { development: true, staging: true, production: true },
    },
    {
      label: "original-drop",
      asset: assetIn("original-drop", true),
      verdict: "cleared",
      displays: { development: true, staging: true, production: true },
    },
    {
      label: "development-mock",
      asset: assetIn("development-mock", false),
      verdict: "blocked",
      displays: { development: true, staging: true, production: false },
    },
    {
      label: "rights-pending",
      asset: assetIn("rights-pending", true),
      verdict: "blocked",
      displays: { development: false, staging: false, production: false },
    },
    {
      label: "replace-with-final",
      asset: assetIn("replace-with-final", true, { replacementNote: "final artwork pending" }),
      verdict: "awaiting-final",
      displays: { development: true, staging: true, production: false },
    },
    {
      label: "approved but productionAllowed: false",
      asset: assetIn("approved", false),
      verdict: "blocked",
      displays: { development: true, staging: true, production: false },
    },
  ];

  for (const { label, asset, verdict, displays } of CASES) {
    test(`${label}: verdict "${verdict}" and the documented display gating`, () => {
      expect(verdictFor(asset)).toBe(verdict);
      for (const environment of ["development", "staging", "production"] as const) {
        expect(
          canDisplayAsset(asset, environment),
          `${label} in ${environment}`,
        ).toBe(displays[environment]);
      }
    });
  }

  test("rights-pending displays in dev/staging ONLY behind the explicit internal flag", () => {
    const pending = assetIn("rights-pending", true);

    withEnv(SHOW_RIGHTS_PENDING_FLAG, "1", () => {
      expect(canDisplayAsset(pending, "development")).toBe(true);
      expect(canDisplayAsset(pending, "staging")).toBe(true);
      // Production is not a matter of flags. It never shows pending media.
      expect(canDisplayAsset(pending, "production")).toBe(false);
    });

    withEnv(SHOW_RIGHTS_PENDING_FLAG, undefined, () => {
      expect(canDisplayAsset(pending, "development")).toBe(false);
      expect(canDisplayAsset(pending, "staging")).toBe(false);
    });
  });

  test("development-mock and productionAllowed:false BLOCK the production build", () => {
    for (const asset of [assetIn("development-mock", false), assetIn("approved", false)]) {
      const lens = lensCarrying([asset]);
      expect(reviewMediaRights(lens).blocking).toHaveLength(1);
      expect(() => assertProductionMedia(lens)).toThrow(PRODUCTION_MEDIA_GUARD_FAILURE);
    }
  });

  test("a required replace-with-final asset fails by default and warns loudly on request", () => {
    const lens = lensCarrying([assetIn("replace-with-final", true)]);
    expect(reviewMediaRights(lens).awaitingFinal).toHaveLength(1);

    // Fail-closed default.
    expect(() => assertProductionMedia(lens)).toThrow(/replace-with-final/);

    // Explicitly downgraded: a LOUD warning that names the asset, and no block.
    const warnings: string[] = [];
    assertProductionMedia(lens, {
      onReplaceWithFinal: "warn",
      warn: (message) => warnings.push(message),
    });
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("WARNING");
    expect(warnings[0]).toContain("replace-with-final");
    // A warning is not a block: it must not carry the string CI greps for.
    expect(warnings[0]).not.toContain(PRODUCTION_MEDIA_GUARD_FAILURE);
  });

  test("approved and original-drop media clear the guard outright", () => {
    const lens = lensCarrying([assetIn("approved", true), assetIn("original-drop", true)]);
    const review = reviewMediaRights(lens);
    expect(review.blocking).toHaveLength(0);
    expect(review.awaitingFinal).toHaveLength(0);
    expect(review.cleared).toHaveLength(2);
    expect(() => assertProductionMedia(lens)).not.toThrow();
  });
});

/* ============================================ RIGHTS ROW — what the two builds actually paint */

test("the production build withholds the mock pack behind branded DROP placeholders", async ({
  page,
}) => {
  await page.goto("/");

  // The lens still declares what it is — the mode is data, not a rendering decision.
  await expect(page.locator("[data-content-mode='development-mock']")).toHaveCount(1);

  const painted = page.locator("[data-art-media-painted='true']");
  const withheld = page.locator("[data-art-media-painted='false']");
  const posterPainted = page.locator("[data-poster-state='painted']");
  const posterWithheld = page.locator("[data-poster-state='withheld']");
  const artworkAsset = page.locator("[data-track-artwork='asset']");
  const artworkPlaceholder = page.locator("[data-track-artwork='placeholder']");
  const menuAsset = page.locator("[data-menu-image='asset']");
  const menuPlaceholder = page.locator("[data-menu-image='placeholder']");

  // CORRECT BEHAVIOR, not a defect: `canDisplayAsset` gates `development-mock` to dev/staging.
  await expect(painted).toHaveCount(0);
  await expect(posterPainted).toHaveCount(0);
  await expect(artworkAsset).toHaveCount(0);
  await expect(menuAsset).toHaveCount(0);

  // …and every withheld slot is a branded stand-in, never a broken image or an empty box.
  const withheldTotal =
    (await withheld.count()) +
    (await posterWithheld.count()) +
    (await artworkPlaceholder.count()) +
    (await menuPlaceholder.count());
  expect(withheldTotal, "every mock asset has a placeholder slot").toBe(MOCK_ASSET_COUNT);
  await expect(page.locator("[data-art-media-painted='false'] img")).toHaveCount(0);
  await expect(page.locator("[data-poster-state='withheld'] img")).toHaveCount(0);
  // A credit belongs to a painted asset; a withheld slot must not caption an absent image.
  await expect(page.locator("[data-art-media-credit]")).toHaveCount(0);

  // The stand-ins keep the asset's own localized description as their accessible name, so the
  // meaning of the slot survives the substitution (brief §16).
  const placeholderNames = await page
    .locator("[data-menu-image='placeholder'], [data-poster-state='withheld'] [role='img']")
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("aria-label") ?? ""));
  expect(placeholderNames.length).toBeGreaterThan(0);
  for (const name of placeholderNames) expect(name.trim()).not.toBe("");
});

test("the development build paints the mock pack and reports its content mode", async ({
  page,
}) => {
  let reachable = true;
  try {
    await page.goto(`${DEV_ORIGIN}/`, { waitUntil: "load" });
  } catch (error) {
    reachable = false;
    test.skip(true, `no development server at ${DEV_ORIGIN} (${String(error)})`);
  }
  if (!reachable) return;

  await expect(page.locator("[data-content-mode='development-mock']")).toHaveCount(1);

  // The mirror of the production expectation: in development the mock pack is what renders.
  await expect(page.locator("[data-art-media-painted='false']")).toHaveCount(0);
  await expect(page.locator("[data-poster-state='withheld']")).toHaveCount(0);
  await expect(page.locator("[data-menu-image='placeholder']")).toHaveCount(0);
  expect(await page.locator("[data-art-media-painted='true']").count()).toBeGreaterThan(0);

  // Ticket 15: `contentMode: "development-mock"` visible in dev diagnostics. The diagnostics
  // object is published by an effect once the scene machine has mounted, so this polls rather
  // than reading once — a race here would be a flaky pass, not a flaky failure.
  await expect
    .poll(
      () =>
        page.evaluate(
          () =>
            (window as unknown as { __dropSceneDiagnostics?: { contentMode?: string } })
              .__dropSceneDiagnostics?.contentMode ?? null,
        ),
      { message: "dev diagnostics must report the lens's content mode", timeout: 20_000 },
    )
    .toBe("development-mock");
});

/* ================================================== ROUTES — the fixture harness never ships */

test("the development-only fixture route is absent from the production build", async ({
  page,
  request,
}) => {
  for (const slug of [VARIABLE_COUNTS.slug, MINIMUM_COUNTS.slug]) {
    const response = await request.get(FIXTURE_ROUTE(slug));
    expect(
      response.status(),
      `${FIXTURE_ROUTE(slug)} must not be reachable on a production build`,
    ).toBe(404);
  }

  /*
   * The gate itself, cross-checked on a route that is COMPILED INTO this production build.
   *
   * The two assertions above are satisfied by a build that predates the fixture route, which
   * would 404 for the wrong reason (the page simply is not there). `/brand-preview` is the
   * control: it is in the production bundle and gates itself with the same
   * `process.env.NODE_ENV === "production" → notFound()` idiom the fixture route uses. Its 404
   * therefore proves that idiom really does refuse a request in this build, which is the part
   * absence cannot prove.
   */
  expect(
    (await request.get("/brand-preview")).status(),
    "the dev-harness gate must refuse requests in a production build",
  ).toBe(404);

  // And nothing on the shipped site links to any development harness.
  await page.goto("/");
  await expect(page.locator("a[href*='/dev/']")).toHaveCount(0);
});

/* ------------------------------------------------------------------------------ tiny helper */

/** The page's current scroll position as a fraction of its scrollable range. */
async function currentRatio(page: Page): Promise<number> {
  return page.evaluate(() => {
    const range = document.documentElement.scrollHeight - window.innerHeight;
    return range <= 0 ? 0 : window.scrollY / range;
  });
}
