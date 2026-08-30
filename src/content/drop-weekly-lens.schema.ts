import { z } from "zod";

export const localizedTextSchema = z.object({
  fa: z.string().min(1),
  en: z.string().min(1).optional(),
});

export const mediaAssetSchema = z.object({
  src: z.string().startsWith("/media/"),
  alt: localizedTextSchema,
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  rightsStatus: z.enum([
    "approved",
    "rights-pending",
    "replace-with-final",
    "original-drop",
    "development-mock",
  ]),
  productionAllowed: z.boolean(),
  credit: z.string().optional(),
  sourceUrl: z.string().url().optional(),
  replacementNote: z.string().optional(),
});

export const menuItemSchema = z.object({
  id: z.string().min(1),
  name: localizedTextSchema,
  maker: z.string().min(1),
  category: localizedTextSchema.optional(),
  rationale: localizedTextSchema,
  image: mediaAssetSchema,
});

export const filmRecommendationSchema = z.object({
  id: z.string().min(1),
  viewLabel: localizedTextSchema,
  title: z.string().min(1),
  director: z.string().min(1),
  year: z.string().min(1),
  genres: z.array(z.string()).optional(),
  rationale: localizedTextSchema,
  poster: mediaAssetSchema,
  sourceUrl: z.string().url().optional(),
});

export const trackRecommendationSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  artist: z.string().min(1),
  groupId: z.string().min(1),
  groupTitle: localizedTextSchema,
  period: z.enum(["morning", "afternoon", "night"]),
  playlistRationale: localizedTextSchema,
  artwork: mediaAssetSchema,
  sourceUrl: z.string().url().optional(),
});

export const artPieceSchema = z.object({
  id: z.string().min(1),
  category: localizedTextSchema,
  title: z.string().min(1),
  creator: z.string().optional(),
  year: z.string().optional(),
  duration: z.string().optional(),
  label: localizedTextSchema.optional(),
  rationale: localizedTextSchema,
  media: mediaAssetSchema,
  sourceUrl: z.string().url().optional(),
});

export const footerLinkSchema = z.object({
  label: z.string().min(1),
  href: z.string(),
  enabled: z.boolean(),
});

export const weeklyLensSchema = z.object({
  schemaVersion: z.literal("1.0"),
  contentMode: z.literal("development-mock"),
  publicationStatus: z.enum(["draft", "review", "approved", "published"]),
  slug: z.string().min(1),
  week: z.string().regex(/^W\d{2}$/),
  title: localizedTextSchema,
  thesis: localizedTextSchema,
  tension: localizedTextSchema,
  balance: localizedTextSchema,
  notThis: localizedTextSchema,
  heroMessages: z.array(localizedTextSchema).min(1),
  gridStatement: localizedTextSchema,
  sectionLabels: z.object({
    menu: localizedTextSchema,
    films: localizedTextSchema,
    tracks: localizedTextSchema,
    artPieces: localizedTextSchema,
  }),
  menuItems: z.array(menuItemSchema).min(2).max(6),
  films: z.array(filmRecommendationSchema).length(3),
  tracks: z.array(trackRecommendationSchema).min(3),
  artPieces: z.array(artPieceSchema).min(1),
  footer: z.object({
    statement: localizedTextSchema,
    cta: z
      .object({
        label: localizedTextSchema,
        href: z.string(),
        enabled: z.boolean(),
      })
      .optional(),
    links: z.array(footerLinkSchema),
  }),
});

export type WeeklyLens = z.infer<typeof weeklyLensSchema>;
export type MediaAsset = z.infer<typeof mediaAssetSchema>;

export function assertProductionMedia(lens: WeeklyLens) {
  const media = [
    ...lens.menuItems.map((item) => item.image),
    ...lens.films.map((item) => item.poster),
    ...lens.tracks.map((item) => item.artwork),
    ...lens.artPieces.map((item) => item.media),
  ];

  const blocked = media.filter(
    (asset) => !asset.productionAllowed || asset.rightsStatus === "development-mock",
  );

  if (blocked.length > 0) {
    throw new Error(
      `Production build blocked: ${blocked.length} temporary or unapproved media asset(s) remain.`,
    );
  }
}
