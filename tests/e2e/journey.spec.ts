import { expect, test as base, type Page } from "@playwright/test";

/**
 * Whole-journey integrity and the route matrix — page seam (BUILD-GUIDE seam 3, ticket 15,
 * second acceptance box).
 *
 * `lens-page.spec.ts` already proves the *content* of the assembled page: the ten sections exist
 * in brief §6 order, the counts and strings come from the W04 seed, the header adapts, one
 * forward/reverse ratio walk is ordinally monotonic. This file does not repeat any of that. It
 * covers the things that only break once the whole thing is moving:
 *
 * - every scene *section* is actually reached — not just that the machine's scene id moves in
 *   the right order, but that each of the ten sections reports itself active, forward AND after a
 *   full reverse (the ticket's automatable proxy for stuck pins and dead scroll zones);
 * - the document really scrolls to its end;
 * - rapid scrolling (large jumps, fast repeated jumps, jumps taken while the loader is still on
 *   screen) never lands the page in a state that disagrees with where it stopped;
 * - resizing while pinned inside a scene: ScrollTriggers recalculate, and the scene stays
 *   reachable and the journey stays complete — desktop→mobile and mobile→desktop;
 * - the route matrix: `/`, direct `/lens/beautiful-imperfection`, refresh mid-page, and
 *   back-navigation, after which forward and reverse must produce *identical* state sequences and
 *   the dev-only ScrollTrigger count must not have grown.
 *
 * ## `[manual]` — the part this file deliberately does not claim
 *
 * The general "no stuck pin, no dead scroll zone" judgment of brief §19 ("General") is a
 * **`[manual]`** acceptance box and is NOT automated here. A scene can be perfectly reachable —
 * every assertion below green — while a long shader-only scrub range in the middle of it reads as
 * dead air, or while a pin releases a beat late. Playwright cannot see any of that: nothing in the
 * DOM changes across those ranges, and WebGL pixels are never asserted. What is automated is the
 * strictly weaker, mechanical proxy the ticket words: *the document scrolls to its end, and every
 * scene section is reachable forward and after a full reverse.* Passing that says the journey has
 * no unreachable region; it says nothing about whether the journey feels right. The manual
 * procedure is: at each QA viewport, scroll the page end to end by wheel and by touch at a natural
 * pace, then again in reverse, watching for a scene that holds after its content has finished, a
 * range where nothing on screen responds to scroll, or a pin that jumps rather than releases.
 *
 * ## Rules this file obeys
 *
 * - **Attributes and text only** — `data-scene`, `data-active`, `aria-current`,
 *   `data-active-scene`, `data-background-mode`, `data-header-variant`, `data-contrast`, and the
 *   loader's `data-drop-loader` marker on the document element. Never a computed style, never an
 *   inline transform or opacity (Playwright's visibility heuristic is wrong for them anyway),
 *   never a GSAP internal, never a canvas pixel.
 * - **Ordinal / structural, never absolute.** Scroll budgets are tunable by design, so no test
 *   here asserts that a scene is active at a particular fraction of the page. Scroll positions are
 *   only ever used as *inputs*; the expectations are orderings, set membership, and equality
 *   between two observed sequences.
 * - **Expected values come from the brief**, written out below — never recomputed the way the page
 *   computes them.
 * - **Zero console errors** is a standing assertion on every test in the file (auto fixture).
 */

/* ------------------------------------------------------- expectations, from the source docs */

/** Brief §6, "Master Experience Sequence" — the order is itself an acceptance criterion. */
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

/** Brief §21, "Routes": both entry points render the same lens journey. */
const LENS_ROUTES = ["/", "/lens/beautiful-imperfection"] as const;

/** Brief §21, "Viewports". The two extremes of the matrix, used for the resize rows. */
const QA_DESKTOP = { width: 1440, height: 900 } as const;
const QA_MOBILE = { width: 375, height: 812 } as const;

/**
 * Scenes to be pinned inside when the viewport changes under the user. One from each of the three
 * background families the page runs through — off-white glow, wavy dots, monochrome mesh — so a
 * refresh failure that only affects one family cannot hide.
 */
const RESIZE_PROBE_SCENES: readonly SceneId[] = ["menu", "films", "tracks"];

/**
 * Samples per walk of the page. Fine enough that the shortest budgeted scene (brief §6 gives the
 * pixel transitions 140-180vh out of a page in the low thousands) still lands at least one sample
 * inside its own window at every QA viewport. Not tuned to any particular budget value — raising
 * it only makes the walk finer.
 */
