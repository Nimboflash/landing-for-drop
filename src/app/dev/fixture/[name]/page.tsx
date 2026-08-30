import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ImmersiveLensPage } from "@/components/shell";
import { resolveRuntimeEnvironment, type WeeklyLens } from "@/content";
import { countFixtureLenses } from "@/content/lenses/variable-count-fixture";

/**
 * `/dev/fixture/[name]` — a DEVELOPMENT-ONLY harness that renders a count fixture lens through
 * the real immersive template (ticket 15, brief §21 "Content" row).
 *
 * ## Why this route exists
 *
 * The brief's Content row asks for the site to be exercised with counts other than W04's, and
 * §11 asks that "a scene gracefully handles the minimum allowed content count". Neither can be
 * proved by a unit test: the claim is about the assembled scene components — five menu cards
 * fanning, four coverflow slides, six art rows, a single art row that still reads as an editorial
 * row, one hero message that still advances. That needs the real page, so it needs a route.
 *
 * `src/content/lenses/variable-count-fixture.ts` deliberately keeps its lenses out of
 * `publishedLenses`, so `/lens/[slug]` cannot reach them — hence a separate, gated route rather
 * than publishing test data.
 *
 * ## Why it can never ship
 *
 * Two independent gates, both of which must be open:
 *
 * 1. `process.env.NODE_ENV === "production"` — a STATIC read, so a bundler inlines it and the
 *    production build compiles this page down to an unconditional `notFound()`;
 * 2. `resolveRuntimeEnvironment() !== "development"` — the content module's own public reading of
 *    `DROP_ENV` / `NODE_ENV`. Staging is a DEPLOYED environment, so it is refused too: a fixture
 *    lens is not content, and a deployed URL that renders synthetic content is a URL that can be
 *    shared, indexed, or mistaken for the week's lens.
 *
 * `dynamic = "force-dynamic"` keeps it out of the prerender manifest as well, so a production
 * build never emits a static HTML file for it. The route is additionally `noindex, nofollow`, for
 * the development and local-network case where it does render.
 *
 * This is the same shape as `/brand-preview`, which gates itself the same way and correctly 404s
 * on the production server.
 *
 * ## What it does NOT do
 *
 * It does not weaken the media-rights guard. The fixtures reuse the W04 mock pack, so every asset
 * on this page is still `development-mock` / `productionAllowed: false`, and `canDisplayAsset`
 * still decides — inside the scenes — whether anything paints. The fixtures are absent from
 * `publishedLenses`, so the module-scope guard in `src/content/index.ts` never sees them and this
 * route cannot be used to sneak unreviewed media into a build.
 */

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Content fixture",
  robots: { index: false, follow: false },
};

type FixtureRouteProps = {
  /** Next 16: route params arrive as a PROMISE and must be awaited. */
  params: Promise<{ name: string }>;
};

/**
 * The fixtures this route can render, keyed by their own slug. Data-driven: adding a fixture to
 * `countFixtureLenses` publishes it here, and no name is written into this file.
 */
const FIXTURES: ReadonlyMap<string, WeeklyLens> = new Map(
  countFixtureLenses.map((lens) => [lens.slug, lens] as const),
);

/**
 * Both gates. Kept as one expression so there is a single place to read the answer, and NOT
 * exported — an App Router page may only export the framework's own names.
 */
function fixtureRouteEnabled(): boolean {
  if (process.env.NODE_ENV === "production") return false;
  return resolveRuntimeEnvironment() === "development";
}

export default async function DevFixturePage({ params }: FixtureRouteProps) {
  // Gate first: an unknown environment must not even reveal which fixture names exist.
  if (!fixtureRouteEnabled()) notFound();

  const { name } = await params;
  const lens = FIXTURES.get(name);
  if (!lens) notFound();

  // Keyed by slug, exactly as `/` and `/lens/[slug]` do, so the scene-state machine mounts fresh
  // for each fixture instead of inheriting the previous lens's indices.
  return <ImmersiveLensPage key={lens.slug} lens={lens} />;
}
