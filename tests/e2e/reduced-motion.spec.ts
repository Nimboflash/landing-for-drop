import { expect, test as base, type Page } from "@playwright/test";

/**
 * The reduced-motion journey — page seam (BUILD-GUIDE seam 3; ticket 15, third acceptance box;
 * brief §16 "Respect `prefers-reduced-motion` across every scene" and "Reduced motion must not
 * remove content or make the page unusable").
 *
 * Every test in this file runs with `prefers-reduced-motion: reduce` in force from before the
 * first navigation, because the loader picks its path once, at mount (brief §7.1).
 *
 * ## What this file claims, and what it deliberately does not
 *
 * The brief's reduced-motion contract is a *substitution*, never a subtraction. So the claims here
 * are about presentation choices the scenes publish as attributes, and about content still being
 * reachable and readable — never about how anything looks while it changes:
 *
 * | brief | assertable here | `[manual]` |
 * | --- | --- | --- |
 * | §7.1 static logo, then a simple O-shaped crossfade | the loader reports the static path and still hands over | that the crossfade reads as an O |
 * | §7.3 menu shows fronts, no 3D flip | every card presents `front` at every point of the deck's run | — |
 * | §7.6 films crossfade | all three films are reachable, one at a time | that the swap is a crossfade rather than a cut |
 * | §7.8 coverflow kept, stepped by a non-animated crossfade, all four inputs | the field still spans both sides of the active case, motion reports `static`, and scroll / buttons / keyboard / pointer-drag each still step it | that the step reads as a crossfade |
 * | §7.10 static gradient ribbon, simple outline reveal | the footer reports `static` and the shared canvas reports reduced motion | the ribbon's look |
 * | §16 no content lost | the whole W04 inventory is readable across one reduced-motion pass | — |
 *
 * Nothing below reads a computed style, an inline transform or opacity, a GSAP internal, or a
 * canvas pixel. "Readable" means: attached, carrying its text, and not inside `[inert]` or
 * `[aria-hidden="true"]` — the DOM observable-state contract, not a visibility heuristic
 * (Playwright's is wrong for `opacity: 0` and back-facing 3D elements anyway).
 *
 * Scroll positions are **inputs only**. No test asserts that a scene or an index is at a
 * particular fraction of the page: scroll budgets are tunable by design, so such an expectation
 * would just re-derive the implementation's config.
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
 * W04 seed — `handoff/04-mock-content/src/content/lenses/beautiful-imperfection.mock.json`,
 * transcribed. Expected values come from the seed, never from the module the page renders from.
 */
const LENS_TITLE_FA = "زیبایی در کامل نبودن";

const HERO_MESSAGES_FA = [
  "زیبایی از «نقص» نمی‌آید.",
  "اول مهارت و دوام؛ بعد تفاوت.",
  "دقت در کار؛ جا برای ردِ دست و رفتار واقعیِ ماده.",
] as const;

/** Thesis · tension · balance · not-this — the four statements of the lens's argument. */
const ARGUMENT_FA = [
  "زیبایی از «نقص» نمی‌آید؛ از مهارتی می‌آید که تفاوت‌های کوچکِ دست، ماده و زمان را پاک نمی‌کند.",
  "کیفیت باید هر بار قابل‌اعتماد باشد؛ نتیجهٔ دست‌ساز لازم نیست هر بار عیناً تکرار شود.",
  "دقت در کار؛ جا برای ردِ دست و رفتار واقعیِ ماده.",
  "این یک نسخهٔ آماده از کلیشهٔ وابی‌سابی نیست و بی‌دقتی را زیبا جا نمی‌زند؛ اول مهارت و دوام، بعد تفاوت.",
] as const;

const MENU_NAMES_FA = ["تارت میوهٔ هفتگی", "جعبهٔ موچی بایت"] as const;
const GRID_STATEMENT_FA = "جایی با یک نگاه مشخص.";
const FILM_TITLES = ["SHOWING UP", "PERFECT DAYS", "PATERSON"] as const;
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
] as const;
const ART_TITLES = [
  "BRION MEMORIAL",
  "UNTITLED (S.270)",
  "UNTITLED, FROM ILLUMINANCE",
  "THE PRATFALL EFFECT",
] as const;
const FOOTER_STATEMENT_FA = "جایی با یک نگاه مشخص.";

/**
 * Brief §7.10, "Footer content": "Bottom metadata slots: Instagram, location, contact, copyright,
 * and legal." Five slots, all disabled until final destinations exist.
 */