const WALK_SAMPLES = 64;

/**
 * Samples for the secondary walks — the two either side of a route round trip, and the two that
 * confirm a refreshed page is still whole. Coarser than {@link WALK_SAMPLES} because coverage of
 * every scene is not the primary claim of those tests, and multiple walks of one page are by far
 * the most expensive thing in the file.
 */
const SECONDARY_WALK_SAMPLES = 48;

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
      expect(errors, "the journey must produce no console errors").toEqual([]);
    },
    { auto: true },
  ],
});

test.describe.configure({ timeout: 180_000 });

/* -------------------------------------------------------------------------------- helpers */

/**
 * Everything this file is allowed to observe, read in one round-trip: the shell's reducer-driven
 * attributes, which sections claim to be active, and where the document is scrolled to.
 *
 * `activeSections` is the interesting one. The shell publishes a single `data-active-scene`, but
 * each of the ten `<section data-scene>` elements independently carries `data-active`. Reading the
 * sections rather than the shell is what makes the stuck-pin proxy meaningful: it is the section
 * that has to be reached, and a page where the machine's id advances while a section never flips
 * would fail here and pass a shell-only assertion.
 */
type JourneySnapshot = {
  activeScene: string | null;
  activeSections: string[];
  ariaCurrentSections: string[];
  backgroundMode: string | null;
  headerVariant: string | null;
  contrast: string | null;
  scrollY: number;
  maxScroll: number;
};

async function journeySnapshot(page: Page): Promise<JourneySnapshot> {
  return page.evaluate(() => {
    const shell = document.querySelector("[data-active-scene]");
    const header = document.querySelector("[data-header-variant]");
    const named = (selector: string) =>
      [...document.querySelectorAll(selector)].map((element) => element.getAttribute("data-scene") ?? "");
    return {
      activeScene: shell?.getAttribute("data-active-scene") ?? null,
      activeSections: named('[data-scene][data-active="true"]'),
      ariaCurrentSections: named('[data-scene][aria-current="true"]'),
      backgroundMode: shell?.getAttribute("data-background-mode") ?? null,
      headerVariant: header?.getAttribute("data-header-variant") ?? null,
      contrast: shell?.getAttribute("data-contrast") ?? null,
      scrollY: Math.round(window.scrollY),
      maxScroll: Math.round(document.documentElement.scrollHeight - window.innerHeight),
    };
  });
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

/** Put the document at a fraction of its scrollable range. An input, never an expectation. */
async function jumpToRatio(page: Page, ratio: number): Promise<void> {
  await page.evaluate((value) => {
    const range = document.documentElement.scrollHeight - window.innerHeight;
    window.scrollTo({ top: range * value, behavior: "instant" as ScrollBehavior });
  }, ratio);
}

async function scrollToRatio(page: Page, ratio: number): Promise<void> {
  await jumpToRatio(page, ratio);
  await settle(page);
}

/**
 * Arrive at an absolute scroll offset the slow way, from the top. Used to answer "what does the
 * page say when you *scroll* here?", so it can be compared with what the page says when it *lands*
 * here — after a rapid jump, a refresh, or a deep link. The comparison needs no knowledge of which
 * scene belongs at that offset, which is what keeps it ordinal.
 */
async function calmScrollToY(page: Page, y: number, steps = 20): Promise<void> {
  await scrollToRatio(page, 0);
  for (let step = 1; step <= steps; step += 1) {
    await page.evaluate((top) => window.scrollTo({ top, behavior: "instant" as ScrollBehavior }), (y * step) / steps);
    await settle(page);
  }
}

/**
 * Scroll into a scene's own section, by that section's live geometry rather than by a fraction of
 * the page. This is what makes the resize tests real: if ScrollTriggers had not recalculated after
 * the viewport changed, their cached start/end would still describe the old layout and the section
 * would report the wrong scene from its own new position.
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
 * The loader is time-based (brief §7.1), so every test waits for it to hand over before it starts
 * reading the journey. `data-drop-loader` on the document element is the loader's own published
 * marker — an attribute, like everything else this file reads.
 */
async function waitPastLoader(page: Page): Promise<void> {
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.dropLoader), {
      timeout: LOADER_SETTLE_TIMEOUT_MS,
      message: "the loader never reported itself complete",
    })
    .toBe("complete");
  await expect(page.locator("[data-loader-overlay]")).toHaveCount(0);
}

