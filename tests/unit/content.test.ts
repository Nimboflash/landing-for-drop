/**
 * Content seam (BUILD-GUIDE seam 1) — the content module's public API.
 *
 * Expected values come from independent sources, never from the code under test:
 *   - `handoff/04-mock-content/media-manifest.csv` for asset counts, paths, and rights flags;
 *   - the master brief (§7.2 hero messages, §7.3 menu, §7.6 films, §7.9 art pieces, §10 seed
 *     content, §11 content rules) for content values and required guard behavior.
 *
 * The production-media guard THROWING on the W04 mock pack is the asserted-correct behavior.
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  assertProductionMedia,
  beautifulImperfectionLens,
  canDisplayAsset,
  collectMediaAssets,
  currentLensSlug,
  enforceProductionMediaRights,
  getCurrentLens,
  getLensBySlug,
  isProductionRightsEnforced,
  listLenses,
  reviewMediaRights,
  weeklyLensSchema,
  type MediaAsset,
  type WeeklyLens,
} from "@/content";
import {
  minimumCountsFixtureLens,
  variableCountFixtureLens,
} from "@/content/lenses/variable-count-fixture";
import rawW04 from "@/content/lenses/beautiful-imperfection.mock.json";

// --- independent expectations: the shipped media manifest --------------------------------

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

type ManifestRow = {
  asset_id: string;
  scene: string;
  target_public_path: string;
  rights_status: string;
  production_allowed: string;
};

function readMediaManifest(): ManifestRow[] {
  const csv = readFileSync(
    path.join(repoRoot, "handoff", "04-mock-content", "media-manifest.csv"),
    "utf8",
  );
  const [headerLine, ...lines] = csv.trim().split("\n");
  const columns = headerLine.split(",");
  return lines.map((line) => {
    const cells = line.split(",");
    const row: Record<string, string> = {};
    columns.forEach((column, index) => {
      // The trailing instruction column may itself contain commas.
      row[column] =
        index === columns.length - 1 ? cells.slice(index).join(",") : (cells[index] ?? "");
    });
    return row as unknown as ManifestRow;
  });
}

const manifest = readMediaManifest();
const manifestRowsFor = (scene: string) => manifest.filter((row) => row.scene === scene);

/** Brief §7.2: the W04 pinned thesis cycles exactly three hero messages. */
const HERO_MESSAGE_COUNT = 3;

function clone(lens: WeeklyLens): WeeklyLens {
  return JSON.parse(JSON.stringify(lens)) as WeeklyLens;
}

/** A W04 clone with every media asset forced into one rights state. */
function lensWithMediaRights(
  rightsStatus: MediaAsset["rightsStatus"],
  productionAllowed: boolean,
): WeeklyLens {
  const lens = clone(beautifulImperfectionLens);
  const patch = (asset: MediaAsset) => {
    asset.rightsStatus = rightsStatus;
    asset.productionAllowed = productionAllowed;
  };
  lens.menuItems.forEach((item) => patch(item.image));
  lens.films.forEach((film) => patch(film.poster));
  lens.tracks.forEach((track) => patch(track.artwork));
  lens.artPieces.forEach((piece) => patch(piece.media));
  // Re-parse: a rights fixture that no longer satisfies the schema would prove nothing.
  return weeklyLensSchema.parse(lens);
}

function anAssetWith(rightsStatus: MediaAsset["rightsStatus"], productionAllowed: boolean) {
  const asset = clone(beautifulImperfectionLens).menuItems[0].image;
  asset.rightsStatus = rightsStatus;
  asset.productionAllowed = productionAllowed;
  return asset;
}

const ENV_KEYS = ["DROP_SHOW_RIGHTS_PENDING", "DROP_ENFORCE_MEDIA_RIGHTS", "DROP_ENV"] as const;
let savedEnv: Record<string, string | undefined> = {};

