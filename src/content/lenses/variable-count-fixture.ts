/**
 * Synthetic fixture lenses that exercise counts other than W04's.
 *
 * Purpose: every count-driven slot in the site (menu deck fan angles, track scroll budget,
 * art-piece rows, hero message sequence) must derive from array lengths, never from a literal.
 * These fixtures let seam-1 and seam-2 tests prove that with data W04 cannot provide.
 *
 * They PARSE against the real `weeklyLensSchema` — a fixture that skipped validation would not
 * prove anything about real content. Note the schema pins `films` at exactly 3
 * (CONTEXT.md → "Film edit"), so both fixtures carry 3 films by construction.
 *
 * Media is reused from the W04 mock pack so fixture renders never 404. That also means fixture
 * assets stay `development-mock` / `productionAllowed: false`: these lenses are development-only
 * and are deliberately absent from `publishedLenses`.
 */

import { beautifulImperfectionLens as w04 } from "./beautiful-imperfection";
import { weeklyLensSchema, type MediaAsset, type WeeklyLens } from "../drop-weekly-lens.schema";

const menuImages: readonly MediaAsset[] = w04.menuItems.map((item) => item.image);
const filmPosters: readonly MediaAsset[] = w04.films.map((film) => film.poster);
const trackArtworks: readonly MediaAsset[] = w04.tracks.map((track) => track.artwork);
const artMedia: readonly MediaAsset[] = w04.artPieces.map((piece) => piece.media);

const TRACK_GROUPS = [
  { id: "fixture-morning", period: "morning", fa: "صبح آزمایشی", en: "FIXTURE MORNING" },
  { id: "fixture-afternoon", period: "afternoon", fa: "بعدازظهر آزمایشی", en: "FIXTURE AFTERNOON" },
  { id: "fixture-night", period: "night", fa: "شب آزمایشی", en: "FIXTURE NIGHT" },
] as const;

/** Films are pinned at exactly 3 by the adopted schema. */
const FILM_COUNT = 3;

function cycle<T>(source: readonly T[], index: number): T {
  return source[index % source.length] as T;
}

type FixtureCounts = {
  heroMessages: number;
  menuItems: number;
  tracks: number;
  artPieces: number;
};

type FixtureConfig = {
  slug: string;
  week: string;
  titleFa: string;
  titleEn: string;
  counts: FixtureCounts;
};

function range(count: number): number[] {
  return Array.from({ length: count }, (_, index) => index);
}

