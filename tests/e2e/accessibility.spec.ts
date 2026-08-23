import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test as base, type Page } from "@playwright/test";

/**
 * Accessibility — page seam (BUILD-GUIDE seam 3; ticket 15, sixth acceptance box; brief §16).
 *
 * Brief §16, item by item, and where each one is proved:
 *
 * | §16 requirement | here |
 * | --- | --- |
 * | Semantic headings and section landmarks | `semantic structure` tests |
 * | `lang="fa"`, `dir="rtl"` on text containers; editorial L/R held by CSS grid, not direction hacks | `document language` + `Latin runs` |
 * | All meaningful media has localized alt text | `alt text` |
 * | Decorative canvas and shader layers hidden from assistive technology | `decorative canvas` |
 * | Carousel supports keyboard arrows and clear focus states | `keyboard` tests |
 * | Controls have accessible labels | `keyboard` tests |
 * | No autoplay audio; loop video muted, inline, pausable | `no autoplaying audio` |
 * | Respect `prefers-reduced-motion`; no content lost | **`reduced-motion.spec.ts`** — not repeated here |
 * | Maintain WCAG AA text contrast | **`[manual]`** — see the procedure at the foot of this file |
 * | Do not flash or strobe | **`[manual]`** — a shader property; no DOM signal exists for it |
 * | External links announce/open safely | `external links` |
 *
 * ## Rules this file obeys
 *
 * - **Attributes, accessible names and text only.** Focus visibility is asserted by whether the
 *   focused element *matches `:focus-visible`* — the selector the stylesheet keys its ring off —
 *   never by reading a computed outline, which is the styling layer's business.
 * - **Expected values come from the W04 seed and the brief**, transcribed below.
 * - **WebGL pixels are never asserted.** In particular, text contrast over a live shader is a
 *   `[manual]` box: Lighthouse and axe both silently skip text over a canvas, so a green automated
 *   run says nothing about it. No test here pretends otherwise.
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

type SceneId = (typeof SCENE_ORDER_FROM_BRIEF)[number];

/**
 * The scenes that carry no content of their own. Brief §7.5/§7.7 make the pixel transitions pure
 * background choreography, and the loader is an overlay — all three have nothing to announce.
 */
const DECORATIVE_SCENES: readonly SceneId[] = ["loader", "pixelA", "pixelB"];

/**
 * W04 seed — `handoff/04-mock-content/src/content/lenses/beautiful-imperfection.mock.json`,
 * transcribed. Accessible names for the scene regions come from the lens, so these are the
 * expected region labels too.
 */
const LENS_TITLE_FA = "زیبایی در کامل نبودن";
const GRID_STATEMENT_FA = "جایی با یک نگاه مشخص.";
const FOOTER_STATEMENT_FA = "جایی با یک نگاه مشخص.";
const SECTION_LABELS_FA = {
  menu: "انتخاب مزه",
  films: "سه نگاه",
  tracks: "قطعه‌ها",
  artPieces: "قطعه‌های هنری / یادداشت‌ها",
} as const;

/** The scene regions and the lens string each one must be named by. */
const SCENE_REGION_LABELS: ReadonlyArray<readonly [SceneId, string]> = [
  ["thesis", LENS_TITLE_FA],
  ["menu", SECTION_LABELS_FA.menu],
  ["gridStatement", GRID_STATEMENT_FA],
  ["films", SECTION_LABELS_FA.films],
  ["tracks", SECTION_LABELS_FA.tracks],
  ["artPieces", SECTION_LABELS_FA.artPieces],
  ["footer", FOOTER_STATEMENT_FA],
];

/** Localized alt text, from the seed's media assets. Never a filename, never empty (brief §11). */
const MENU_MEDIA_ALT_FA = [
  "تارت میوهٔ دست‌ساز روی سطح تیره",
  "شش موچی دست‌ساز در یک جعبهٔ مشکی",
] as const;

const FILM_POSTER_ALT_FA = [
  "مطالعهٔ مفهومی یک مجسمهٔ پرندهٔ گِلی در کارگاه",
  "نور صبح و سایهٔ برگ‌ها روی دیوار تیره کنار یک پارچهٔ آبی تاخورده",
  "دفترچه و مداد قرمز روی صندلی خالی اتوبوس",
] as const;

const TRACK_ARTWORK_ALT_FA = [
  "رنگدانهٔ آبی در آب",
  "حلقهٔ کاغذی با لبهٔ دست‌کنده",
  "کاسهٔ چینی دست‌ساز با خط کبالت",
  "حلقه‌های موج روی آب سیاه",
  "برگ فرسوده میان ورق‌های نیمه‌شفاف",
  "بافت شعاعی نخ‌های سیاه و نارنجی",
  "دیسک رزین کهربایی با حباب‌های هوا",
  "غشای بنفش شفاف دور یک مرکز سیاه",
  "لایه‌های پارچهٔ دودی دور یک نور کم",
  "دو نشان روشن کوچک روی کاغذ سیاه",
  "برگ‌های استوایی تیره در یک چیدمان حلقه‌ای",
] as const;

