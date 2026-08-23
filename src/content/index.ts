/**
 * Content module — the single source of truth for lens data, consumed by both routes.
 *
 * Scene components receive lens data as props from a route; they never import media paths,
 * copy, or counts of their own (CLAUDE.md hard rule: content is data-driven, counts come from
 * array lengths).
 *
 * Test fixtures live beside the seed content but are deliberately NOT exported here — import
 * `@/content/lenses/variable-count-fixture` directly from tests.
 */

import type { z } from "zod";
import type {
  artPieceSchema,
  filmRecommendationSchema,
  footerLinkSchema,
  localizedTextSchema,
  menuItemSchema,
  trackRecommendationSchema,
} from "./drop-weekly-lens.schema";
import type { WeeklyLens } from "./drop-weekly-lens.schema";
import { publishedLenses } from "./current-lens";
import { enforceProductionMediaRights } from "./rights";

// --- schema -----------------------------------------------------------------------------

export {
  weeklyLensSchema,
  localizedTextSchema,
  mediaAssetSchema,
  menuItemSchema,
  filmRecommendationSchema,
  trackRecommendationSchema,
  artPieceSchema,
  footerLinkSchema,
} from "./drop-weekly-lens.schema";

export type { WeeklyLens, MediaAsset } from "./drop-weekly-lens.schema";

/** Item types scene components consume, inferred from the adopted schema. */
export type LocalizedText = z.infer<typeof localizedTextSchema>;
export type MenuItem = z.infer<typeof menuItemSchema>;
export type FilmRecommendation = z.infer<typeof filmRecommendationSchema>;
export type TrackRecommendation = z.infer<typeof trackRecommendationSchema>;
export type ArtPiece = z.infer<typeof artPieceSchema>;
export type FooterLink = z.infer<typeof footerLinkSchema>;

// --- lenses -----------------------------------------------------------------------------

export { beautifulImperfectionLens } from "./lenses/beautiful-imperfection";
export { currentLensSlug, getCurrentLens, publishedLenses } from "./current-lens";

/** Every published lens, oldest first. Counts and ordering come from the data, never a literal. */
export function listLenses(): readonly WeeklyLens[] {
  return publishedLenses;
}

/** The validated lens for a slug, or `undefined` when no such lens is published. */
export function getLensBySlug(slug: string): WeeklyLens | undefined {
  return publishedLenses.find((lens) => lens.slug === slug);
}

// --- media rights -----------------------------------------------------------------------

export {
  assertProductionMedia,
  assertHandoffProductionMedia,
  canDisplayAsset,
  collectMediaAssets,
  enforceProductionMediaRights,
  isProductionRightsEnforced,
  isRightsPendingDisplayEnabled,
  resolveRuntimeEnvironment,
  reviewMediaRights,
  verdictFor,
  ENFORCE_MEDIA_RIGHTS_FLAG,
  PRODUCTION_MEDIA_GUARD_FAILURE,
  RUNTIME_ENVIRONMENT_VAR,
  SHOW_RIGHTS_PENDING_FLAG,
} from "./rights";

export type {
  LocatedMediaAsset,
  MediaRightsReview,
  MediaScene,
  ProductionMediaOptions,
  RightsVerdict,
  RuntimeEnvironment,
} from "./rights";

// --- build-time media-rights gate ---------------------------------------------------------

/**
 * The production-media guard, run at module scope over every published lens.
 *
 * A NO-OP unless `DROP_ENFORCE_MEDIA_RIGHTS` is set, so the default `next build` and `next dev`
 * stay green while the development mock pack is in place (BUILD-GUIDE → "Production-guard CI
 * wiring"). On the flagged path (`npm run build:production-check`) it throws, failing the build.
 *
 * It lives here rather than in a route because this module is the single content entry point
 * both routes and the root layout import: wiring the guard to the data, not to a page, means no
 * future route can forget to call it. Client bundles never see the flag (Next only inlines
 * `NEXT_PUBLIC_*`), so the check is inert in the browser.
 */
for (const lens of publishedLenses) {
  enforceProductionMediaRights(lens);
}