function buildFixtureLens(config: FixtureConfig): WeeklyLens {
  const { slug, week, titleFa, titleEn, counts } = config;
  const label = (index: number) => `${titleEn} ${index + 1}`;

  const raw = {
    schemaVersion: "1.0",
    contentMode: "development-mock",
    publicationStatus: "draft",
    slug,
    week,
    title: { fa: titleFa, en: titleEn },
    thesis: {
      fa: "این لنز فقط برای آزمودن شمارش‌های متغیر ساخته شده است.",
      en: "This lens exists only to exercise variable content counts.",
    },
    tension: {
      fa: "شمارش‌ها از داده می‌آیند، نه از عدد ثابت در کد.",
      en: "Counts come from data, never from a literal in code.",
    },
    balance: {
      fa: "هر اسلات از طول آرایه ساخته می‌شود.",
      en: "Every slot derives from an array length.",
    },
    notThis: {
      fa: "این محتوای منتشرشده نیست و هرگز در سایت رندر نمی‌شود.",
      en: "This is not published content and never renders on the site.",
    },
    heroMessages: range(counts.heroMessages).map((index) => ({
      fa: `پیام آزمایشی ${index + 1}`,
      en: `FIXTURE MESSAGE ${index + 1}`,
    })),
    gridStatement: { fa: "جمله‌ی آزمایشی شبکه.", en: "FIXTURE GRID STATEMENT." },
    sectionLabels: {
      menu: { fa: "منوی آزمایشی", en: "FIXTURE TASTE EDIT" },
      films: { fa: "فیلم‌های آزمایشی", en: "FIXTURE VIEWS" },
      tracks: { fa: "قطعه‌های آزمایشی", en: "FIXTURE TRACKS" },
      artPieces: { fa: "قطعه‌های هنری آزمایشی", en: "FIXTURE ART PIECES" },
    },
    menuItems: range(counts.menuItems).map((index) => ({
      id: `${slug}-menu-${index + 1}`,
      name: { fa: `آیتم منوی ${index + 1}`, en: label(index) },
      maker: `FIXTURE MAKER ${index + 1}`,
      category: { fa: "مزه / آزمایشی", en: "TASTE / FIXTURE" },
      rationale: {
        fa: "دلیل انتخاب آزمایشی برای این آیتم.",
        en: "Fixture selection rationale for this item.",
      },
      image: cycle(menuImages, index),
    })),
    films: range(FILM_COUNT).map((index) => ({
      id: `${slug}-film-${index + 1}`,
      viewLabel: { fa: `نگاه ${index + 1}`, en: `FIXTURE VIEW ${index + 1}` },
      title: `FIXTURE FILM ${index + 1}`,
      director: `Fixture Director ${index + 1}`,
      year: `${2000 + index}`,
      rationale: {
        fa: "دلیل انتخاب آزمایشی برای این فیلم.",
        en: "Fixture selection rationale for this film.",
      },
      poster: cycle(filmPosters, index),
    })),
    tracks: range(counts.tracks).map((index) => {
      const group = cycle(TRACK_GROUPS, index);
      return {
        id: `${slug}-track-${index + 1}`,
        title: `Fixture Track ${index + 1}`,
        artist: `Fixture Artist ${index + 1}`,
        groupId: group.id,
        groupTitle: { fa: group.fa, en: group.en },
        period: group.period,
        playlistRationale: {
          fa: "دلیل انتخاب آزمایشی برای این گروه.",
          en: "Fixture rationale for this playlist group.",
        },
        artwork: cycle(trackArtworks, index),
      };
    }),
    artPieces: range(counts.artPieces).map((index) => ({
      id: `${slug}-art-${index + 1}`,
      category: { fa: "دسته‌ی آزمایشی", en: "FIXTURE CATEGORY" },
      title: `FIXTURE ART PIECE ${index + 1}`,
      creator: `Fixture Creator ${index + 1}`,
      year: `${1970 + index}`,
      rationale: {
        fa: "دلیل انتخاب آزمایشی برای این قطعه.",
        en: "Fixture selection rationale for this piece.",
      },
      media: cycle(artMedia, index),
    })),
    footer: {
      statement: { fa: "جمله‌ی پایانی آزمایشی.", en: "FIXTURE CLOSING STATEMENT." },
      cta: { label: { fa: "بدون اقدام", en: "NO ACTION" }, href: "", enabled: false },
      links: [{ label: "FIXTURE LINK — NO DESTINATION", href: "", enabled: false }],
    },
  };

  return weeklyLensSchema.parse(raw);
}

/**
 * Counts deliberately unlike W04's (2 menu / 3 films / 11 tracks / 4 art / 3 hero messages):
 * 5 menu items, 4 tracks, 6 art pieces, 2 hero messages. Films stay at the schema's fixed 3.
 */
export const variableCountFixtureLens: WeeklyLens = buildFixtureLens({
  slug: "variable-count-fixture",
  week: "W98",
  titleFa: "لنز آزمایشی شمارش متغیر",
  titleEn: "VARIABLE COUNT FIXTURE",
  counts: { heroMessages: 2, menuItems: 5, tracks: 4, artPieces: 6 },
});

/**
 * The schema's minimum allowed content: 2 menu items, 3 films, 3 tracks, 1 art piece,
 * 1 hero message. Brief §11: "A scene gracefully handles the minimum allowed content count."
 */
export const minimumCountsFixtureLens: WeeklyLens = buildFixtureLens({
  slug: "minimum-counts-fixture",
  week: "W99",
  titleFa: "لنز آزمایشی کمینه",
  titleEn: "MINIMUM COUNTS FIXTURE",
  counts: { heroMessages: 1, menuItems: 2, tracks: 3, artPieces: 1 },
});

/**
 * A four-card menu deck, for looking at the deck's conveyor with more than W04's two items.
 *
 * W04 ships two menu items and the mock pack ships exactly two menu images, so a four-card deck
 * cannot be seen on the real page without inventing DROP menu content — which the content rules
 * forbid. This fixture recycles the two real images across four items instead, so the deck's
 * pacing and hand-off can be judged at a realistic count while `publishedLenses` stays honest.
 *
 * Every other count is at or near its minimum: the deck is the only thing this fixture is for,
 * and a short page is a quicker scroll to it.
 */
export const menuDeckFixtureLens: WeeklyLens = buildFixtureLens({
  slug: "four-card-menu-fixture",
  week: "W97",
  titleFa: "لنز آزمایشی چهار کارت",
  titleEn: "FOUR CARD MENU FIXTURE",
  counts: { heroMessages: 1, menuItems: 4, tracks: 3, artPieces: 1 },
});

/** Every fixture, for tests that assert the same property across every count shape. */
export const countFixtureLenses: readonly WeeklyLens[] = [
  variableCountFixtureLens,
  minimumCountsFixtureLens,
  menuDeckFixtureLens,
];