const ART_MEDIA_ALT_FA = [
  "مطالعهٔ مفهومی بتن، آب و یک بازشوی دایره‌ای",
  "فرم آویزان ساخته‌شده از حلقه‌های فلزی دست‌ساز",
  "ورقهٔ آب و قطره‌ها در نور روی پس‌زمینهٔ تیره",
  "شبکه‌ای از فنجان‌های مشکی با یک لکهٔ کوچک نارنجی",
] as const;

const TRACK_TITLES_EN = [
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
] as const;

const FILM_TITLES_EN = ["SHOWING UP", "PERFECT DAYS", "PATERSON"] as const;

/**
 * Interface copy the scenes own (the lens schema carries no accessibility strings), transcribed
 * from the components they are declared in. Persian, because Persian is the primary language.
 */
const SKIP_LINK_LABEL_FA = "پرش به محتوای اصلی";
const CAROUSEL_PREVIOUS_LABEL_FA = "قطعهٔ قبلی";
const CAROUSEL_NEXT_LABEL_FA = "قطعهٔ بعدی";

/** Brief §7.10: five metadata slots, all disabled until final destinations exist. */
const FOOTER_SLOT_COUNT = 5;

/** Brief §7.1: "Cap the loader at 4 seconds." Plus room for a cold start and the navigation. */
const LOADER_SETTLE_TIMEOUT_MS = 15_000;

/* ------------------------------------------------------------------------------- fixtures */

/** Brief §17: "No console errors, WebGL warnings, or accumulating ScrollTriggers." */
const test = base.extend<{ consoleErrors: string[] }>({
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(`console.error: ${message.text()}`);
      });
      page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
      await use(errors);
      expect(errors, "the page must produce no console errors").toEqual([]);
    },
    { auto: true },
  ],
});

test.describe.configure({ timeout: 150_000 });

/* -------------------------------------------------------------------------------- helpers */

async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

async function waitPastLoader(page: Page): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.dropLoader), {
      timeout: LOADER_SETTLE_TIMEOUT_MS,
      message: "the loader never reported itself complete",
    })
    .toBe("complete");
  await expect(page.locator("[data-loader-overlay]")).toHaveCount(0);
}

async function openJourney(page: Page, route = "/"): Promise<void> {
  const response = await page.goto(route);
  expect(response?.status(), `${route} must be served`).toBe(200);
  await waitPastLoader(page);
}

