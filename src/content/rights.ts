/**
 * Production-media guard — the repo's extended version.
 *
 * Sources: brief §11 ("Content rules"), §18 ("Media Rights and Production Safety"),
 * CONTEXT.md → "Production-media guard".
 *
 * The handoff schema ships an `assertProductionMedia` that implements only the first clause
 * (development-mock / `productionAllowed: false`). This module is the guard the repo actually
 * uses:
 *
 *   1. BLOCKS while any asset is `development-mock` or `productionAllowed: false`;
 *   2. BLOCKS (fail-closed default) or warns loudly on required `replace-with-final` assets,
 *      controlled by `onReplaceWithFinal`;
 *   3. BLOCKS `rights-pending` assets — they are display-gated to development/staging behind an
 *      explicit internal flag (`DROP_SHOW_RIGHTS_PENDING`) and can never ship to production;
 *   4. names every blocking asset by scene + item id, and states the blocking count.
 *
 * The guard throwing on the current 20-asset mock pack is CORRECT behavior, not a bug. Never
 * weaken it, and never edit the `development-mock` / `productionAllowed: false` flags in content.
 */

import {
  assertProductionMedia as assertHandoffProductionMedia,
  type MediaAsset,
  type WeeklyLens,
} from "./drop-weekly-lens.schema";

/**
 * The handoff pack's narrower guard (first clause only), re-exported under a distinct name so
 * the extended `assertProductionMedia` below can own the public name.
 */
export { assertHandoffProductionMedia };

/** Scene a media asset belongs to. Uses the `SceneId` vocabulary from CONTEXT.md. */
export type MediaScene = "menu" | "films" | "tracks" | "artPieces";

/** A media asset plus where in the lens it came from, so failures can name the offender. */
export type LocatedMediaAsset = {
  asset: MediaAsset;
  scene: MediaScene;
  /** Id of the menu item / film / track / art piece carrying the asset. */
  itemId: string;
  /** `${scene}/${itemId}` — the stable label used in guard failure messages. */
  location: string;
};

/** How one asset stands relative to production clearance. */
export type RightsVerdict = "blocked" | "awaiting-final" | "cleared";

/** Full rights picture for one lens. `assertProductionMedia` is a thin wrapper over this. */
export type MediaRightsReview = {
  /** Every media asset in the lens, in menu → films → tracks → art pieces order. */
  assets: LocatedMediaAsset[];
  /** Assets that can never ship: development-mock, rights-pending, or productionAllowed: false. */
  blocking: LocatedMediaAsset[];
  /** Assets cleared to render but still flagged for final replacement. */
  awaitingFinal: LocatedMediaAsset[];
  /** Assets fully cleared for production. */
  cleared: LocatedMediaAsset[];
};

/** Where the site is running. `staging` is opted into explicitly via `DROP_ENV`. */
export type RuntimeEnvironment = "development" | "staging" | "production";

export type ProductionMediaOptions = {
  /**
   * What to do about required assets still marked `replace-with-final`.
   * Fail-closed default: `"throw"`.
   */
  onReplaceWithFinal?: "throw" | "warn";
  /** Sink for the loud warning. Defaults to `console.warn`. */
  warn?: (message: string) => void;
};

/**
 * First line of every guard failure. `scripts/assert-rights-guard-blocks.mjs` greps a build's
 * output for this string — keep the two in sync.
 */
export const PRODUCTION_MEDIA_GUARD_FAILURE = "Production media guard blocked the build";

/** Env var enabling the flagged production build path (`npm run build:production-check`). */
export const ENFORCE_MEDIA_RIGHTS_FLAG = "DROP_ENFORCE_MEDIA_RIGHTS";

/** Internal dev/staging flag that opts `rights-pending` media into rendering. */
export const SHOW_RIGHTS_PENDING_FLAG = "DROP_SHOW_RIGHTS_PENDING";

/** Overrides the detected runtime environment (`development` | `staging` | `production`). */
export const RUNTIME_ENVIRONMENT_VAR = "DROP_ENV";