const FOOTER_SLOT_COUNT = 5;

/** Brief §7.1: "Cap the loader at 4 seconds." Plus room for a cold start and the navigation. */
const LOADER_SETTLE_TIMEOUT_MS = 15_000;

/** Samples per walk of the page. Fine enough that the shortest budgeted scene still lands one. */
const WALK_SAMPLES = 64;

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
      expect(errors, "the reduced-motion journey must produce no console errors").toEqual([]);
    },
    { auto: true },
  ],
});

/**
 * The whole file runs reduced. Set on the context rather than per test, so the preference is
 * already in force for the very first client render.
 */
test.use({ contextOptions: { reducedMotion: "reduce" } });

test.describe.configure({ timeout: 150_000 });

/* -------------------------------------------------------------------------------- helpers */

/** Two animation frames: one for the scroll to be observed, one for the render it causes. */
async function settle(page: Page): Promise<void> {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }),
  );
}

/**
 * The loader is time-based (brief §7.1), so every test waits for it to hand over before reading
 * the journey. `data-drop-loader` on the document element is the loader's own published marker.
 */
async function waitPastLoader(page: Page): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.dropLoader), {
      timeout: LOADER_SETTLE_TIMEOUT_MS,
      message: "the loader never reported itself complete under reduced motion",
    })
    .toBe("complete");
  await expect(page.locator("[data-loader-overlay]")).toHaveCount(0);
}

async function openJourney(page: Page, route = "/"): Promise<void> {
  const response = await page.goto(route);
  expect(response?.status(), `${route} must be served`).toBe(200);
  await waitPastLoader(page);
}

/** Put the document at a fraction of its scrollable range. An input, never an expectation. */
async function scrollToRatio(page: Page, ratio: number): Promise<void> {
  await page.evaluate((value) => {
    const range = document.documentElement.scrollHeight - window.innerHeight;
    window.scrollTo({ top: range * value, behavior: "instant" as ScrollBehavior });
  }, ratio);
  await settle(page);
}

/**
 * Scroll into a scene's own section, by that section's live geometry — never by a fraction of the
 * whole page, which would bake a budget into the test.
 */
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

/**
 * The text of every element matching `selector` that a reader can actually reach right now:
 * attached, non-empty, and not inside `[inert]` or `[aria-hidden="true"]`.
 *
 * This is the DOM observable-state contract, not a visibility guess — the page hides inactive
 * content with `inert` + `aria-hidden` on purpose, and never with opacity alone for anything
 * meaning-bearing.
 */
async function readableTexts(page: Page, selector: string): Promise<string[]> {
  return page.evaluate((css) => {
    const hidden = (element: Element): boolean =>
      element.closest("[inert]") !== null || element.closest('[aria-hidden="true"]') !== null;
    return [...document.querySelectorAll(css)]
      .filter((element) => !hidden(element))
      .map((element) => (element.textContent ?? "").replace(/\s+/g, " ").trim())
      .filter((text) => text !== "");
  }, selector);
}

/** Attribute values across a set of elements, read in one round-trip. */
async function attributes(page: Page, selector: string, name: string): Promise<(string | null)[]> {
  return page.evaluate(
    ({ css, attribute }) =>
      [...document.querySelectorAll(css)].map((element) => element.getAttribute(attribute)),
    { css: selector, attribute: name },
  );
}

/** Section ids in the order they first reported themselves the sole active scene. */
async function walkJourney(page: Page, reverse = false, samples = WALK_SAMPLES): Promise<string[]> {
  const order: string[] = [];
  for (let step = 0; step <= samples; step += 1) {
    await scrollToRatio(page, reverse ? 1 - step / samples : step / samples);
    const active = await page.evaluate(() =>
      [...document.querySelectorAll('[data-scene][data-active="true"]')].map((section) =>
        section.getAttribute("data-scene"),
      ),
    );
    if (active.length === 1 && active[0] !== null && order[order.length - 1] !== active[0]) {
      order.push(active[0]);
    }
  }
  return order;
}

/**
 * Sweep a scene end to end, collecting the union of everything `collect` reports at each sample.
 * The scene's own geometry drives the sweep, so no budget value is ever written down.
 */
async function sweepScene<T>(
  page: Page,
  sceneId: SceneId,
  samples: number,
  collect: () => Promise<readonly T[]>,
): Promise<T[]> {
  const seen: T[] = [];
  for (let step = 0; step <= samples; step += 1) {
    await scrollIntoScene(page, sceneId, step / samples);
    for (const value of await collect()) {
      if (!seen.includes(value)) seen.push(value);
    }
  }
  return seen;
}