/** Scroll into a scene's own section by that section's live geometry. An input, never a claim. */
async function scrollIntoScene(page: Page, sceneId: SceneId, fraction = 0.5): Promise<void> {
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

/** The carousel's published active index. */
async function trackIndex(page: Page): Promise<number> {
  const raw = await page.locator("[data-tracks-carousel]").getAttribute("data-track-index");
  return Number(raw);
}

/**
 * What is focused right now, described only by things this file is allowed to observe: the tag,
 * the accessible label, the data hooks, and whether the element matches `:focus-visible`.
 */
type FocusReport = {
  tag: string;
  label: string;
  href: string | null;
  /** `data-*` attribute names on the focused element. */
  hookNames: string[];
  /** The same attributes as `name=value`, for hooks whose value distinguishes them. */
  hooks: string[];
  focusVisible: boolean;
  insideBackgroundCanvas: boolean;
  insideFooter: boolean;
  scene: string | null;
};

async function focusReport(page: Page): Promise<FocusReport | null> {
  return page.evaluate(() => {
    const element = document.activeElement;
    if (!element || element === document.body || element === document.documentElement) return null;
    const dataAttributes = [...element.attributes].filter((attribute) =>
      attribute.name.startsWith("data-"),
    );
    const hookNames = dataAttributes.map((attribute) => attribute.name);
    const hooks = dataAttributes.map((attribute) =>
      attribute.value === "" ? attribute.name : `${attribute.name}=${attribute.value}`,
    );
    let focusVisible = false;
    try {
      focusVisible = element.matches(":focus-visible");
    } catch {
      focusVisible = false;
    }
    return {
      tag: element.tagName,
      label:
        element.getAttribute("aria-label") ??
        (element.textContent ?? "").replace(/\s+/g, " ").trim(),
      href: element.getAttribute("href"),
      hookNames,
      hooks,
      focusVisible,
      insideBackgroundCanvas: element.closest("[data-background-canvas]") !== null,
      insideFooter: element.closest("[data-footer]") !== null,
      scene: element.closest("[data-scene]")?.getAttribute("data-scene") ?? null,
    };
  });
}

/** Press Tab until the cycle repeats, recording each stop. */
async function tabCycle(page: Page, limit = 40): Promise<FocusReport[]> {
  const stops: FocusReport[] = [];
  const seen = new Set<string>();
  for (let step = 0; step < limit; step += 1) {
    await page.keyboard.press("Tab");
    const report = await focusReport(page);
    if (report === null) break; // focus returned to the document — the cycle is closed
    const key = `${report.tag}|${report.label}|${report.hooks.join(",")}`;
    if (seen.has(key)) break;
    seen.add(key);
    stops.push(report);
  }
  return stops;
}

/* ============================================================ semantics: language and direction */

/**
 * Brief §16: "Persian pages use `lang='fa'` and appropriate `dir='rtl'` for text containers", and
 * "the deliberately left/right editorial layout remains controlled by CSS grid, not document
 * direction hacks" — so `dir` never flips on the document to lay out the film scene.
 */
test("Persian is the document language and the document direction is RTL", async ({ page }) => {
  await openJourney(page);

  await expect(page.locator("html")).toHaveAttribute("lang", "fa");
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");

  // The film scene is the one with a deliberate left/right composition. It must not have been
  // achieved by flipping direction on an ancestor of the whole page.
  await scrollIntoScene(page, "films", 0.3);
  const ltrAncestorsOfFilms = await page.evaluate(() => {
    const section = document.querySelector('[data-scene="films"]');
    const chain: string[] = [];
    for (let node = section?.parentElement ?? null; node !== null; node = node.parentElement) {
      const dir = node.getAttribute("dir");
      if (dir !== null) chain.push(`${node.tagName}[dir=${dir}]`);
    }
    return chain;
  });
  expect(
    ltrAncestorsOfFilms.filter((entry) => entry.includes("ltr")),
    "the film layout must not be produced by flipping document direction",
  ).toEqual([]);
});

/**
 * Brief §16 again: Latin editorial runs inside a Persian document declare their own language and
 * direction, so a screen reader switches voice and the bidi algorithm places them correctly.
 */
test("Latin editorial runs carry their own lang and dir", async ({ page }) => {
  await openJourney(page);

  await scrollIntoScene(page, "films", 0.15);
  const filmTitle = page.locator("[data-film-title]").first();
  await expect(filmTitle).toHaveAttribute("lang", "en");
  await expect(filmTitle).toHaveAttribute("dir", "ltr");
  expect(FILM_TITLES_EN).toContain((await filmTitle.textContent())?.trim());

  await scrollIntoScene(page, "tracks", 0.1);
  for (const selector of ["[data-track-title]", "[data-track-artist]"]) {
    const runs = await page.evaluate(
      (css) =>
        [...document.querySelectorAll(css)].map((element) => ({
          lang: element.getAttribute("lang"),
          dir: element.getAttribute("dir"),
        })),
      selector,
    );
    expect(runs.length, `${selector} must exist to be checked`).toBeGreaterThan(0);
    expect(
      runs.every((run) => run.lang === "en" && run.dir === "ltr"),
      `every ${selector} is declared as a Latin run`,
    ).toBe(true);
  }

  await scrollIntoScene(page, "artPieces", 0.5);
  const artTitle = page.locator("[data-art-title]").first();
  await expect(artTitle).toHaveAttribute("lang", "en");
  await expect(artTitle).toHaveAttribute("dir", "ltr");

  // Persian editorial containers declare RTL explicitly rather than relying on inheritance alone.
  await scrollIntoScene(page, "thesis", 0.2);
  await expect(page.locator("[data-lens-title]")).toHaveAttribute("dir", "rtl");
  await expect(page.locator("[data-footer-statement]")).toHaveAttribute("dir", "rtl");
});

/* ============================================================ semantics: headings and landmarks */

/**
 * Brief §16: "Semantic headings and section landmarks."
 *
 * Asserted structurally: one `h1`, no level skipped in document order, and no heading that is
 * empty. Which words are in them is `lens-page.spec.ts`'s business, not this file's.
 */
test("the heading hierarchy is sensible and every heading carries text", async ({ page }) => {
  await openJourney(page);

  const headings = await page.evaluate(() =>
    [...document.querySelectorAll("h1, h2, h3, h4, h5, h6")].map((heading) => ({
      level: Number(heading.tagName.slice(1)),
      text: (heading.textContent ?? "").replace(/\s+/g, " ").trim(),
      scene: heading.closest("[data-scene]")?.getAttribute("data-scene") ?? null,
    })),
  );

  expect(headings.length, "the page has headings").toBeGreaterThan(0);
  expect(
    headings.filter((heading) => heading.level === 1),
    "exactly one h1 — the lens title",
  ).toHaveLength(1);
  expect(headings[0]?.level, "the first heading is the h1").toBe(1);
  expect(
    headings.filter((heading) => heading.text === ""),
    "no empty headings",
  ).toEqual([]);

  const skips = headings
    .map((heading, index) =>
      index > 0 && heading.level - headings[index - 1]!.level > 1
        ? `${headings[index - 1]!.text} (h${headings[index - 1]!.level}) → ${heading.text} (h${heading.level})`
        : null,
    )
    .filter((entry): entry is string => entry !== null);
  expect(skips, "heading levels never skip a step").toEqual([]);
});

/**
 * Landmarks: one `main` wrapping the journey, and each content-bearing scene a named region.
 * The region names come from the lens data (brief hard rule: no invented section copy), so the
 * expected labels are the seed's own strings.
 */
test("landmarks exist and every content scene is a region named from the lens data", async ({
  page,
}) => {
  await openJourney(page);

  await expect(page.locator("main")).toHaveCount(1);
  await expect(page.locator("main [data-active-scene]")).toHaveCount(1);
  await expect(page.locator("header")).toHaveCount(1);

  for (const [sceneId, label] of SCENE_REGION_LABELS) {
    const section = page.locator(`[data-scene="${sceneId}"]`);
    await expect(section, `scene "${sceneId}" is a labelled region`).toHaveAttribute(
      "aria-label",
      label,
    );
    await expect(section).not.toHaveAttribute("aria-hidden", "true");
  }

  for (const sceneId of DECORATIVE_SCENES) {
    await expect(
      page.locator(`[data-scene="${sceneId}"]`),
      `decorative scene "${sceneId}" is hidden from assistive technology`,
    ).toHaveAttribute("aria-hidden", "true");
  }

  // The skip link is the first thing in the document and targets the main landmark.
  const skip = page.locator(`a[href="#main"]`);
  await expect(skip).toHaveCount(1);
  await expect(skip).toHaveText(SKIP_LINK_LABEL_FA);
});

/* ==================================================================== media and alt text */

/**
 * Brief §16: "All meaningful media has localized alt text." Every media slot exposes it, whether
 * the asset painted or the rights guard withheld it — in a production build the mock pack is
 * `development-mock` and `canDisplayAsset` substitutes a branded DROP placeholder, and the alt
 * text has to travel with the placeholder too (brief §11, §18).
 *
 * Read from the accessible name of the slot: `img[alt]` when the asset painted, the
 * `role="img"` + `aria-label` placeholder when it did not.
 */
async function mediaNames(page: Page, slotSelector: string): Promise<string[]> {
  return page.evaluate((css) => {
    const named = (element: Element): string => {
      if (element instanceof HTMLImageElement) return element.getAttribute("alt") ?? "";
      const inner = element.querySelector("img[alt], [role='img'][aria-label]");
      if (inner instanceof HTMLImageElement) return inner.getAttribute("alt") ?? "";
      if (inner) return inner.getAttribute("aria-label") ?? "";
      return element.getAttribute("aria-label") ?? "";
    };
    return [...document.querySelectorAll(css)].map(named);
  }, slotSelector);
}

test("every meaningful media slot carries its localized alt text from the data", async ({
  page,
}) => {
  await openJourney(page);

  await scrollIntoScene(page, "menu", 0.9);
  expect(await mediaNames(page, "[data-menu-image]"), "menu card imagery").toEqual([
    ...MENU_MEDIA_ALT_FA,
  ]);

  await scrollIntoScene(page, "films", 0.5);
  expect(await mediaNames(page, "[data-film-media]"), "film posters").toEqual([
    ...FILM_POSTER_ALT_FA,
  ]);

  await scrollIntoScene(page, "tracks", 0.3);
  expect(await mediaNames(page, "[data-track-artwork]"), "track artwork discs").toEqual([
    ...TRACK_ARTWORK_ALT_FA,
  ]);

  await scrollIntoScene(page, "artPieces", 0.8);
  expect(await mediaNames(page, "[data-art-media]"), "art piece media").toEqual([
    ...ART_MEDIA_ALT_FA,
  ]);

  // The negative half of the same rule: never empty, and never a filename standing in for a
  // description. Checked across every slot on the page at once.
  const allNames = [
    ...(await mediaNames(page, "[data-menu-image]")),
    ...(await mediaNames(page, "[data-film-media]")),
    ...(await mediaNames(page, "[data-track-artwork]")),
    ...(await mediaNames(page, "[data-art-media]")),
  ];
  expect(allNames.length).toBe(
    MENU_MEDIA_ALT_FA.length +
      FILM_POSTER_ALT_FA.length +
      TRACK_ARTWORK_ALT_FA.length +
      ART_MEDIA_ALT_FA.length,
  );
  expect(
    allNames.filter((name) => name.trim() === ""),
    "no media slot has an empty accessible name",
  ).toEqual([]);
  expect(
    allNames.filter((name) => /\.(webp|png|jpe?g|gif|svg|webm|mp4)\b/i.test(name) || name.includes("/")),
    "alt text is a description, never a filename or a path",
  ).toEqual([]);
});

/**
 * Brief §12/§16: "Decorative canvas and shader layers are hidden from assistive technology."
 * The one persistent canvas is inside an `aria-hidden` root and is not focusable — neither by an
 * explicit tabindex nor by turning up in the tab cycle.
 */
test("the decorative WebGL canvas is hidden from assistive technology and not focusable", async ({
  page,
}) => {
  await openJourney(page);

  const root = page.locator("[data-background-canvas]");
  await expect(root).toHaveCount(1);
  await expect(root).toHaveAttribute("aria-hidden", "true");

  const canvases = await page.evaluate(() =>
    [...document.querySelectorAll("canvas")].map((canvas) => ({
      tabindex: canvas.getAttribute("tabindex"),
      hiddenFromAt: canvas.closest('[aria-hidden="true"]') !== null,
      contentEditable: canvas.getAttribute("contenteditable"),
    })),
  );
  expect(canvases.length, "the shared canvas is present in this run").toBeGreaterThan(0);
  for (const canvas of canvases) {
    expect(canvas.hiddenFromAt, "every canvas sits inside an aria-hidden layer").toBe(true);
    expect(canvas.tabindex, "a decorative canvas is never given a tab stop").toBeNull();
    expect(canvas.contentEditable).toBeNull();
  }

  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior }));
  const stops = await tabCycle(page);
  expect(
    stops.filter((stop) => stop.insideBackgroundCanvas),
    "tabbing never lands inside the background canvas",
  ).toEqual([]);
});