const PRODUCTION_CLEARED_STATUSES: ReadonlySet<MediaAsset["rightsStatus"]> = new Set([
  "approved",
  "original-drop",
]);

const FALSY_FLAG_VALUES: ReadonlySet<string> = new Set(["", "0", "false", "off", "no"]);

function readEnv(name: string): string | undefined {
  // Guarded: this module is imported by client components too, where `process` may not exist.
  if (typeof process === "undefined" || !process.env) return undefined;
  return process.env[name];
}

function flagEnabled(name: string): boolean {
  const raw = readEnv(name);
  if (raw === undefined) return false;
  return !FALSY_FLAG_VALUES.has(raw.trim().toLowerCase());
}

/**
 * True when the flagged production build path is active. The default `next build` stays green
 * during development; a dedicated CI step sets the flag and asserts the guard blocks.
 */
export function isProductionRightsEnforced(): boolean {
  return flagEnabled(ENFORCE_MEDIA_RIGHTS_FLAG);
}

/** True when the explicit internal flag opting `rights-pending` media into rendering is set. */
export function isRightsPendingDisplayEnabled(): boolean {
  return flagEnabled(SHOW_RIGHTS_PENDING_FLAG);
}

/**
 * `DROP_ENV` when it names a known environment, else derived from `NODE_ENV`.
 *
 * The `NODE_ENV` read is deliberately the STATIC expression `process.env.NODE_ENV` rather than
 * `readEnv("NODE_ENV")`. This module is imported by client components (every scene that paints
 * an image asks {@link canDisplayAsset} whether it may), and a bundler can only inline the
 * literal form. Through the dynamic index the browser reads Next's empty `process.env` shim,
 * answers `undefined`, and falls through to `"development"` — so a PRODUCTION page would hydrate
 * with the whole `development-mock` pack painted over the withheld markup the server sent. That
 * is both a media-rights leak and a hydration mismatch; it was observed on a real production
 * build before this line was made static.
 *
 * `DROP_ENV` stays a dynamic read because it is a server-only variable with no client
 * counterpart: in the browser it is always absent, so a client component resolves from
 * `NODE_ENV` alone. A staging deploy that sets `DROP_ENV=staging` therefore has a server that
 * says "staging" and a browser that says "production"; today nothing sets it, and the fix when
 * something does is to thread the environment down from the server component as data, not to
 * make the browser guess harder.
 */
export function resolveRuntimeEnvironment(): RuntimeEnvironment {
  const explicit = readEnv(RUNTIME_ENVIRONMENT_VAR)?.trim().toLowerCase();
  if (explicit === "development" || explicit === "staging" || explicit === "production") {
    return explicit;
  }
  return process.env.NODE_ENV === "production" ? "production" : "development";
}

/** Every media asset across menu items, films, tracks, and art pieces, tagged with its origin. */
export function collectMediaAssets(lens: WeeklyLens): LocatedMediaAsset[] {
  const locate = (scene: MediaScene, itemId: string, asset: MediaAsset): LocatedMediaAsset => ({
    asset,
    scene,
    itemId,
    location: `${scene}/${itemId}`,
  });

  return [
    ...lens.menuItems.map((item) => locate("menu", item.id, item.image)),
    ...lens.films.map((film) => locate("films", film.id, film.poster)),
    ...lens.tracks.map((track) => locate("tracks", track.id, track.artwork)),
    ...lens.artPieces.map((piece) => locate("artPieces", piece.id, piece.media)),
  ];
}

/** Where one asset stands relative to production clearance. */
export function verdictFor(asset: MediaAsset): RightsVerdict {
  if (!asset.productionAllowed) return "blocked";

  switch (asset.rightsStatus) {
    case "development-mock":
      // The whole mock pack. Never ships.
      return "blocked";
    case "rights-pending":
      // Renders in development/staging behind the internal flag only; never in production.
      return "blocked";
    case "replace-with-final":
      return "awaiting-final";
    case "approved":
    case "original-drop":
      return "cleared";
    default: {
      const unexpected: never = asset.rightsStatus;
      throw new Error(`Unknown rightsStatus: ${String(unexpected)}`);
    }
  }
}