/** The carousel's published active index. */
async function trackIndex(page: Page): Promise<number> {
  const raw = await page.locator("[data-tracks-carousel]").getAttribute("data-track-index");
  return Number(raw);
}

/* ============================================================================ the loader */

/**
 * Brief §7.1: "Reduced motion: static logo for 500-700ms, then a simple O-shaped crossfade."
 *
 * The loader unmounts when it finishes, so what is assertable afterwards is the marker it leaves
 * on the document element: *which path ran*, and that it completed. That the crossfade is
 * O-shaped is `[manual]` — it is a mask, and masks are pixels.
 */
test("the loader takes the static path and still hands the page over", async ({ page }) => {
  await page.goto("/");
  await waitPastLoader(page);

  const path = await page.evaluate(() => ({
    mode: document.documentElement.dataset.dropLoaderMode,
    sequence: document.documentElement.dataset.dropLoaderSequence,
  }));
  expect(path.mode, "reduced motion must take the loader's static path, not the material one").toBe(
    "static",
  );
  expect(path.sequence).toBe("static");

  // Handed over: the lens is there and the shell agrees that reduced motion is in force.
  await expect(page.locator("[data-lens-title]")).toHaveText(LENS_TITLE_FA);
  await expect(page.locator("[data-reduced-motion]").first()).toHaveAttribute(
    "data-reduced-motion",
    "true",
  );
});

/* ================================================================ the journey, end to end */

test("every scene is reachable with reduced motion, forward and in full reverse", async ({
  page,
}) => {
  await openJourney(page);

  const forward = await walkJourney(page);
  expect(forward, "every scene section is reached, in brief §6 order").toEqual([
    ...SCENE_ORDER_FROM_BRIEF,
  ]);

  const backward = await walkJourney(page, true);
  expect(backward, "every scene section is reached again on the way back").toEqual(
    [...SCENE_ORDER_FROM_BRIEF].reverse(),
  );

  // Reduced motion must not strand the reader anywhere: the page still runs to its end.
  await page.evaluate(() =>
    window.scrollTo({ top: 10_000_000, behavior: "instant" as ScrollBehavior }),
  );
  await settle(page);
  const end = await page.evaluate(() => ({
    scrollY: Math.round(window.scrollY),
    maxScroll: Math.round(document.documentElement.scrollHeight - window.innerHeight),
    active: [...document.querySelectorAll('[data-scene][data-active="true"]')].map((s) =>
      s.getAttribute("data-scene"),
    ),
  }));
  expect(end.maxScroll).toBeGreaterThan(0);
  expect(Math.abs(end.scrollY - end.maxScroll)).toBeLessThanOrEqual(2);
  expect(end.active).toEqual(["footer"]);
});

/**
 * The headline claim of brief §16: **reduced motion must not remove content**. One pass over the
 * assembled page, collecting the entire W04 inventory as it becomes readable — the counts and the
 * strings both come from the seed above.
 */
test("no content is lost: the whole W04 inventory is readable across one reduced-motion pass", async ({
  page,
}) => {
  await openJourney(page);

  // Thesis: identity, all three hero messages, and the four statements of the argument.
  await scrollIntoScene(page, "thesis", 0.9);
  expect(await readableTexts(page, "[data-lens-title]")).toEqual([LENS_TITLE_FA]);
  expect(
    await readableTexts(page, "[data-hero-message]"),
    "all three hero messages stay readable",
  ).toEqual([...HERO_MESSAGES_FA]);
  expect(
    await readableTexts(
      page,
      "[data-lens-thesis], [data-lens-tension], [data-lens-balance], [data-lens-not-this]",
    ),
  ).toEqual([...ARGUMENT_FA]);

  // Menu: both items.
  await scrollIntoScene(page, "menu", 0.9);
  expect(await readableTexts(page, "[data-menu-name]")).toEqual([...MENU_NAMES_FA]);
  expect(await readableTexts(page, "[data-menu-rationale]")).toHaveLength(MENU_NAMES_FA.length);

  // The single centred statement.
  await scrollIntoScene(page, "gridStatement", 0.6);
  expect(await readableTexts(page, "[data-statement-line='fa']")).toEqual([GRID_STATEMENT_FA]);

  // Films: one at a time (brief §7.6), so the scene has to be swept to read all three.
  const films = await sweepScene(page, "films", 24, () =>
    readableTexts(page, "[data-film][data-active='true'] [data-film-title]"),
  );
  expect(films, "all three films become readable").toEqual([...FILM_TITLES]);

  // Tracks: the caption belongs to the active case, so the carousel has to be stepped.
  const tracks = await sweepScene(page, "tracks", 44, () =>
    readableTexts(page, "[data-track][data-active='true'] [data-track-title]"),
  );
  expect(tracks, "all eleven tracks become readable").toEqual([...TRACK_TITLES]);

  // Art pieces: editorial rows, all four readable together.
  await scrollIntoScene(page, "artPieces", 0.95);
  expect(await readableTexts(page, "[data-art-title]")).toEqual([...ART_TITLES]);

  // Footer: the closing statement and every metadata slot.
  await scrollIntoScene(page, "footer", 1);
  expect(await readableTexts(page, "[data-footer-statement]")).toEqual([FOOTER_STATEMENT_FA]);
  expect(await readableTexts(page, "[data-footer-link]")).toHaveLength(FOOTER_SLOT_COUNT);
  expect(await readableTexts(page, "[data-footer-cta]")).toHaveLength(1);
});