/** Open a lens route and wait for the loader to let go. */
async function openJourney(page: Page, route: string): Promise<void> {
  const response = await page.goto(route);
  expect(response?.status(), `${route} must be served`).toBe(200);
  await waitPastLoader(page);
}

type Walk = {
  /** Section ids in the order they first reported themselves active. */
  order: string[];
  /** The active-section id at every sample, in order — the sequence two runs are compared on. */
  sequence: string[];
  /** Samples where the section-level and shell-level state disagreed, or were not unique. */
  inconsistencies: string[];
};

/**
 * Walk the page from one end to the other, recording which section is active at each sample.
 *
 * Also checks a structural invariant at every sample, which costs nothing because the snapshot is
 * already being read: *exactly one* section is active, `aria-current` marks that same one, and the
 * shell's `data-active-scene` agrees with it. A journey that briefly shows two active scenes, or
 * none, is a broken state even if the ends of the walk look right.
 */
async function walkJourney(page: Page, reverse = false, samples = WALK_SAMPLES): Promise<Walk> {
  const order: string[] = [];
  const sequence: string[] = [];
  const inconsistencies: string[] = [];

  for (let step = 0; step <= samples; step += 1) {
    const ratio = reverse ? 1 - step / samples : step / samples;
    await scrollToRatio(page, ratio);
    const snapshot = await journeySnapshot(page);

    const active = snapshot.activeSections[0] ?? null;
    if (
      snapshot.activeSections.length !== 1 ||
      snapshot.ariaCurrentSections.length !== 1 ||
      snapshot.ariaCurrentSections[0] !== active ||
      snapshot.activeScene !== active
    ) {
      inconsistencies.push(
        `sample ${step}: sections=[${snapshot.activeSections.join(",")}] ` +
          `aria-current=[${snapshot.ariaCurrentSections.join(",")}] shell=${snapshot.activeScene}`,
      );
    }

    if (active !== null) {
      sequence.push(active);
      if (order[order.length - 1] !== active) order.push(active);
    }
  }

  return { order, sequence, inconsistencies };
}

/**
 * Assert a scene is reachable from its own section, retrying while the page settles. Used after a
 * viewport change, where ScrollTrigger's refresh is debounced and the first attempt can land
 * against stale geometry.
 */
async function expectSceneReachable(page: Page, sceneId: SceneId): Promise<void> {
  await expect
    .poll(
      async () => {
        await scrollIntoScene(page, sceneId);
        return (await journeySnapshot(page)).activeSections;
      },
      {
        timeout: 20_000,
        message: `scene "${sceneId}" never became the sole active section from inside its own section`,
      },
    )
    .toEqual([sceneId]);
}

/** Every one of the ten sections is reachable from its own position, and only it is active. */
async function expectEverySceneReachable(page: Page): Promise<void> {
  for (const sceneId of SCENE_ORDER_FROM_BRIEF) {
    await scrollIntoScene(page, sceneId);
    expect(
      (await journeySnapshot(page)).activeSections,
      `scene "${sceneId}" is not reachable from inside its own section`,
    ).toEqual([sceneId]);
  }
}

/**
 * The end of the document is really reachable — asked for far past the bottom, so a pin that
 * refused to release, or a scene whose spacer never resolved, shows up as a short page.
 */
async function expectDocumentScrollsToItsEnd(page: Page): Promise<void> {
  await page.evaluate(() => window.scrollTo({ top: 10_000_000, behavior: "instant" as ScrollBehavior }));
  await settle(page);
  const snapshot = await journeySnapshot(page);
  expect(snapshot.maxScroll, "the page must have a scrollable range").toBeGreaterThan(0);
  expect(
    Math.abs(snapshot.scrollY - snapshot.maxScroll),
    "the document must scroll all the way to its end",
  ).toBeLessThanOrEqual(2);
  expect(
    snapshot.activeSections,
    "the last scene of brief §6 must own the end of the document",
  ).toEqual(["footer"]);
}

type SceneDiagnosticsSnapshot = {
  scrollTriggerCount: number;
  sceneId: string;
  contentMode: string | undefined;
};

/**
 * The dev-build diagnostics object (BUILD-GUIDE's sanctioned escape hatch), or `null` when it has
 * been stripped — which is the correct state of a production bundle. Same shape `lens-page.spec.ts`
 * reads, so the leak check never reaches into GSAP internals.
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

/* ------------------------------------------------------- forward, reverse, end of document */