beforeEach(() => {
  savedEnv = Object.fromEntries(ENV_KEYS.map((key) => [key, process.env[key]]));
  ENV_KEYS.forEach((key) => delete process.env[key]);
});

afterEach(() => {
  ENV_KEYS.forEach((key) => {
    const value = savedEnv[key];
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  });
});

// --- the media manifest itself ------------------------------------------------------------

describe("media manifest (the expectations source)", () => {
  it("describes the twenty mock assets the brief promises", () => {
    // Brief §0.1 / §5 QA matrix: 2 menu, 3 films, 11 tracks, 4 art pieces = 20 local assets.
    expect(manifest).toHaveLength(20);
    expect(manifestRowsFor("menu")).toHaveLength(2);
    expect(manifestRowsFor("films")).toHaveLength(3);
    expect(manifestRowsFor("tracks")).toHaveLength(11);
    expect(manifestRowsFor("art")).toHaveLength(4);
  });

  it("keeps every mock asset flagged development-mock and production-disallowed", () => {
    for (const row of manifest) {
      expect(row.rights_status).toBe("development-mock");
      expect(row.production_allowed).toBe("false");
    }
  });
});

// --- W04 content ---------------------------------------------------------------------------

describe("W04 Beautiful Imperfection lens", () => {
  it("parses through weeklyLensSchema", () => {
    expect(() => weeklyLensSchema.parse(rawW04)).not.toThrow();
    expect(beautifulImperfectionLens).toEqual(weeklyLensSchema.parse(rawW04));
  });

  it("carries the seed identity from the brief", () => {
    expect(beautifulImperfectionLens.slug).toBe("beautiful-imperfection");
    expect(beautifulImperfectionLens.week).toBe("W04");
    expect(beautifulImperfectionLens.title.en).toBe("BEAUTIFUL IMPERFECTION");
    expect(beautifulImperfectionLens.title.fa).toBe("زیبایی در کامل نبودن");
    expect(beautifulImperfectionLens.contentMode).toBe("development-mock");
  });

  it("has the counts the media manifest and the brief prescribe", () => {
    expect(beautifulImperfectionLens.menuItems).toHaveLength(manifestRowsFor("menu").length);
    expect(beautifulImperfectionLens.films).toHaveLength(manifestRowsFor("films").length);
    expect(beautifulImperfectionLens.tracks).toHaveLength(manifestRowsFor("tracks").length);
    expect(beautifulImperfectionLens.artPieces).toHaveLength(manifestRowsFor("art").length);
    expect(beautifulImperfectionLens.heroMessages).toHaveLength(HERO_MESSAGE_COUNT);
  });

  it("uses exactly the local media paths listed in the manifest", () => {
    const lensPaths = collectMediaAssets(beautifulImperfectionLens)
      .map((located) => located.asset.src)
      .sort();
    const manifestPaths = manifest.map((row) => row.target_public_path).sort();
    expect(lensPaths).toEqual(manifestPaths);
  });

  it("serves every media file locally from public/", () => {
    for (const located of collectMediaAssets(beautifulImperfectionLens)) {
      const filePath = path.join(repoRoot, "public", located.asset.src.replace(/^\//, ""));
      expect(existsSync(filePath), `missing local asset for ${located.location}`).toBe(true);
    }
  });

  it("presents the three films in view order (brief §7.6)", () => {
    expect(beautifulImperfectionLens.films.map((film) => film.title)).toEqual([
      "SHOWING UP",
      "PERFECT DAYS",
      "PATERSON",
    ]);
    expect(beautifulImperfectionLens.films.map((film) => film.director)).toEqual([
      "Kelly Reichardt",
      "Wim Wenders",
      "Jim Jarmusch",
    ]);
    expect(beautifulImperfectionLens.films.map((film) => film.year)).toEqual([
      "2023",
      "2023",
      "2016",
    ]);
    expect(beautifulImperfectionLens.films.map((film) => film.viewLabel.en)).toEqual([
      "FIRST VIEW",
      "SECOND VIEW",
      "COMPLETING VIEW",
    ]);
  });

  it("presents the two seed menu items with their makers (brief §7.3)", () => {
    expect(beautifulImperfectionLens.menuItems.map((item) => item.name.en)).toEqual([
      "WEEKLY FRUIT TART",
      "MOCHI BITE BOX",
    ]);
    expect(beautifulImperfectionLens.menuItems.map((item) => item.maker)).toEqual([
      "ÉCLAIR",
      "MOCHIKI",
    ]);
  });

  it("groups the eleven tracks by period as the brief's sound edit does (§10)", () => {
    const byPeriod = (period: string) =>
      beautifulImperfectionLens.tracks.filter((track) => track.period === period);
    expect(byPeriod("morning")).toHaveLength(4);
    expect(byPeriod("afternoon")).toHaveLength(3);
    expect(byPeriod("night")).toHaveLength(4);
  });

  it("presents the four art pieces of the field notes (brief §7.9)", () => {
    expect(beautifulImperfectionLens.artPieces.map((piece) => piece.title)).toEqual([
      "BRION MEMORIAL",
      "UNTITLED (S.270)",
      "UNTITLED, FROM ILLUMINANCE",
      "THE PRATFALL EFFECT",
    ]);
    expect(beautifulImperfectionLens.artPieces.map((piece) => piece.creator)).toEqual([
      "Carlo Scarpa",
      "Ruth Asawa",
      "Rinko Kawauchi",
      undefined,
    ]);
    expect(beautifulImperfectionLens.artPieces[3].duration).toBe("3 MIN READ");
  });

  it("carries the brand statement used by the grid scene and the footer (brief §7.4, §7.10)", () => {
    expect(beautifulImperfectionLens.gridStatement.en).toBe("A PLACE WITH A POINT OF VIEW.");
    expect(beautifulImperfectionLens.footer.statement.en).toBe("A PLACE WITH A POINT OF VIEW.");
  });

  it("keeps the footer CTA and every footer link disabled until final destinations exist", () => {
    expect(beautifulImperfectionLens.footer.cta?.enabled).toBe(false);
    for (const link of beautifulImperfectionLens.footer.links) {
      expect(link.enabled).toBe(false);
      expect(link.href).toBe("");
    }
  });
});

// --- bilingual completeness ----------------------------------------------------------------

type LocalizedNode = { at: string; fa: unknown; en: unknown };

function collectLocalizedText(value: unknown, at = "$", found: LocalizedNode[] = []) {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => collectLocalizedText(entry, `${at}[${index}]`, found));
    return found;
  }
  if (value !== null && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.fa === "string" || "fa" in record) {
      found.push({ at, fa: record.fa, en: record.en });
    }
    for (const [key, entry] of Object.entries(record)) {
      collectLocalizedText(entry, `${at}.${key}`, found);
    }
    return found;
  }
  return found;
}