/* ========================================================= the per-scene substitutions */

/**
 * Brief §7.3 reduced motion: the deck presents card fronts without the 3D flip. So the substitution
 * is assertable exactly: at NO point in the deck's run does a card present its back.
 */
test("the menu deck presents fronts for the whole of its run and never flips", async ({ page }) => {
  await openJourney(page);

  await expect(page.locator("[data-menu-items]")).toHaveAttribute("data-deck-motion", "static");

  const facesSeen = await sweepScene(page, "menu", 20, async () => {
    const faces = await attributes(page, "[data-menu-item]", "data-card-face");
    return faces.map((face) => face ?? "missing");
  });
  expect(facesSeen, "a reduced-motion deck only ever presents fronts").toEqual(["front"]);

  // The reducer still runs its choreography underneath — the deck reaches its dealt state — it is
  // only the *presented face* that never turns.
  await scrollIntoScene(page, "menu", 0.95);
  expect(await attributes(page, "[data-menu-item]", "data-flipped")).toEqual(
    MENU_NAMES_FA.map(() => "true"),
  );
});

/**
 * Brief §7.4/§7.5: the grid statement is one centred statement, and reduced motion swaps its
 * choreography for a static presentation without touching the statement itself.
 */
test("the grid statement keeps its text and reports static presentation", async ({ page }) => {
  await openJourney(page);
  await scrollIntoScene(page, "gridStatement", 0.6);

  const statement = page.locator("[data-grid-statement]");
  await expect(statement).toHaveAttribute("data-statement-motion", "static");
  expect(await readableTexts(page, "[data-statement-line='fa']")).toEqual([GRID_STATEMENT_FA]);
});

/**
 * Brief §7.8 and ticket 12: reduced motion keeps the coverflow presentation and every capability —
 * only the travel between positions stops. Two halves to that claim, both assertable:
 *
 * 1. the field is still a coverflow field: cases on BOTH sides of the active one are painted
 *    positions (`data-in-field`), each with its own signed `data-offset`;
 * 2. the carousel reports `static` motion rather than dropping to a single visible item.
 */
test("the tracks carousel keeps its coverflow field under reduced motion", async ({ page }) => {
  await openJourney(page);
  await scrollIntoScene(page, "tracks", 0.5);

  const carousel = page.locator("[data-tracks-carousel]");
  await expect(carousel).toHaveAttribute("data-carousel-motion", "static");
  await expect(carousel).toHaveAttribute("data-track-count", String(TRACK_TITLES.length));

  // Park the active case away from both ends so the field can span it on both sides. Halfway
  // through the scene is an input, not an expectation — it is only asserted that the index that
  // results is an interior one.
  await expect
    .poll(() => trackIndex(page), { message: "the middle of the tracks scene is not an end case" })
    .toBeGreaterThan(0);
  const parked = await trackIndex(page);
  expect(parked).toBeLessThan(TRACK_TITLES.length - 1);

  const field = await page.evaluate(() => ({
    slots: Number(
      document.querySelector("[data-tracks-carousel]")?.getAttribute("data-carousel-slots"),
    ),
    offsets: [...document.querySelectorAll('[data-track][data-in-field="true"]')]
      .map((track) => Number(track.getAttribute("data-offset")))
      .sort((a, b) => a - b),
    discs: document.querySelectorAll("[data-track-artwork]").length,
  }));

  // Brief §15 gives desktop five positions and mobile three, so the count is viewport-dependent
  // and is never written down here — what must hold is that it IS a field, on both sides.
  expect(field.slots, "the coverflow field survives reduced motion").toBeGreaterThanOrEqual(1);
  expect(field.offsets, "a case sits before the active one").toContain(-1);
  expect(field.offsets, "a case sits after the active one").toContain(1);
  expect(field.offsets, "the active case is in its own field").toContain(0);
  expect(field.discs, "every track still has its disc").toBe(TRACK_TITLES.length);
});