/* ============================================================================== keyboard */

/**
 * Brief §16: "Carousel supports keyboard arrows and clear focus states" and "Controls have
 * accessible labels".
 *
 * Focus visibility is asserted as `:focus-visible` matching — the selector the stylesheet keys its
 * ring off — rather than by reading a computed outline, which would be testing the styling layer.
 */
test("every carousel control is keyboard operable, labelled, and shows a visible focus state", async ({
  page,
}) => {
  await openJourney(page);
  await scrollIntoScene(page, "tracks", 0.4);

  const controls: ReadonlyArray<readonly [string, string]> = [
    ['[data-carousel-control="prev"]', CAROUSEL_PREVIOUS_LABEL_FA],
    ['[data-carousel-control="next"]', CAROUSEL_NEXT_LABEL_FA],
  ];

  for (const [selector, label] of controls) {
    const control = page.locator(selector);
    await expect(control, `${selector} exists on every viewport`).toHaveCount(1);
    await expect(control).toHaveAttribute("aria-label", label);
    // Never disabled at the ends — a control that leaves the interaction model at an edge is a
    // control a keyboard user cannot rely on (brief §7.8).
    await expect(control).not.toBeDisabled();

    await control.focus();
    const report = await focusReport(page);
    expect(report?.label, `${selector} takes focus`).toBe(label);
    expect(report?.focusVisible, `${selector} matches :focus-visible when focused`).toBe(true);
  }

  // The active case is the carousel's single tab stop, and it is labelled from the track data.
  const activeCase = page.locator('[data-track][data-active="true"] [data-track-case]');
  await activeCase.focus();
  const caseReport = await focusReport(page);
  expect(caseReport?.focusVisible, "the active case shows a visible focus state").toBe(true);
  const caseLabel = caseReport?.label ?? "";
  expect(
    TRACK_TITLES_EN.some((title) => caseLabel.includes(title)),
    `the case label names its track — got "${caseLabel}"`,
  ).toBe(true);

  // Operating the controls from the keyboard, not by clicking them.
  const start = await trackIndex(page);
  await page.locator('[data-carousel-control="next"]').focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => trackIndex(page)).toBe(start + 1);
  await page.locator('[data-carousel-control="prev"]').focus();
  await page.keyboard.press("Space");
  await expect.poll(() => trackIndex(page)).toBe(start);
});