describe("bilingual completeness", () => {
  const localized = collectLocalizedText(beautifulImperfectionLens);

  it("finds the lens's localized fields", () => {
    // Sanity floor for the walker itself; the mock pack carries dozens of localized fields.
    expect(localized.length).toBeGreaterThan(50);
  });

  it("has a non-empty Persian string everywhere (Persian is the primary language)", () => {
    const missingFa = localized.filter((node) => typeof node.fa !== "string" || node.fa === "");
    expect(missingFa.map((node) => node.at)).toEqual([]);
  });

  it("has the English strings the mock pack supplies on every localized field", () => {
    const missingEn = localized.filter((node) => typeof node.en !== "string" || node.en === "");
    expect(missingEn.map((node) => node.at)).toEqual([]);
  });
});

// --- malformed data ------------------------------------------------------------------------

describe("malformed lens data fails loudly", () => {
  it("rejects a remote media src (no hotlinking, ever)", () => {
    const lens = clone(beautifulImperfectionLens);
    lens.menuItems[0].image.src = "https://cdn.example.com/hotlinked-product-photo.webp";
    expect(() => weeklyLensSchema.parse(lens)).toThrow();
  });

  it("rejects a malformed week code", () => {
    const lens = clone(beautifulImperfectionLens);
    lens.week = "week-4";
    expect(() => weeklyLensSchema.parse(lens)).toThrow();
  });

  it("rejects a film count other than three", () => {
    const tooFew = clone(beautifulImperfectionLens);
    tooFew.films = tooFew.films.slice(0, 2);
    expect(() => weeklyLensSchema.parse(tooFew)).toThrow();

    const tooMany = clone(beautifulImperfectionLens);
    tooMany.films = [...tooMany.films, tooMany.films[0]];
    expect(() => weeklyLensSchema.parse(tooMany)).toThrow();
  });

  it("rejects an empty Persian string", () => {
    const lens = clone(beautifulImperfectionLens);
    lens.heroMessages[0].fa = "";
    expect(() => weeklyLensSchema.parse(lens)).toThrow();
  });

  it("rejects a menu deck outside the 2–6 range the brief allows", () => {
    const lens = clone(beautifulImperfectionLens);
    lens.menuItems = lens.menuItems.slice(0, 1);
    expect(() => weeklyLensSchema.parse(lens)).toThrow();
  });
});