/** Group every asset of a lens by its production-clearance verdict. */
export function reviewMediaRights(lens: WeeklyLens): MediaRightsReview {
  const assets = collectMediaAssets(lens);
  return {
    assets,
    blocking: assets.filter((located) => verdictFor(located.asset) === "blocked"),
    awaitingFinal: assets.filter((located) => verdictFor(located.asset) === "awaiting-final"),
    cleared: assets.filter((located) => verdictFor(located.asset) === "cleared"),
  };
}

function formatAsset(located: LocatedMediaAsset): string {
  const { asset, location } = located;
  const note = asset.replacementNote ? ` — ${asset.replacementNote}` : "";
  return `  - ${location} [${asset.rightsStatus}, productionAllowed: ${asset.productionAllowed}] ${asset.src}${note}`;
}

/**
 * The repo's production-media guard. Throws while any asset is not cleared for production, and
 * (by default) while any required asset is still marked `replace-with-final`.
 *
 * @throws Error naming every blocking asset by scene/item id, and stating the count.
 */
export function assertProductionMedia(
  lens: WeeklyLens,
  options: ProductionMediaOptions = {},
): void {
  const { onReplaceWithFinal = "throw", warn = (message: string) => console.warn(message) } =
    options;
  const review = reviewMediaRights(lens);
  const total = review.assets.length;
  const problems: string[] = [];

  if (review.blocking.length > 0) {
    problems.push(
      `${review.blocking.length} of ${total} media asset(s) are not cleared for production ` +
        `(development-mock, rights-pending, or productionAllowed: false):\n` +
        review.blocking.map(formatAsset).join("\n"),
    );
  }

  if (review.awaitingFinal.length > 0 && onReplaceWithFinal === "throw") {
    problems.push(
      `${review.awaitingFinal.length} of ${total} required media asset(s) still marked ` +
        `"replace-with-final":\n` +
        review.awaitingFinal.map(formatAsset).join("\n"),
    );
  }

  if (problems.length > 0) {
    throw new Error(
      `${PRODUCTION_MEDIA_GUARD_FAILURE} for lens "${lens.slug}" (${lens.week}).\n\n` +
        `${problems.join("\n\n")}\n\n` +
        `See handoff/04-mock-content/REPLACE_BEFORE_LAUNCH.md. Clear or replace the assets — ` +
        `never weaken the guard.`,
    );
  }

  if (review.awaitingFinal.length > 0) {
    // Deliberately does NOT contain PRODUCTION_MEDIA_GUARD_FAILURE: a warning is not a block,
    // and the CI step greps build output for that exact string.
    warn(
      `WARNING — production media rights unresolved for lens "${lens.slug}" (${lens.week}): ` +
        `${review.awaitingFinal.length} of ${total} required media asset(s) still marked ` +
        `"replace-with-final".\n` +
        review.awaitingFinal.map(formatAsset).join("\n"),
    );
  }
}

/**
 * Build-time entry point: runs the guard only on the flagged production path, so the default
 * `next build` stays green while the mock pack is in place. Call from a module that Next
 * evaluates during the build (a route or the content module's consumer).
 */
export function enforceProductionMediaRights(
  lens: WeeklyLens,
  options: ProductionMediaOptions = {},
): void {
  if (!isProductionRightsEnforced()) return;
  assertProductionMedia(lens, options);
}

/**
 * Whether an asset may be rendered in a given environment.
 *
 * - production: only `approved` / `original-drop` assets with `productionAllowed: true`;
 * - development/staging: everything except `rights-pending`, which needs the explicit internal
 *   flag `DROP_SHOW_RIGHTS_PENDING`.
 */
export function canDisplayAsset(
  asset: MediaAsset,
  environment: RuntimeEnvironment = resolveRuntimeEnvironment(),
): boolean {
  if (environment === "production") {
    return asset.productionAllowed && PRODUCTION_CLEARED_STATUSES.has(asset.rightsStatus);
  }
  if (asset.rightsStatus === "rights-pending") {
    return isRightsPendingDisplayEnabled();
  }
  return true;
}