/**
 * The carousel's arrow-key contract. The coverflow field is composed physically left-to-right
 * inside an RTL document (brief §16 keeps the editorial layout in CSS, not in direction), so
 * `ArrowRight` advances and `ArrowLeft` retreats, and `Home`/`End` jump to the ends.
 */
test("the tracks carousel advances and retreats with the arrow keys", async ({ page }) => {
  await openJourney(page);
  await scrollIntoScene(page, "tracks", 0.4);

  await page.locator('[data-track][data-active="true"] [data-track-case]').focus();
  const start = await trackIndex(page);
  expect(start).toBeGreaterThan(0);

  await page.keyboard.press("ArrowRight");
  await expect.poll(() => trackIndex(page)).toBe(start + 1);
  await page.keyboard.press("ArrowLeft");
  await expect.poll(() => trackIndex(page)).toBe(start);

  await page.keyboard.press("End");
  await expect.poll(() => trackIndex(page)).toBe(TRACK_TITLES_EN.length - 1);
  await page.keyboard.press("Home");
  await expect.poll(() => trackIndex(page)).toBe(0);

  // The roving tab stop follows the active case, so a keyboard user never loses focus into an
  // element the field has since made inert.
  const report = await focusReport(page);
  expect(report?.hookNames, "focus stayed on a case").toContain("data-track-case");
  expect(report?.focusVisible).toBe(true);
});