// --- production-media guard ------------------------------------------------------------------

describe("production-media guard", () => {
  it("collects every media asset tagged with the scene and item it came from", () => {
    const collected = collectMediaAssets(beautifulImperfectionLens);
    expect(collected).toHaveLength(manifest.length);

    const perScene = (scene: string) => collected.filter((located) => located.scene === scene);
    expect(perScene("menu")).toHaveLength(manifestRowsFor("menu").length);
    expect(perScene("films")).toHaveLength(manifestRowsFor("films").length);
    expect(perScene("tracks")).toHaveLength(manifestRowsFor("tracks").length);
    expect(perScene("artPieces")).toHaveLength(manifestRowsFor("art").length);

    expect(collected[0].location).toBe("menu/weekly-fruit-tart");
  });

  it("throws on the W04 mock pack — the correct behavior until launch clearance", () => {
    let thrown: Error | undefined;
    try {
      assertProductionMedia(beautifulImperfectionLens);
    } catch (error) {
      thrown = error as Error;
    }

    expect(thrown, "the guard must block while mock assets remain").toBeDefined();
    const message = thrown!.message;
    // The message states the blocking count (all 20 manifest assets) and names offenders.
    expect(message).toMatch(new RegExp(`\\b${manifest.length}\\b`));
    expect(message).toContain("menu/weekly-fruit-tart");
    expect(message).toContain("artPieces/pratfall-effect");
    expect(message).toContain("development-mock");
  });

  it("blocks while assets are development-mock", () => {
    expect(() => assertProductionMedia(lensWithMediaRights("development-mock", false))).toThrow();
  });

  it("blocks any asset with productionAllowed: false, whatever its rights status", () => {
    expect(() => assertProductionMedia(lensWithMediaRights("approved", false))).toThrow(
      /productionAllowed: false/,
    );
  });

  it("blocks rights-pending assets, which never ship to production", () => {
    expect(() => assertProductionMedia(lensWithMediaRights("rights-pending", true))).toThrow(
      /rights-pending/,
    );
  });

  it("fails loudly by default on required replace-with-final assets", () => {
    expect(() => assertProductionMedia(lensWithMediaRights("replace-with-final", true))).toThrow(
      /replace-with-final/,
    );
  });

  it("warns loudly instead when replace-with-final is explicitly downgraded to a warning", () => {
    const warn = vi.fn();
    const lens = lensWithMediaRights("replace-with-final", true);

    expect(() =>
      assertProductionMedia(lens, { onReplaceWithFinal: "warn", warn }),
    ).not.toThrow();

    expect(warn).toHaveBeenCalledTimes(1);
    const message = warn.mock.calls[0][0] as string;
    expect(message).toContain("WARNING");
    expect(message).toMatch(new RegExp(`\\b${manifest.length}\\b`));
    expect(message).toContain("replace-with-final");
  });

  it("passes for approved and original-drop media", () => {
    expect(() => assertProductionMedia(lensWithMediaRights("approved", true))).not.toThrow();
    expect(() => assertProductionMedia(lensWithMediaRights("original-drop", true))).not.toThrow();
  });

  it("reviews a lens into blocking / awaiting-final / cleared groups", () => {
    const mockReview = reviewMediaRights(beautifulImperfectionLens);
    expect(mockReview.blocking).toHaveLength(manifest.length);
    expect(mockReview.cleared).toHaveLength(0);

    const clearedReview = reviewMediaRights(lensWithMediaRights("original-drop", true));
    expect(clearedReview.cleared).toHaveLength(manifest.length);
    expect(clearedReview.blocking).toHaveLength(0);

    const awaitingReview = reviewMediaRights(lensWithMediaRights("replace-with-final", true));
    expect(awaitingReview.awaitingFinal).toHaveLength(manifest.length);
  });
});

