/**
 * Which Weekly Lenses the site can render, and which one `/` shows.
 *
 * The current lens is CONFIGURATION (brief §5: "`/` renders the configured `currentLensSlug`").
 * Routes and components read it from here; no call site hardcodes a slug.
 */

import { beautifulImperfectionLens } from "./lenses/beautiful-imperfection";
import type { WeeklyLens } from "./drop-weekly-lens.schema";

/**
 * Every published lens, oldest first. W01–W03 exist editorially (CONTEXT.md → "Weekly Lens")
 * but are not part of V1; adding one is a data change: validate it and list it here.
 */
export const publishedLenses: readonly WeeklyLens[] = [beautifulImperfectionLens];

/** The lens rendered at `/`. */
export const currentLensSlug = "beautiful-imperfection";

/** The validated lens `/` renders. */
export function getCurrentLens(): WeeklyLens {
  const lens = publishedLenses.find((candidate) => candidate.slug === currentLensSlug);
  if (!lens) {
    throw new Error(
      `Configured currentLensSlug "${currentLensSlug}" is not among the published lenses ` +
        `(${publishedLenses.map((candidate) => candidate.slug).join(", ") || "none"}).`,
    );
  }
  return lens;
}