/**
 * Nothing depends on hover: the whole journey is completed below without the pointer ever moving —
 * Playwright only dispatches mouse events when asked to, and this test asks for none. Every
 * control is reached with `Tab`, operated with the keyboard, and identified by its accessible name.
 *
 * Sequential `Tab` traversal is asserted on engines with a standard tab order. **Safari is
 * excluded**: with "Full Keyboard Access" off — its factory default — WebKit's `Tab` visits only
 * form controls and elements carrying an explicit `tabindex`, so the skip link and the arrow
 * buttons are skipped there. That is a browser preference, applied to every site, not a property
 * of this page; the substance (each control focusable, labelled, `:focus-visible`, and operable
 * from the keyboard) is asserted on every engine by the tests above.
 */
test("a keyboard-only visitor can operate the page without a pointer", async ({
  page,
  browserName,
}) => {
  test.skip(
    browserName === "webkit",
    "WebKit's default Tab order excludes links and buttons unless Full Keyboard Access is on; " +
      "the same controls are asserted focusable, labelled and operable on WebKit by the other " +
      "tests in this file.",
  );

  await openJourney(page);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior }));

  const stops = await tabCycle(page);
  expect(stops.length, "the page has reachable controls").toBeGreaterThan(0);

  // First stop is the skip link, and it is announced in Persian.
  expect(stops[0]?.href, "the first tab stop is the skip link").toBe("#main");
  expect(stops[0]?.label).toBe(SKIP_LINK_LABEL_FA);

  // Every stop is a real, named control with a visible focus state.
  for (const stop of stops) {
    expect(stop.label.trim(), `a tab stop with no accessible name: ${stop.hooks.join(" ")}`).not.toBe(
      "",
    );
    expect(stop.focusVisible, `no visible focus state on ${stop.label}`).toBe(true);
    expect(stop.insideBackgroundCanvas).toBe(false);
    expect(stop.insideFooter, "the disabled footer slots are not focusable").toBe(false);
  }

  // The carousel's controls are all reachable this way.
  expect(stops.flatMap((stop) => stop.hookNames)).toContain("data-track-case");
  const hooks = stops.flatMap((stop) => stop.hooks);
  expect(hooks).toContain("data-carousel-control=prev");
  expect(hooks).toContain("data-carousel-control=next");

  // Activating the skip link moves focus into the main landmark.
  await page.keyboard.press("Home");
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior }));
  await page.locator('a[href="#main"]').focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
});

/* ================================================================= links, audio and video */

/**
 * Brief §16: "External links announce/open safely", and §7.10: "Do not invent live destinations."
 *
 * The seed carries no `sourceUrl` on any film, track or art piece, so W04 renders no external
 * link at all — which is itself the assertion worth making (nothing invented a destination). The
 * safety contract is written as an invariant over whatever anchors DO exist, so it becomes live
 * coverage the moment a lens supplies a `sourceUrl`, without this file changing.
 */