for (const route of LENS_ROUTES) {
  test(`${route} — forward scroll reaches every scene section in brief order, to the document's end`, async ({
    page,
  }) => {
    await openJourney(page, route);

    const forward = await walkJourney(page);
    expect(forward.inconsistencies, "exactly one scene section is active at a time").toEqual([]);

    // The stuck-pin / dead-zone proxy: not "the scene id moved in order" but "every one of the ten
    // sections was actually reached", and reached in the brief's sequence.
    expect(forward.order, "every scene section is reached, once, in brief §6 order").toEqual([
      ...SCENE_ORDER_FROM_BRIEF,
    ]);

    await expectDocumentScrollsToItsEnd(page);
  });

  test(`${route} — a full reverse scroll reaches every scene again and returns to the initial state`, async ({
    page,
  }) => {
    await openJourney(page, route);
    const initial = await journeySnapshot(page);
    expect(initial.activeSections).toEqual(["loader"]);
    expect(initial.scrollY).toBe(0);

    await walkJourney(page);

    const backward = await walkJourney(page, true);
    expect(backward.inconsistencies, "exactly one scene section is active at a time").toEqual([]);

    // Reversibility is an acceptance criterion everywhere (brief §9, §19): the journey back is the
    // journey out, mirrored — every section reached again, in the mirrored order.
    expect(backward.order, "every scene section is reached again on the way back").toEqual(
      [...SCENE_ORDER_FROM_BRIEF].reverse(),
    );

    const final = await journeySnapshot(page);
    expect(final.scrollY, "the page returns to the top").toBe(0);
    expect(final.activeSections).toEqual(["loader"]);
    expect(final.activeScene).toBe(initial.activeScene);
    expect(final.backgroundMode).toBe(initial.backgroundMode);
    expect(final.headerVariant).toBe(initial.headerVariant);
    expect(final.contrast).toBe(initial.contrast);
    // The document must be the same length it started: pin spacers that accumulated on every pass
    // would grow the page a little each time and would show up here before anywhere else.
    expect(
      Math.abs(final.maxScroll - initial.maxScroll),
      "a round trip must not change the length of the document",
    ).toBeLessThanOrEqual(2);
  });
}

/* --------------------------------------------------------------------------- rapid scroll */

test("rapid scrolling leaves the page in the state its final position calls for", async ({
  page,
}) => {
  await openJourney(page, "/");

  // Deliberately violent: large jumps end to end, taken back to back with no frame in between, so
  // the machine is asked to keep up with a position that has already moved on several times.
  const THRASH: readonly number[] = [1, 0, 0.83, 0.07, 0.55, 0.29];

  for (const landing of [0.18, 0.55, 0.87]) {
    await scrollToRatio(page, 0);
    for (let round = 0; round < 5; round += 1) {
      for (const ratio of THRASH) await jumpToRatio(page, ratio);
    }
    await jumpToRatio(page, landing);
    await settle(page);
    const afterRapid = await journeySnapshot(page);

    // The same position, arrived at calmly. Comparing the two is the whole assertion: it needs no
    // knowledge of which scene "should" be at that fraction of the page, so it stays ordinal and
    // survives any retuning of the scroll budgets.
    await calmScrollToY(page, afterRapid.scrollY);
    const afterCalm = await journeySnapshot(page);

    expect(afterRapid.activeSections, "one scene is active after rapid scrolling").toHaveLength(1);
    expect(
      afterRapid.activeSections,
      `rapid and calm scrolling to the same position must agree (landing ${landing})`,
    ).toEqual(afterCalm.activeSections);
    expect(afterRapid.activeScene).toBe(afterCalm.activeScene);
    expect(afterRapid.backgroundMode).toBe(afterCalm.backgroundMode);
    expect(afterRapid.headerVariant).toBe(afterCalm.headerVariant);
  }

  // Nothing was skipped *into a broken state*: after all that, every section is still reachable
  // from its own position and the document still runs to its end.
  await expectEverySceneReachable(page);
  await expectDocumentScrollsToItsEnd(page);
});

/**
 * The loader is an overlay over a live, scrollable page (brief §7.1: "Keep the DOM page mounted
 * beneath the loader"), so an impatient user can scroll during it. This test asserts only what is
 * uncontroversial — the machine ends up consistent with where the page actually stopped, nothing
 * errors, and the journey is still whole. It deliberately does NOT assert where the page lands:
 * that the page can be scrolled past the hero while the loader still covers the screen is an
 * observation for the ticket-15 report, not a behaviour to pin down here.
 */