// --- rights enforcement flag -------------------------------------------------------------------

describe("production rights enforcement flag", () => {
  it("is off unless DROP_ENFORCE_MEDIA_RIGHTS is set, so the default build stays green", () => {
    expect(isProductionRightsEnforced()).toBe(false);
    expect(() => enforceProductionMediaRights(beautifulImperfectionLens)).not.toThrow();
  });

  it("runs the guard on the flagged production build path", () => {
    process.env.DROP_ENFORCE_MEDIA_RIGHTS = "1";
    expect(isProductionRightsEnforced()).toBe(true);
    expect(() => enforceProductionMediaRights(beautifulImperfectionLens)).toThrow(
      /Production media guard blocked the build/,
    );
  });

  it("treats an explicitly falsy flag value as off", () => {
    process.env.DROP_ENFORCE_MEDIA_RIGHTS = "0";
    expect(isProductionRightsEnforced()).toBe(false);
  });

  it("blocks the flagged build at the content module itself, so no route can forget it", async () => {
    // Both routes and the root layout import the content module; the module-scope gate is what
    // `npm run ci:rights-guard` relies on. Re-imported in isolation so the flag is read fresh.
    vi.resetModules();
    process.env.DROP_ENFORCE_MEDIA_RIGHTS = "1";
    await expect(import("@/content")).rejects.toThrow(/Production media guard blocked the build/);
    vi.resetModules();
  });

  it("imports cleanly with the flag unset, keeping the default build green", async () => {
    vi.resetModules();
    await expect(import("@/content")).resolves.toBeDefined();
    vi.resetModules();
  });
});

// --- display gating -----------------------------------------------------------------------------

describe("asset display gating", () => {
  it("shows rights-pending media in development only behind the explicit internal flag", () => {
    const asset = anAssetWith("rights-pending", true);

    expect(canDisplayAsset(asset, "development")).toBe(false);
    expect(canDisplayAsset(asset, "staging")).toBe(false);

    process.env.DROP_SHOW_RIGHTS_PENDING = "1";
    expect(canDisplayAsset(asset, "development")).toBe(true);
    expect(canDisplayAsset(asset, "staging")).toBe(true);
  });

  it("never shows rights-pending media in production, flag or not", () => {
    const asset = anAssetWith("rights-pending", true);

    expect(canDisplayAsset(asset, "production")).toBe(false);
    process.env.DROP_SHOW_RIGHTS_PENDING = "1";
    expect(canDisplayAsset(asset, "production")).toBe(false);
  });

  it("shows the development mock pack in development but never in production", () => {
    const asset = anAssetWith("development-mock", false);

    expect(canDisplayAsset(asset, "development")).toBe(true);
    expect(canDisplayAsset(asset, "staging")).toBe(true);
    expect(canDisplayAsset(asset, "production")).toBe(false);
  });

  it("shows cleared media everywhere", () => {
    for (const status of ["approved", "original-drop"] as const) {
      const asset = anAssetWith(status, true);
      expect(canDisplayAsset(asset, "development")).toBe(true);
      expect(canDisplayAsset(asset, "staging")).toBe(true);
      expect(canDisplayAsset(asset, "production")).toBe(true);
    }
  });

  it("hides replace-with-final media from production until it is replaced", () => {
    const asset = anAssetWith("replace-with-final", true);
    expect(canDisplayAsset(asset, "development")).toBe(true);
    expect(canDisplayAsset(asset, "production")).toBe(false);
  });
});