/**
 * Ticket 12 is explicit that reduced motion removes no capability: scroll, drag/swipe, buttons and
 * keyboard all still step the carousel (brief §7.8, §19 "Carousel supports scroll, drag/swipe,
 * buttons, and keyboard").
 *
 * Each input is exercised in isolation and asserted only as "the published index moved the way the
 * input asked" — never by how far, which is the drag threshold's business and viewport-dependent.
 */
test("all four carousel inputs still step the carousel under reduced motion", async ({ page }) => {
  await openJourney(page);

  /* --- 1. scroll: the scene's own scrub is an input source like any other --- */
  await scrollIntoScene(page, "tracks", 0.05);
  const early = await trackIndex(page);
  await scrollIntoScene(page, "tracks", 0.85);
  const late = await trackIndex(page);
  expect(late, "scrolling forward through the tracks scene advances the carousel").toBeGreaterThan(
    early,
  );

  /* --- 2. buttons --- */
  await scrollIntoScene(page, "tracks", 0.4);
  const beforeButtons = await trackIndex(page);
  await page.locator('[data-carousel-control="next"]').click();
  await expect.poll(() => trackIndex(page)).toBe(beforeButtons + 1);
  await page.locator('[data-carousel-control="prev"]').click();
  await expect.poll(() => trackIndex(page)).toBe(beforeButtons);

  /* --- 3. keyboard, from the carousel's roving tab stop --- */
  await page.locator('[data-track][data-active="true"] [data-track-case]').focus();
  await page.keyboard.press("ArrowRight");
  await expect.poll(() => trackIndex(page)).toBe(beforeButtons + 1);
  await page.keyboard.press("ArrowLeft");
  await expect.poll(() => trackIndex(page)).toBe(beforeButtons);

  /* --- 4. drag / swipe --- *
   * Dispatched as real `PointerEvent`s with `pointerType: "touch"` so the touch path is the one
   * exercised, not a mouse drag standing in for it. This is an input at the page seam — the same
   * events a finger produces — not a reach into the component.
   */
  const dragged = await page.evaluate(() => {
    const carousel = document.querySelector("[data-tracks-carousel]");
    if (!carousel) return false;
    const box = carousel.getBoundingClientRect();
    const y = box.top + box.height / 2;
    const startX = box.left + box.width / 2;
    const target = document.elementFromPoint(startX, y) ?? carousel;
    const fire = (type: string, x: number, buttons: number): void => {
      target.dispatchEvent(
        new PointerEvent(type, {
          bubbles: true,
          cancelable: true,
          composed: true,
          pointerId: 917,
          pointerType: "touch",
          isPrimary: true,
          clientX: x,
          clientY: y,
          button: 0,
          buttons,
        }),
      );
    };
    fire("pointerdown", startX, 1);
    for (let step = 1; step <= 12; step += 1) fire("pointermove", startX - step * 30, 1);
    fire("pointerup", startX - 360, 0);
    return true;
  });
  expect(dragged).toBe(true);
  // The field is composed physically left-to-right, so dragging leftward advances it.
  await expect
    .poll(() => trackIndex(page), { message: "a touch swipe still steps the carousel" })
    .toBeGreaterThan(beforeButtons);
});

/**
 * Brief §7.6: exactly one active film at a time, and reduced motion swaps the cinematic transition
 * for a crossfade. Whether the swap *reads* as a crossfade is `[manual]`; that all three films are
 * still reachable one at a time, forward and in reverse, is not.
 */