test("scrolling while the loader is still on screen leaves a consistent, complete journey", async ({
  page,
}) => {
  await page.goto("/");
  for (let round = 0; round < 4; round += 1) {
    for (const ratio of [0.4, 0.05, 0.7, 0.2]) await jumpToRatio(page, ratio);
  }
  await waitPastLoader(page);
  await settle(page);

  const snapshot = await journeySnapshot(page);
  expect(snapshot.activeSections, "exactly one scene is active once the loader hands over").toHaveLength(1);
  expect(snapshot.activeScene).toBe(snapshot.activeSections[0]);
  expect(snapshot.ariaCurrentSections).toEqual(snapshot.activeSections);

  await expectEverySceneReachable(page);
  await expectDocumentScrollsToItsEnd(page);
  await scrollToRatio(page, 0);
  expect((await journeySnapshot(page)).activeSections).toEqual(["loader"]);
});

/* -------------------------------------------------------------------- resize mid-scene */

/**
 * Brief §21 lists "resize mid-scene" as a Motion row of the QA matrix, and §9 requires triggers to
 * "Recalculate after fonts and critical assets load" — the same recalculation a viewport change
 * demands. Both directions of the matrix's extremes are covered: 1440x900 ↔ 375x812.
 *
 * Note what is *not* asserted: that the same scene is still active at the same scroll offset. The
 * budgets are in viewport heights, so the document legitimately gets shorter on a narrow viewport
 * and a preserved absolute scroll offset is genuinely further through the journey. Pinning that
 * down would be asserting the implementation's config. What must hold is that the page is still
 * correct and usable: every scene, including the one that was pinned, is reachable from its own
 * section, and the whole journey still runs.
 */
for (const [name, from, to] of [
  ["desktop to mobile", QA_DESKTOP, QA_MOBILE],
  ["mobile to desktop", QA_MOBILE, QA_DESKTOP],
] as const) {
  test(`resizing ${name} while pinned inside a scene keeps the journey usable`, async ({ page }) => {
    await page.setViewportSize(from);
    await openJourney(page, "/");

    for (const sceneId of RESIZE_PROBE_SCENES) {
      await page.setViewportSize(from);
      await expectSceneReachable(page, sceneId);

      // Resize while the scene holds the viewport.
      await page.setViewportSize(to);
      await expectSceneReachable(page, sceneId);

      // …and back again, which is the case that catches a refresh that only ever runs one way.
      await page.setViewportSize(from);
      await expectSceneReachable(page, sceneId);
    }

    await page.setViewportSize(to);
    const forward = await walkJourney(page);
    expect(forward.inconsistencies).toEqual([]);
    expect(forward.order, "the whole journey survives the resize").toEqual([
      ...SCENE_ORDER_FROM_BRIEF,
    ]);
    await expectDocumentScrollsToItsEnd(page);
  });
}

/* ---------------------------------------------------------------------- the route matrix */