// --- lens lookup ---------------------------------------------------------------------------------

describe("lens lookup", () => {
  it("returns the W04 lens for its slug", () => {
    expect(getLensBySlug("beautiful-imperfection")).toBe(beautifulImperfectionLens);
  });

  it("returns undefined for an unknown slug", () => {
    expect(getLensBySlug("controlled-tension")).toBeUndefined();
    expect(getLensBySlug("")).toBeUndefined();
  });

  it("lists the published lenses, each with a unique slug", () => {
    const lenses = listLenses();
    expect(lenses).toContain(beautifulImperfectionLens);
    expect(new Set(lenses.map((lens) => lens.slug)).size).toBe(lenses.length);
  });

  it("keeps development fixtures out of the published lenses", () => {
    expect(getLensBySlug(variableCountFixtureLens.slug)).toBeUndefined();
    expect(getLensBySlug(minimumCountsFixtureLens.slug)).toBeUndefined();
  });

  it("renders the configured current lens at the root route", () => {
    expect(currentLensSlug).toBe("beautiful-imperfection");
    expect(getCurrentLens()).toBe(beautifulImperfectionLens);
    expect(getCurrentLens().slug).toBe(currentLensSlug);
  });
});

// --- variable-count fixtures ------------------------------------------------------------------------

describe("count fixtures", () => {
  it("exposes counts unlike W04's, for count-driven scene tests", () => {
    expect(variableCountFixtureLens.menuItems).toHaveLength(5);
    expect(variableCountFixtureLens.films).toHaveLength(3);
    expect(variableCountFixtureLens.tracks).toHaveLength(4);
    expect(variableCountFixtureLens.artPieces).toHaveLength(6);
    expect(variableCountFixtureLens.heroMessages).toHaveLength(2);
  });

  it("exposes the schema minimums", () => {
    expect(minimumCountsFixtureLens.menuItems).toHaveLength(2);
    expect(minimumCountsFixtureLens.films).toHaveLength(3);
    expect(minimumCountsFixtureLens.tracks).toHaveLength(3);
    expect(minimumCountsFixtureLens.artPieces).toHaveLength(1);
    expect(minimumCountsFixtureLens.heroMessages).toHaveLength(1);
  });

  it("parses against the real schema", () => {
    for (const fixture of [variableCountFixtureLens, minimumCountsFixtureLens]) {
      expect(() => weeklyLensSchema.parse(fixture)).not.toThrow();
    }
  });

  it("reuses W04 media, so fixture renders never 404", () => {
    const w04Paths = new Set(
      collectMediaAssets(beautifulImperfectionLens).map((located) => located.asset.src),
    );
    for (const fixture of [variableCountFixtureLens, minimumCountsFixtureLens]) {
      for (const located of collectMediaAssets(fixture)) {
        expect(w04Paths.has(located.asset.src)).toBe(true);
        expect(
          existsSync(path.join(repoRoot, "public", located.asset.src.replace(/^\//, ""))),
        ).toBe(true);
      }
    }
  });

  it("stays blocked by the production guard like every development lens", () => {
    for (const fixture of [variableCountFixtureLens, minimumCountsFixtureLens]) {
      expect(() => assertProductionMedia(fixture)).toThrow();
    }
  });
});