test("external links are announced and open safely, and no destination is invented", async ({
  page,
}) => {
  await openJourney(page);

  const anchors: {
    href: string | null;
    rel: string | null;
    target: string | null;
    name: string;
    external: string | null;
  }[] = [];

  for (const sceneId of SCENE_ORDER_FROM_BRIEF) {
    await scrollIntoScene(page, sceneId, 0.6);
    const found = await page.evaluate(() =>
      [...document.querySelectorAll("a")].map((anchor) => ({
        href: anchor.getAttribute("href"),
        rel: anchor.getAttribute("rel"),
        target: anchor.getAttribute("target"),
        name: (
          anchor.getAttribute("aria-label") ??
          `${anchor.textContent ?? ""} ${
            document.getElementById(anchor.getAttribute("aria-describedby") ?? "")?.textContent ?? ""
          }`
        )
          .replace(/\s+/g, " ")
          .trim(),
        external: anchor.getAttribute("data-external"),
      })),
    );
    for (const anchor of found) {
      if (!anchors.some((seen) => seen.href === anchor.href && seen.name === anchor.name)) {
        anchors.push(anchor);
      }
    }
  }

  const inPage = anchors.filter((anchor) => (anchor.href ?? "").startsWith("#"));
  const offSite = anchors.filter((anchor) => /^[a-z]+:\/\//i.test(anchor.href ?? ""));
  const other = anchors.filter(
    (anchor) => !inPage.includes(anchor) && !offSite.includes(anchor),
  );

  // The only in-page anchor is the skip link.
  expect(inPage.map((anchor) => anchor.href)).toEqual(["#main"]);
  // Nothing else: no relative anchor the content never asked for.
  expect(other, "no anchor with a destination the data did not supply").toEqual([]);

  for (const anchor of offSite) {
    expect(anchor.rel ?? "", `rel on ${anchor.href}`).toContain("noopener");
    expect(anchor.target, `${anchor.href} opens in a new context`).toBe("_blank");
    expect(
      anchor.name,
      `${anchor.href} must be announced as leaving the site`,
    ).not.toBe("");
    expect(anchor.external, `${anchor.href} is flagged as external`).toBe("true");
  }

  test
    .info()
    .annotations.push({
      type: "coverage",
      description:
        `${offSite.length} external link(s) exercised. The W04 seed supplies no sourceUrl on any ` +
        "film, track or art piece, so the external-link branch of this invariant is unexercised " +
        "by the launch content — it is asserted, not demonstrated. Add a lens with a sourceUrl to " +
        "make it live coverage.",
    });
});

/**
 * Brief §7.10 and the hard rules: a disabled slot renders as text, not as a dead link, and the CTA
 * ships disabled — never as a pill, a waitlist, or a "schedule demo" button copied from the
 * layout reference.
 */
test("disabled footer slots are inert text, not focusable links", async ({ page }) => {
  await openJourney(page);
  await scrollIntoScene(page, "footer", 1);

  await expect(page.locator("[data-footer-link]")).toHaveCount(FOOTER_SLOT_COUNT);
  await expect(page.locator('[data-footer-link][data-enabled="false"] a')).toHaveCount(0);
  await expect(page.locator('[data-footer-link][data-enabled="false"] button')).toHaveCount(0);

  const cta = page.locator("[data-footer-cta]");
  await expect(cta).toHaveCount(1);
  await expect(cta).toHaveAttribute("data-enabled", "false");
  expect(
    await cta.evaluate((element) => element.tagName),
    "a disabled CTA is not an anchor or a button",
  ).not.toMatch(/^(A|BUTTON)$/);

  // And nothing in the footer takes focus.
  const focusableInFooter = await page.evaluate(() => {
    const footer = document.querySelector("[data-footer]");
    if (!footer) return ["no footer"];
    return [
      ...footer.querySelectorAll(
        'a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])',
      ),
    ].map((element) => element.tagName);
  });
  expect(focusableInFooter, "the footer contains no focusable control").toEqual([]);
});

/**
 * Brief §16: "No autoplay audio" and "Any loop video is muted, inline, and pausable when required."
 *
 * W04 ships images only, so the video branch is an invariant rather than a demonstration — the
 * annotation below records that honestly.
 */
test("nothing autoplays audio, and any loop video is muted and inline", async ({ page }) => {
  await openJourney(page);

  const media: { audio: number; videos: { muted: boolean; inline: boolean; loop: boolean; controllable: boolean }[] }[] =
    [];
  for (const sceneId of SCENE_ORDER_FROM_BRIEF) {
    await scrollIntoScene(page, sceneId, 0.6);
    media.push(
      await page.evaluate(() => ({
        audio: document.querySelectorAll("audio").length,
        videos: [...document.querySelectorAll("video")].map((video) => ({
          muted: video.muted && video.hasAttribute("muted"),
          inline: video.hasAttribute("playsinline"),
          loop: video.hasAttribute("loop"),
          controllable:
            video.hasAttribute("controls") ||
            document.querySelector("[data-art-media-control]") !== null,
        })),
      })),
    );
  }

  expect(
    media.map((snapshot) => snapshot.audio),
    "there is no <audio> element anywhere in the journey",
  ).toEqual(SCENE_ORDER_FROM_BRIEF.map(() => 0));

  const videos = media.flatMap((snapshot) => snapshot.videos);
  for (const video of videos) {
    expect(video.muted, "a loop video is muted").toBe(true);
    expect(video.inline, "a loop video plays inline").toBe(true);
    expect(video.controllable, "a loop video is pausable").toBe(true);
  }

  test.info().annotations.push({
    type: "coverage",
    description:
      `${videos.length} loop video(s) exercised. The W04 seed's art media are all images, so the ` +
      "muted/inline/pausable invariant is asserted but not demonstrated by the launch content.",
  });
});

/* ================================================================================== axe */

/**
 * An axe sweep across the journey.
 *
 * `@axe-core/playwright` is not a dependency of this repo and must not be installed for a test, and
 * pulling axe from a CDN is out of the question (tests do not reach the network). `axe-core` itself
 * IS already present in `node_modules` — Lighthouse depends on it — so the engine is injected from
 * that local file. If it is ever absent the test skips loudly rather than silently passing.
 *
 * `color-contrast` is DISABLED on purpose. Every scene here paints its text over a live WebGL
 * shader, and axe (like Lighthouse) computes contrast from CSS background colours only: it cannot
 * see a canvas, so it either skips those nodes or compares against the wrong ground. Leaving the
 * rule on would produce a green result that means nothing. AA contrast over live shaders is the
 * `[manual]` box documented at the foot of this file.
 */
function readAxeSource(): string | null {
  // The spec file lives at <repo>/tests/e2e, so the workspace root is two levels up. Resolved
  // from this file rather than from the working directory, which the runner does not promise.
  const candidates = [
    join(__dirname, "..", "..", "node_modules", "axe-core", "axe.min.js"),
    join(process.cwd(), "node_modules", "axe-core", "axe.min.js"),
  ];
  for (const candidate of candidates) {
    try {
      return readFileSync(candidate, "utf8");
    } catch {
      // try the next candidate
    }
  }
  return null;
}

type AxeViolation = { id: string; impact: string | null; help: string; targets: string[] };

test("axe reports no WCAG A/AA violations across the journey", async ({ page }) => {
  const axeSource = readAxeSource();
  test.skip(
    axeSource === null,
    "axe-core is not present in node_modules; install nothing for this — the structural " +
      "accessibility properties are asserted by the other tests in this file.",
  );

  await openJourney(page);

  const findings: { scene: string; violations: AxeViolation[] }[] = [];
  for (const sceneId of SCENE_ORDER_FROM_BRIEF) {
    await scrollIntoScene(page, sceneId, 0.6);
    await page.addScriptTag({ content: axeSource! });
    const violations = await page.evaluate(async () => {
      const axe = (window as unknown as { axe: { run: (context: Document, options: unknown) => Promise<{ violations: { id: string; impact: string | null; help: string; nodes: { target: unknown[] }[] }[] }> } }).axe;
      const result = await axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
        rules: { "color-contrast": { enabled: false } },
        resultTypes: ["violations"],
      });
      return result.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        targets: violation.nodes.slice(0, 4).map((node) => node.target.join(" ")),
      }));
    });
    if (violations.length > 0) findings.push({ scene: sceneId, violations });
  }

  expect(
    findings,
    `axe violations (color-contrast excluded — see the manual procedure): ${JSON.stringify(findings, null, 2)}`,
  ).toEqual([]);

  test.info().annotations.push({
    type: "note",
    description:
      "axe-core injected from the local node_modules copy (no network). Rule set: wcag2a, wcag2aa, " +
      "wcag21a, wcag21aa, with color-contrast disabled because every scene's text sits over a live " +
      "WebGL canvas that axe cannot sample. See the [manual] contrast procedure in this file.",
  });
});

