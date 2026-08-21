# DROP W04 Mock Content Pack

Use this pack until DROP Studio OS can publish real Weekly Lens data and approved media.

It is intentionally shaped like production content: Claude can build every scene, validate the object at runtime, and later replace content without rewriting motion components.

## What is included

- `src/content/drop-weekly-lens.schema.ts` — Zod schema, inferred TypeScript types, and a production-media guard.
- `src/content/lenses/beautiful-imperfection.mock.json` — complete bilingual W04 content.
- `src/content/lenses/beautiful-imperfection.ts` — validated export for the application.
- `media-manifest.csv` — one row for each of the 20 temporary media assets.
- `REPLACE_BEFORE_LAUNCH.md` — final-media and final-link checklist.
- `MOCK_ASSET_GENERATION_PROMPTS.md` — provenance and repeatable direction for the original temporary visuals.
- `../05-mock-assets/` — 2 menu images, 3 film concept posters, 11 track artworks, and 4 Art Piece concept images.

## Exact setup for Claude

1. Copy `04-mock-content/src/content/` into the application `src/content/` directory.
2. Copy the contents of `05-mock-assets/` into:

   ```text
   public/media/lenses/beautiful-imperfection/
   ```

3. Install `zod` if it is not already present.
4. Import the validated content:

   ```ts
   import { beautifulImperfectionLens } from "@/content/lenses/beautiful-imperfection";
   ```

5. Render all text, counts, image paths, alt text, and metadata from the content object. Do not retype mock content inside scene components.
6. Keep `contentMode: "development-mock"` visible in non-production diagnostics.
7. In production builds, call `assertProductionMedia(beautifulImperfectionLens)` or an equivalent CI check. The current pack must intentionally fail that guard until assets are reviewed or replaced.

## Scene coverage

| Scene | Data/media supplied |
|---|---|
| Loader | Uses the supplied DROP brand references and procedural 3D material; no raster mock required |
| Hero thesis | Three Persian/English messages plus thesis, tension, balance, and anti-definition |
| Menu cards | Two complete cards with local portrait product images |
| Grid statement | Persian/English statement |
| Films | Three recommendations, rationales, metadata, alt text, and local 2:3 concept posters |
| Tracks | Eleven tracks across morning, afternoon, and night; local square disc artwork for each |
| Art Pieces | Four entries with local 4:3 concept media |
| Footer | Statement plus disabled placeholders for CTA, Instagram, map, contact, and legal |

## Important media rule

All 20 images are original temporary development assets created for this build pack. They do not copy official film posters, album covers, museum photography, or partner product photography. They are safe placeholders for layout and motion development, but every asset is set to:

```json
{
  "rightsStatus": "development-mock",
  "productionAllowed": false
}
```

Do not silently change these flags. Replace or explicitly approve each item before launch.

## Data behavior Claude must preserve

- Persian is the default editorial language; English fields remain available.
- Array lengths control visible counts and scroll budgets.
- Missing optional fields must not leave blank UI.
- No scene component may assume a hardcoded asset count.
- Track art is mapped onto the circular disc inside the jewel case; it is not a square card placed above the disc.
- Film images are concept posters. Do not add title typography onto the images; the title remains live HTML.
- Art Piece concept images must not be presented as photographs of the referenced original works.
- Disabled footer links stay non-interactive until final destinations are supplied.

## Fast acceptance test

The build is correctly connected when it renders:

- 2 menu cards;
- 3 sequential films;
- 11 track slides;
- 4 Art Piece rows;
- no broken images;
- no hardcoded repeated media;
- a deliberate production failure or warning while temporary assets remain.