test("the films still arrive one at a time, and reverse back again", async ({ page }) => {
  await openJourney(page);

  const forward = await sweepScene(page, "films", 24, () =>
    readableTexts(page, "[data-film][data-active='true'] [data-film-title]"),
  );
  expect(forward).toEqual([...FILM_TITLES]);

  const backward: string[] = [];
  for (let step = 24; step >= 0; step -= 1) {
    await scrollIntoScene(page, "films", step / 24);
    const [title] = await readableTexts(
      page,
      "[data-film][data-active='true'] [data-film-title]",
    );
    if (title !== undefined && backward[backward.length - 1] !== title) backward.push(title);
  }
  expect(backward, "reverse scroll walks the films back").toEqual([...FILM_TITLES].reverse());

  // One at a time is a hard property, not a visual one: never two active films at once.
  const activeCounts = await sweepScene(page, "films", 12, async () => [
    (await attributes(page, "[data-film][data-active='true']", "data-index")).length,
  ]);
  expect(activeCounts).toEqual([1]);
});

/**
 * Brief §7.9: the Art Pieces rows are editorial reading. Reduced motion replaces the mask/parallax
 * reveal with a plain arrival — every row, its index, category, creator/year metadata and
 * rationale stay readable.
 */
test("every art piece row stays readable under reduced motion", async ({ page }) => {
  await openJourney(page);
  await scrollIntoScene(page, "artPieces", 0.95);

  expect(await readableTexts(page, "[data-art-title]")).toEqual([...ART_TITLES]);
  expect(await readableTexts(page, "[data-art-index]")).toHaveLength(ART_TITLES.length);
  expect(await readableTexts(page, "[data-art-category]")).toHaveLength(ART_TITLES.length);
  expect(await readableTexts(page, "[data-art-rationale]")).toHaveLength(ART_TITLES.length);
  expect(
    await attributes(page, "[data-art-piece]", "data-art-revealed"),
    "no row is left masked out under reduced motion",
  ).toEqual(ART_TITLES.map(() => "true"));
});

/**
 * Brief §7.10: "Reduced-motion mode uses a static blurred gradient ribbon and a simple outline
 * reveal." The ribbon is the shader's, so its *look* is `[manual]`; what the page publishes is
 * that the footer's own choreography is static and that the shared canvas knows it is reduced.
 */
test("the footer reveals statically and keeps every slot", async ({ page }) => {
  await openJourney(page);
  await scrollIntoScene(page, "footer", 1);

  const footer = page.locator("[data-footer]");
  await expect(footer).toHaveAttribute("data-motion", "static");
  await expect(footer).toHaveAttribute("data-reveal-percent", "100");
  await expect(page.locator("[data-background-canvas]")).toHaveAttribute(
    "data-reduced-motion",
    "true",
  );
  await expect(page.locator("[data-background-canvas]")).toHaveAttribute(
    "data-background-mode",
    "footerLight",
  );

  await expect(page.locator("[data-footer-statement]")).toHaveText(FOOTER_STATEMENT_FA);
  await expect(page.locator("[data-footer-link]")).toHaveCount(FOOTER_SLOT_COUNT);
  // Reduced motion is not an excuse to drop the disabled slots or turn them into live links.
  expect(await attributes(page, "[data-footer-link]", "data-enabled")).toEqual(
    Array.from({ length: FOOTER_SLOT_COUNT }, () => "false"),
  );
  await expect(page.locator("[data-footer-link] a")).toHaveCount(0);
});

/**
 * The shared canvas under reduced motion (brief §14: "static backgrounds with brief crossfades;
 * all content remains accessible"). Asserted as the canvas's own published state — never as
 * pixels, and never as a frame rate.
 */
test("the shared background reports reduced motion in every scene it serves", async ({ page }) => {
  await openJourney(page);

  const seen: string[] = [];
  for (const sceneId of SCENE_ORDER_FROM_BRIEF) {
    await scrollIntoScene(page, sceneId, 0.5);
    const canvas = await page.evaluate(() => {
      const root = document.querySelector("[data-background-canvas]");
      return {
        mode: root?.getAttribute("data-background-mode") ?? null,
        reduced: root?.getAttribute("data-reduced-motion") ?? null,
        hidden: root?.getAttribute("aria-hidden") ?? null,
      };
    });
    expect(canvas.reduced, `background canvas in "${sceneId}"`).toBe("true");
    expect(canvas.hidden, "the decorative canvas stays out of the accessibility tree").toBe("true");
    if (canvas.mode !== null && !seen.includes(canvas.mode)) seen.push(canvas.mode);
  }
  // The journey still moves through more than one background: reduced motion holds the shaders
  // still, it does not collapse the page to a single ground.
  expect(seen.length, "reduced motion keeps the per-scene backgrounds").toBeGreaterThan(1);
});