for (const route of LENS_ROUTES) {
  test(`${route} — refreshing mid-journey resumes consistently and the journey stays whole`, async ({
    page,
  }) => {
    await openJourney(page, route);
    await scrollIntoScene(page, "tracks");
    const before = await journeySnapshot(page);
    expect(before.activeSections).toEqual(["tracks"]);

    await page.reload();
    await waitPastLoader(page);
    await settle(page);

    const after = await journeySnapshot(page);
    expect(after.activeSections, "exactly one scene is active after a refresh").toHaveLength(1);
    expect(after.activeScene).toBe(after.activeSections[0]);
    expect(after.ariaCurrentSections).toEqual(after.activeSections);

    // Whether a *reload* restores the previous scroll offset is the browser's business, not the
    // page's — Chromium does, WebKit under Playwright does not — so it is read, never demanded.
    // Where it does restore, the strong claim applies: the machine settles against wherever the
    // page actually is, rather than reporting the first scene while the viewport shows the eighth.
    // Where it does not, the same mount-mid-page path is covered deterministically in every engine
    // by the deep-link test below.
    if (Math.abs(after.scrollY - before.scrollY) <= 2) {
      expect(after.activeSections, "the restored position resolves to the same scene").toEqual(
        before.activeSections,
      );
      expect(after.activeScene).toBe(before.activeScene);
      expect(after.backgroundMode).toBe(before.backgroundMode);
      expect(after.headerVariant).toBe(before.headerVariant);
    } else {
      expect(after.scrollY, "a reload that does not restore scroll starts at the top").toBe(0);
      expect(after.activeSections).toEqual(["loader"]);
      test.info().annotations.push({
        type: "note",
        description:
          "this engine does not restore the scroll offset across a reload, so the refresh resumed " +
          "at the top; the mount-mid-page path is asserted by the deep-link entry test instead",
      });
    }

    // Reachable in both directions from wherever the refresh landed, not just readable there.
    const backward = await walkJourney(page, true, SECONDARY_WALK_SAMPLES);
    expect(backward.order).toEqual([...SCENE_ORDER_FROM_BRIEF].reverse());
    const forward = await walkJourney(page, false, SECONDARY_WALK_SAMPLES);
    expect(forward.order).toEqual([...SCENE_ORDER_FROM_BRIEF]);
  });

  /**
   * Direct entry that starts the page mid-journey. Every scene section carries `id="scene-<id>"`,
   * so a fragment is the one way to make *every* engine mount already scrolled — the code path a
   * restored reload exercises on Chromium and nowhere else.
   *
   * What is asserted is a comparison, not a scene name: the state on landing must equal the state
   * reached by scrolling calmly to the very same offset. That needs no knowledge of the scroll
   * budgets or of which scene owns a hand-over boundary, so it stays ordinal — and it is exactly
   * the failure a machine that mounted without settling against the page's real position would
   * produce (it would report `loader` while the viewport showed the eighth scene).
   */
  test(`${route} — a deep link mounts the page mid-journey in the state that position calls for`, async ({
    page,
  }) => {
    await openJourney(page, `${route}#scene-tracks`);
    await settle(page);

    const mounted = await journeySnapshot(page);
    expect(mounted.scrollY, "the fragment must really start the page mid-journey").toBeGreaterThan(0);
    expect(mounted.activeSections, "exactly one scene is active on a deep-link mount").toHaveLength(1);
    expect(mounted.activeScene).toBe(mounted.activeSections[0]);
    expect(
      mounted.activeScene,
      "a page mounted deep in the journey must not report the first scene",
    ).not.toBe(SCENE_ORDER_FROM_BRIEF[0]);

    await calmScrollToY(page, mounted.scrollY);
    const arrived = await journeySnapshot(page);
    expect(arrived.activeSections, "landing here and scrolling here must agree").toEqual(
      mounted.activeSections,
    );
    expect(arrived.backgroundMode).toBe(mounted.backgroundMode);
    expect(arrived.headerVariant).toBe(mounted.headerVariant);
  });
}

test("navigating away and back reproduces an identical journey without growing the triggers", async ({
  page,
}) => {
  await openJourney(page, "/");
  const firstForward = await walkJourney(page, false, SECONDARY_WALK_SAMPLES);
  const firstBackward = await walkJourney(page, true, SECONDARY_WALK_SAMPLES);
  const before = await readDiagnostics(page);

  await openJourney(page, "/lens/beautiful-imperfection");
  await page.goBack();
  await waitPastLoader(page);
  await scrollToRatio(page, 0);

  const secondForward = await walkJourney(page, false, SECONDARY_WALK_SAMPLES);
  const secondBackward = await walkJourney(page, true, SECONDARY_WALK_SAMPLES);

  // The behavioural proxy BUILD-GUIDE asks for, and the strongest form of it: not just the same
  // scene at one position, but the identical state sequence across the whole page, both ways.
  expect(secondForward.sequence, "forward journey is identical after a route round trip").toEqual(
    firstForward.sequence,
  );
  expect(secondBackward.sequence, "reverse journey is identical after a route round trip").toEqual(
    firstBackward.sequence,
  );
  expect(secondForward.inconsistencies).toEqual([]);
  expect(secondBackward.inconsistencies).toEqual([]);

  const after = await readDiagnostics(page);
  if (before && after) {
    // Brief §17: "no accumulating ScrollTriggers". One per scene is the floor.
    expect(before.scrollTriggerCount).toBeGreaterThanOrEqual(SCENE_ORDER_FROM_BRIEF.length);
    expect(after.scrollTriggerCount, "triggers must not accumulate across route changes").toBe(
      before.scrollTriggerCount,
    );
  } else {
    test
      .info()
      .annotations.push({
        type: "note",
        description:
          "dev-only scene diagnostics are stripped from this build, so the ScrollTrigger count " +
          "could not be read; the behavioural proxy (identical forward and reverse state " +
          "sequences after the round trip) was asserted instead. Run this spec against a build " +
          "with NEXT_PUBLIC_DROP_DIAGNOSTICS=1, or the dev server, to exercise the count.",
      });
  }
});