/* ===================================================================== [manual] procedures */

/**
 * ## `[manual]` — WCAG AA text contrast over live shaders (brief §16, ticket 15)
 *
 * NOT automated, and deliberately so. axe and Lighthouse both derive contrast from CSS background
 * colours; a `<canvas>` is transparent to them, so text over any of the seven background modes is
 * either skipped outright or measured against the page's base colour instead of the pixels the
 * reader actually sees. A green automated contrast result over these scenes would be false comfort,
 * so this file asserts nothing about it.
 *
 * ### Procedure
 *
 * Run the DEV server (`npm run dev`) so the mock imagery paints — a production build substitutes
 * branded placeholders and the worst-case grounds are not the real ones. Repeat at 1440x900 and
 * 375x812.
 *
 * For each row below: scroll to the named beat, pause, screenshot the viewport, then sample with a
 * contrast checker — foreground = the text pixel; background = the median of the shader pixels
 * *immediately behind that glyph*, not the page's CSS colour. Body text and labels need **4.5:1**;
 * text at or above 24px (or 19px bold) needs **3:1**.
 *
 * | # | scene / background | worst-case frame to sample | text to sample |
 * | --- | --- | --- | --- |
 * | 1 | thesis / OffWhiteGlow | the glow at its brightest, at the lower edge of the frame | the active hero message, and the small English lens label (smallest text on the page) |
 * | 2 | thesis / OffWhiteGlow | the moment the argument block is fully revealed | the four argument statements, which sit lowest and closest to the glow |
 * | 3 | menu / GreenGrid | the deck fully fanned over the grid lattice | card name, maker, category, and the rationale line |
 * | 4 | gridStatement / GreenGrid | statement fully revealed on the dark forest green | the centred statement |
 * | 5 | pixelA / mosaic | mid-transition, ~50% replaced — the highest-variance ground on the page | any statement text still held over the mosaic |
 * | 6 | films / WavyDots | a frame where a bright dot band crosses the left text column | view label, film title, director/year meta, rationale, and the poster credit line |
 * | 7 | pixelB / mosaic | mid-transition, through the orange/purple energy beat | any film text still on screen during the fade |
 * | 8 | tracks / MonochromeMesh | the mesh at its lightest (its controls run up to #E4E4E6) | track title, artist, group label, and the arrow-control glyphs |
 * | 9 | artPieces / MonochromeMesh "reading" variant | the lightest reading frame | index, category, creator/year, rationale, and the media credit |
 * | 10 | footer / FooterLight | the beam at full intensity, crossing the closing block | the closing statement, the disabled CTA text, and the five metadata slots |
 *
 * Also sample the persistent header mark in both its light and dark variants, at the scene where
 * each variant is active.
 *
 * ### Evidence to attach to the PR
 *
 * Per row: the screenshot, the sampled foreground/background hex pair, and the computed ratio.
 * Any row below its threshold is a defect against brief §16 — record it with the scene, the frame,
 * and the measured ratio.
 *
 * ## `[manual]` — no flashing or strobing (brief §16)
 *
 * Also not automatable here: the shaders' luminance over time is a GPU property with no DOM signal.
 * Procedure: record the full journey at each viewport, then step through the two pixel transitions
 * and the footer light frame by frame, confirming no more than three luminance reversals per second
 * over any 25% area of the viewport.
 */
export {};
