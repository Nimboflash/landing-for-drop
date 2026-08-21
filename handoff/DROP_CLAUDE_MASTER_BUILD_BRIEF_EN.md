# DROP Immersive Weekly Lens — Claude Master Build Brief

## Final Product, Design, Motion, Content, and Engineering Build Specification

**Version:** 1.2  
**Date:** 21 August 2026  
**Status:** Approved build brief  
**Primary implementer:** Claude / senior creative developer  
**Primary language at launch:** Persian, with bilingual data support  

---

## 0. Start Here: Claude Build Instruction

You are building the production-ready first version of the immersive DROP Weekly Lens website. Treat this document as the source of truth.

Build the experience as a real responsive website, not as a static visual mockup. The site must preserve the content model of the existing DROP Weekly Lens MVP while replacing its presentation with a continuous, scroll-driven, cinematic experience.

Before coding:

1. Read this entire specification.
2. Inspect the supplied DROP brand book and final logo assets.
3. Create a short implementation plan and component map.
4. Scaffold the data model before building visual scenes.
5. Build and validate one scene at a time in the exact order specified below.
6. Use local placeholders when final/licensed media is unavailable. Never hotlink or silently scrape protected artwork, film posters, product photography, or album artwork.
7. Do not stop at a static approximation. The loader, pinned text, stacked cards, pixel transitions, film sequence, CD carousel, art-piece reveals, shaders, and footer light effect are core requirements.
8. Until DROP Studio OS is connected, use the supplied validated W04 mock dataset and all local mock assets. Do not replace them with remote URLs, repeated generic placeholders, or scraped media.

Do not copy source code, branded assets, or copywriting from the reference websites. They are behavioral and motion references only. Recreate the interaction intent using DROP's own brand, content, geometry, colors, and assets.

---

## 0.1 Files to Attach to Claude

Send this Markdown file as the primary instruction and attach the files below in the same Claude Project or conversation. The packaged filenames are already normalized. Claude must treat the Markdown as the source of truth and the attachments as supporting evidence.

### Required attachments

| Priority | Packaged filename | What Claude must use it for |
|---:|---|---|
| 1 | `DROP_CLAUDE_MASTER_BUILD_BRIEF_EN.md` | Complete product, design, motion, content, engineering, QA, and acceptance specification |
| 2 | `01-brand/drop-brand-book.pdf` | Brand geometry, palette, typography, modular rules, and overall identity |
| 3 | `01-brand/drop-final-storefront-logo.jpg` | Confirmation of the approved final DROP logo in real-world application |
| 4 | `01-brand/drop-final-wordmark-reference.png` | Exact D/R/O/P module proportions for reconstructing the logo as vector geometry |
| 5 | `02-motion/opacity-loader-material-reference.png` | Near-black glossy material, hollow-square form, and loader surface direction |
| 6 | `02-motion/opacity-pinned-hero-reference.png` | Pinned headline composition and sparse header behavior |
| 7 | `02-motion/lusion-card-motion-reference.mov` | Menu-card stack, fan, arrival, stagger, and flip choreography |
| 8 | `02-motion/pixel-transition-reference.mov` | Scroll-linked, reversible pixel replacement between scenes |
| 9 | `02-motion/tracks-carousel-reference.png` | Transparent jewel-case/disc carousel composition |
| 10 | `02-motion/art-pieces-motion-reference.mov` | Art Pieces editorial rhythm, reveal, masking, and parallax behavior |
| 11 | `02-motion/footer-light-horizon-reference.png` | Footer scale, outline word treatment, and prismatic moving horizon |
| 12 | `04-mock-content/README.md` | Exact setup and temporary-content rules |
| 13 | `04-mock-content/src/content/drop-weekly-lens.schema.ts` | Runtime validation and production-media guard |
| 14 | `04-mock-content/src/content/lenses/beautiful-imperfection.mock.json` | Complete bilingual W04 data for every scene |
| 15 | `05-mock-assets/` | Twenty local development images covering menu, films, tracks, and Art Pieces |

### Supporting layout references

| Packaged filename | What it clarifies |
|---|---|
| `03-layout/menu-card-back-reference.png` | Sharp card format and centered DROP identity on the reverse |
| `03-layout/menu-card-front-reference.png` | Product image/name/maker hierarchy; exclude price, buy, cart, and like UI |
| `03-layout/grid-statement-reference.png` | Dark-green grid atmosphere with one centered statement and no extra controls |
| `03-layout/film-layout-reference.png` | One recommendation at a time with text left and poster/media right |

### Development mock-content attachments

Use these files immediately so the complete page can be built before the DROP Studio OS pipeline exists:

| Packaged path | Purpose |
|---|---|
| `04-mock-content/README.md` | Copy/install instructions and scene-coverage map |
| `04-mock-content/src/content/drop-weekly-lens.schema.ts` | Zod schema and production guard |
| `04-mock-content/src/content/lenses/beautiful-imperfection.mock.json` | Single source of truth for W04 mock content |
| `04-mock-content/src/content/lenses/beautiful-imperfection.ts` | Validated TypeScript export |
| `04-mock-content/media-manifest.csv` | Exact public path, dimensions, status, and replacement instruction for each image |
| `04-mock-content/REPLACE_BEFORE_LAUNCH.md` | Launch-clearance checklist |
| `04-mock-content/MOCK_ASSET_GENERATION_PROMPTS.md` | Visual provenance and repeatable art direction |
| `05-mock-assets/menu/` | Two portrait menu images |
| `05-mock-assets/films/` | Three original 2:3 concept posters |
| `05-mock-assets/tracks/` | Eleven original square disc artworks |
| `05-mock-assets/art/` | Four original 4:3 concept images |

These images are deliberately marked `development-mock` and `productionAllowed: false`. Build with them now. Do not remove the production guard; replacement or explicit approval happens later through data and asset updates.

### External URLs Claude should inspect

- Existing DROP content MVP: `https://drop-weekly-lens.mafi-kcafe.chatgpt.site/`
- Current lens seed: `https://drop-weekly-lens.mafi-kcafe.chatgpt.site/lens/beautiful-imperfection`
- Interaction reference: `https://opacity.com/`
- Card motion reference: `https://lusion.co/`
- Editorial/grid reference: `https://www.zero.university/`
- Pixel-transition reference: `https://www.runrobrun.com/`
- Track-carousel reference: `https://serhatdurmus.com/`
- Art Pieces reference: `https://www.x2ycreative.com/`
- MetalForge Wavy Dots preset: `https://metalforge.xyz/editor#effect=dots&style=wavy&speed=1&brightness=1&tint=%23FFFFFF&background=%23000000&dotSize=1&gridDensity=1&patternScale=1&vignette=1&horizon=-0.45&amplitude=1&depthFade=1`
- MetalForge Monochrome Mesh preset: use the full URL recorded in Section 13 of this specification.

### Attachment rules

1. Claude must inspect the three DROP brand files before generating components or shaders.
2. Claude must inspect each motion clip before implementing its corresponding scene.
3. Reference screenshots and videos define composition and motion intent only. Do not ship them as production content.
4. Do not copy reference-site code, logos, text, posters, album covers, or copyrighted artwork.
5. If Claude cannot access an external site, the attached references plus this specification remain sufficient to continue.
6. When an instruction conflicts with a reference, this Markdown wins.
7. Mock content is authoritative for development rendering, but it does not imply publication clearance.

### Suggested first message to Claude

> Build the production-ready DROP Immersive Weekly Lens website from the attached `DROP_CLAUDE_MASTER_BUILD_BRIEF_EN.md`. Read the entire brief and inspect all required attachments before coding. First return a concise implementation plan, dependency list, component/data architecture, and scene-by-scene milestone plan. Then implement the site in the specified order. Treat the brief as the source of truth, keep the project data-driven, and do not replace required motion with static approximations.

---

## 1. Executive Summary

DROP is a food concept store and cultural point of view. Each Weekly Lens begins with a clear tension and finds its balance through taste, sound, film, art, architecture, photography, and cultural notes.

The new website should feel like one uninterrupted editorial journey. It combines:

- the immersive loading and pinned typography behavior of Opacity;
- the stacked, fanned, flip-reveal card behavior seen in Lusion;
- the spare grid statement and sequential editorial cards seen in Zero University;
- the scroll-reversible pixel transition seen in Run Rob Run;
- the transparent jewel-case music carousel seen in Serhat Durmus;
- the vertical editorial Art Pieces system seen in X2Y Creative;
- the content hierarchy and real recommendations from the existing DROP Weekly Lens MVP;
- the final DROP modular identity from the supplied brand book.

The homepage in V1 renders the current Weekly Lens as an immersive long-form page. The implementation must be data-driven so future lenses can replace content without rebuilding motion or page structure.

### Core outcome

A user enters through the animated DROP logo, reads the weekly concept through scroll-driven statements, discovers menu items through flipping cards, crosses a pixelated scene transition, explores three films, crosses a second pixel transition, browses music inside transparent discs, reviews related cultural Art Pieces, and reaches a final DROP footer with a living prismatic light horizon.

---

## 2. Product Scope

### In scope for V1

- One production-quality immersive Weekly Lens page.
- Root route `/` renders the current lens.
- Reusable dynamic route `/lens/[slug]` using the same scene components.
- Persian-first content with English fields in the data schema.
- Modular content for menu, films, tracks, Art Pieces, statements, and footer.
- Loader, scroll choreography, 3D card flips, reversible transitions, WebGL backgrounds, carousel interaction, responsive layouts, reduced-motion mode, and performance fallbacks.
- Seed content for W04: Beautiful Imperfection.
- Local asset placeholders and explicit media-rights statuses.

### Not required for the first build

- Checkout, ordering, payment, cart, price, buy, like, or favorite actions.
- User accounts.
- A full CMS or admin panel.
- Audio autoplay or an embedded streaming player.
- A complete redesigned archive page.
- Rebuilding all four historic lenses with final production media.
- Copying reference-site source code or assets.

### Future-ready, but not a launch blocker

- Archive route with W01-W04.
- Language switcher outside the top-right header area.
- CMS integration.
- Share cards and Open Graph image generation.
- Additional lens modules such as books or events.

---

## 3. Source of Truth and Asset Priority

When two references conflict, use this order:

1. This build specification.
2. The supplied final DROP logo photograph/crop.
3. The final modular identity pages in the DROP brand book.
4. The existing DROP Weekly Lens content.
5. User-supplied motion videos and screenshots.
6. External reference websites.

### Supplied source assets

Rename these clearly inside the project before use:

| Current file | Suggested project name | Purpose |
|---|---|---|
| `e333f246-c743-44d0-9053-593a48a45738.pdf` | `drop-brand-book.pdf` | Brand geometry, palette, typography, and applications |
| `e11bbc4f-43b7-47ff-bece-732ba965800e.jpg` | `drop-final-storefront-logo.jpg` | Final logo/application confirmation |
| `0a703ade-91ae-4333-b9f4-b17c9309df98.png` | `drop-final-wordmark-reference.png` | Exact D/R/O/P module reference |
| `aad1c414-38db-408c-9e24-dcd827e9347a.png` | `opacity-loader-material-reference.png` | Loader material and hollow-form reference |
| `c049fa86-8c3b-4f37-b8a8-75dea314d921.png` | `opacity-pinned-hero-reference.png` | Pinned hero layout reference |
| `fe3da8e3-7f74-4fd5-aeb9-5a0ae5b3d2b7.mov` | `lusion-card-motion-reference.mov` | Stack, fan, stagger, and flip timing |
| `6a3c3554-13a0-4fd4-a3d8-9a8b664f23f1.mov` | `pixel-transition-reference.mov` | Scroll-reversible pixel transition |
| `8c5ac6c2-d7f3-4c1f-bf11-41c734dea530.png` | `tracks-carousel-reference.png` | Jewel-case carousel composition |
| `a05b407e-75be-48fd-a3b5-04f851d573d7.mov` | `art-pieces-motion-reference.mov` | Editorial Art Pieces layout and reveal |
| `50679b2c-b1c9-4e88-aa22-b3e6aa6d7412.png` | `footer-light-horizon-reference.png` | Final outline word and light horizon |
| `04f5e2b1-d3f0-4103-97fa-4e8ad6ed4780.png` | `menu-card-back-reference.png` | Sharp card format and reverse-side identity reference |
| `4c27516e-51fc-46a6-a8b4-e98cc27abf74.png` | `menu-card-front-reference.png` | Product-card image and text hierarchy reference |
| `5eb60497-09fa-4907-89e3-1850aa692d25.png` | `grid-statement-reference.png` | Dark-green grid and centered statement composition |
| `1afb0820-b278-48c4-8ef5-06e72842a096.png` | `film-layout-reference.png` | Recommendation layout with copy left and media right |

---

## 4. Brand System

### Brand character

The website must feel:

- raw but controlled;
- geometric but alive;
- minimal but not sterile;
- bold, modular, energetic, and urban;
- editorial rather than commercial;
- precise enough to feel designed, imperfect enough to feel human.

Useful brand principles from the book:

- **Bold simplicity:** strong geometry, clarity, and impact.
- **Motion and energy:** the O carries rhythm and movement.
- **Imperfection as identity:** irregularity follows competence; it never excuses low quality.
- **Balance and structure:** solid letters balance the dynamic circular form.
- **One shape, endless possibilities.**

### Logo geometry

Do not trace the storefront photograph as a bitmap logo. Reconstruct the final logo as clean SVG/procedural geometry.

- The logo is modular and based on a unit `X`.
- Each core module is `2X` by `2X`.
- Module spacing is `X` in the construction system; visually tune the responsive wordmark to match the final supplied reference.
- D, R, and P live in sharp square modules.
- O is a circular ring module.
- O outer diameter is `2X`.
- O inner diameter is `X`.
- The secondary row uses the decorative teeth/line mark, vertical bar in circle, diagonal bar, and chevron.
- All corners in the final website logo and content-card system are sharp unless the physical form explicitly requires a circle.

Create these reusable components:

- `DropWordmark`
- `DropPrimaryLogo`
- `DropSymbolRow`
- `DropO` with controllable aperture scale
- `DropLogoMaterial3D` for the loader

### Color tokens

The final site should prioritize black and off-white. Accent colors appear as light, transition, and atmospheric energy, not as large generic UI fills.

```css
:root {
  --drop-black: #000000;
  --drop-ink: #111111;
  --drop-white: #fffffe;
  --drop-off-white: #f2f2f2;
  --drop-gray: #838383;
  --drop-orange: #ff5a00;
  --drop-purple: #480082;
  --drop-grid-green: #102b19;
  --drop-grid-line: #245236;
}
```

The brand book contains exploratory palette variations. For V1, use black/off-white as the base and orange/purple sparingly for atmospheric glow, pixel energy, and prismatic light.

### Typography

- Latin display and UI: Montserrat ExtraBold/Bold and Montserrat Regular.
- Persian: self-host Vazirmatn until a final licensed Persian brand typeface is approved.
- Large display type should be tight, confident, and highly legible.
- Body copy must not use condensed display faces.
- Do not imitate Opacity's exact typeface.

Recommended responsive scale:

```css
--display-xl: clamp(3.3rem, 7.2vw, 8.5rem);
--display-lg: clamp(2.5rem, 5.4vw, 6.4rem);
--title-lg: clamp(2rem, 3.8vw, 4.5rem);
--title-md: clamp(1.5rem, 2.4vw, 2.8rem);
--body-lg: clamp(1.1rem, 1.35vw, 1.45rem);
--body: clamp(0.98rem, 1vw, 1.12rem);
--label: clamp(0.68rem, 0.72vw, 0.82rem);
```

### Shape language

- No generic rounded SaaS cards.
- Menu cards: `border-radius: 0`.
- Film posters: preserve natural poster rectangle; any layered paper edges should remain subtle.
- Art media: square or source-aspect ratio with sharp edges.
- Pills are allowed only for compact metadata when essential; do not turn the visual system into pill-based UI.

---

## 5. Information Architecture and Content Model

The existing DROP MVP defines the content hierarchy. Preserve it even though the visual presentation changes.

### Archive-level content

- W01 / Controlled Tension
- W02 / Soft Machinery
- W03 / Heat in the Shade
- W04 / Beautiful Imperfection

Each lens has a permanent slug and should remain independently shareable.

### Lens-level content

1. Lens identity: week, Persian title, English title, thesis.
2. Tension: what is being held in balance.
3. Balance point.
4. What the lens is not.
5. Taste edit: real menu items and selection rationale.
6. Sound edit: playlists/time-of-day groups and tracks.
7. Film edit: normally three films/series with a progression of views.
8. Field notes / Art Pieces: architecture, art, photography, and a short cultural idea.
9. Closing brand statement and footer.

### V1 page strategy

- `/` renders the configured `currentLensSlug`.
- `/lens/[slug]` renders the same immersive template.
- Seed W04 as the complete production example.
- Keep content outside scene components.
- Do not hardcode titles, counts, image URLs, years, artists, or descriptions inside animation code.

---

## 6. Master Experience Sequence

The experience must follow this order without extra sections:

1. DROP material loader.
2. O portal transition.
3. Pinned scroll typography / lens thesis.
4. Stacked menu cards.
5. Dark-green grid statement.
6. Pixel transition A.
7. Wavy Dots film/series sequence.
8. Pixel transition B while films fade.
9. Monochrome Mesh tracks carousel.
10. Art Pieces on the same Mesh background.
11. Mesh fade to pure black.
12. DROP outline footer with prismatic light horizon.

### High-level scroll budget

These values are starting points and should be tuned by feel after implementation:

| Scene | Approximate scroll length |
|---|---:|
| Loader | Time-based, 2.8-4.0 seconds |
| Pinned thesis | 320vh |
| Menu deck | 260-320vh |
| Grid statement | 160-200vh |
| Pixel transition A | 140-180vh |
| Three films | 420-500vh |
| Pixel transition B | 150-190vh |
| Tracks | `max(340vh, trackCount * 55vh)` with a sensible cap |
| Art Pieces | 75-95vh per item |
| Footer | 160-220vh |

Do not treat these numbers as fixed if pacing feels rushed or empty. The acceptance criterion is intentional rhythm, not a specific page height.

---

## 7. Scene Specifications

### 7.1 DROP Material Loader

#### Visual

- Full viewport, off-white background.
- The centered English DROP logo replaces the Opacity loader mark.
- D, R, and P are modular square forms.
- O is a thick circular ring with a clear center aperture.
- The entire logo is made from one near-black, glossy, organic material inspired by the hollow-square reference.
- The material must move subtly: slow surface displacement, traveling highlights, slight refraction, and soft irregularity.
- The logo is not a flat image and not four unrelated CSS blocks.

#### Motion

1. Logo fades/materializes from near-black shadow.
2. Surface noise and specular highlights begin moving across all four modules.
3. The O aperture pulses between approximately `0.84` and `1.08` of its resting inner radius.
4. The pulse becomes the visual focus while D/R/P settle.
5. The O aperture expands rapidly but smoothly beyond the viewport.
6. The expanding inner void acts as a mask/portal revealing the first hero scene beneath it.
7. No hard cut or separate loading-screen fade is allowed.

#### Timing

- Total target: 3.2 seconds after critical assets are ready.
- Cap the loader at 4 seconds; never trap the user waiting for noncritical media.
- First hard visit plays the full version.
- Internal route navigation uses a short mask transition rather than replaying the entire loader.
- Reduced motion: static logo for 500-700ms, then a simple O-shaped crossfade.

#### Implementation

- Preferred: React Three Fiber + custom GLSL material.
- Geometry can be procedural/extruded; a GLB is not required.
- Use the O center as a screen-space mask for the portal transition.
- Keep the DOM page mounted beneath the loader to prevent a layout jump.

### 7.2 Pinned Lens Thesis

#### Layout

- Minimal off-white full-screen scene.
- Small final DROP logo at the top-left.
- No button, CTA, nav group, or `Join the waitlist` element at the top-right.
- Large centered text with generous negative space.
- A subtle atmospheric glow grows from the lower edge. Use DROP orange/purple energy rather than copying Opacity's blue exactly.

#### Default W04 message sequence

1. `زیبایی از «نقص» نمی‌آید.`
2. `اول مهارت و دوام؛ بعد تفاوت.`
3. `دقت در کار؛ جا برای ردِ دست و رفتار واقعیِ ماده.`

Optional small English lens label:

`W04 / BEAUTIFUL IMPERFECTION`

#### Motion

- The scene is pinned.
- Each message enters through line masks: `yPercent`, opacity, and a small blur resolving to sharp text.
- The outgoing message lifts and softens while the next replaces it.
- Avoid typewriter effects and random letter animation.
- Scroll direction must reverse the transitions cleanly.
- The bottom glow slowly expands and contracts with progress but never reduces text contrast.

### 7.3 Stacked Menu Cards

#### Entry choreography

1. The final thesis text leaves.
2. A compressed stack of menu cards rises from below the center.
3. The stack fans into small rotations and offsets.
4. Card backs are visible first.
5. Cards flip in 3D with a rapid stagger.
6. Each front reveals a real menu item.

#### Card back

- Pure/near black.
- Centered white English DROP primary logo.
- No additional copy.
- Sharp corners.

#### Card front

- One product image.
- Menu item name.
- Maker/partner name.
- Optional small category label.
- No description paragraph on the card.
- No price.
- No purchase button.
- No cart.
- No like/favorite icon.

#### W04 seed cards

1. `WEEKLY FRUIT TART` / `BY ÉCLAIR`
2. `MOCHI BITE BOX` / `BY MOCHIKI`

The component must support 2-6 items. Do not duplicate content merely to create a larger stack.

#### Motion details

- CSS 3D transforms are preferred for the cards.
- `perspective` on the deck, `transform-style: preserve-3d` on each card.
- Backface hidden.
- Initial fan angles may begin around `-8deg, -3deg, 3deg, 8deg` and adapt to count.
- Flip stagger target: 70-110ms.
- Add subtle post-flip pointer tilt on desktop only.
- Reverse scroll reconstructs the stack and returns it below the viewport.

### 7.4 Grid Statement

#### Visual

- Full-screen dark forest-green background.
- Quiet square grid across the entire viewport.
- Only one centered statement.
- No form, button, email field, arrows, handwriting, social icons, imagery, footer, or floating UI.

#### Default statement

`A PLACE WITH A POINT OF VIEW.`

#### Motion

- Scene rises into place after the menu deck.
- Statement reveals once through a clean mask or opacity/y transition.
- Scene pins briefly.
- Grid cells become the coordinate system for the next pixel transition.

### 7.5 Pixel Transition A: Grid to Films

This transition is scroll-driven and reversible.

- Do not use a simple wipe, blur, crossfade, or gradient dissolve.
- Pixel blocks enter from the bottom with an irregular stepped skyline.
- Pixel dimensions align with the existing background grid.
- Each cell changes state at a seeded threshold.
- The old grid remains visible until a cell is replaced.
- The centered statement fades while the replacement reaches approximately 20-55% progress.
- At completion, the Wavy Dots film background is fully active.
- Reverse scroll restores the exact prior grid state.

Implementation preference: a shared WebGL mosaic mask using a stable random seed and a bottom-weighted threshold field. A DOM grid is acceptable only if it maintains smooth performance.

### 7.6 Film and Series Recommendations

#### Background

Use the MetalForge-inspired Wavy Dots shader preset:

```ts
{
  effect: "dots",
  style: "wavy",
  speed: 1,
  brightness: 1,
  tint: "#FFFFFF",
  background: "#000000",
  dotSize: 1,
  gridDensity: 1,
  patternScale: 1,
  vignette: 1,
  horizon: -0.45,
  amplitude: 1,
  depthFade: 1
}
```

The effect is a reference preset. Rebuild it for web in GLSL; do not embed a MetalForge editor or use a recorded video.

#### Layout

- Pinned full-screen scene.
- Deliberate layout direction remains consistent even for Persian content:
  - left: film information;
  - right: poster stack/current poster.
- Text inside the left column may align right for Persian.
- Show one recommendation at a time.
- Usually three recommendations per lens.

#### Poster behavior

- Large vertical poster.
- Enters from lower-right with slight rotation and scale.
- May include 1-2 subtle paper layers behind the active poster.
- Current poster is crisp and dominant.
- Exiting poster moves upward/outward as the next arrives.
- Do not show three posters side-by-side as static cards.

#### Text behavior

- Category/view label.
- Film/series title.
- Director/creator.
- Year.
- Optional genres.
- Short selection rationale.
- Text updates in sync with the active poster.
- Do not add visible buy, like, price, favorite, or cart controls.
- If a source link is required, make the title/poster subtly clickable rather than adding a large CTA.

#### W04 films

1. **SHOWING UP** - Kelly Reichardt - 2023 - First View.
2. **PERFECT DAYS** - Wim Wenders - 2023 - Second View.
3. **PATERSON** - Jim Jarmusch - 2016 - Completing View.

Use the exact Persian selection rationales from the content seed in Section 10.

### 7.7 Pixel Transition B: Films to Music

The second transition begins as the third film completes.

Exact sequence:

1. Film 03 remains visible.
2. With continued scroll, the poster and left description begin fading.
3. A colored pixel mosaic starts replacing the Wavy Dots background.
4. The pixel field passes through restrained DROP orange/purple energy.
5. The colored pixels resolve into the Monochrome Mesh background.
6. At 100%, hold a short empty dark beat.
7. The Tracks title and jewel-case carousel enter.

Requirements:

- Film content must not disappear abruptly.
- Transition must reverse correctly.
- Pixel coordinates should remain consistent with Transition A.
- The new Mesh is not visible as a generic crossfade underneath the old scene; it is revealed through the cells.

### 7.8 Tracks Carousel

#### Background

Use the MetalForge-inspired animated Monochrome Mesh preset. Rebuild as a web shader.

```ts
{
  effect: "mesh",
  grid: 4,
  style: "mono",
  smooth: 1,
  background: "#000000",
  animate: 1,
  speed: 1,
  drift: 0.35,
  hue: 0,
  fixEdges: 1,
  filter: "none",
  fBlur: 8,
  fFade: 0.45,
  fAmount: 0.5,
  fSoft: 0.5,
  fBrightness: 0,
  fContrast: 1,
  fSaturation: 1,
  fGrain: 16,
  fAngle: 0,
  fScale: 5,
  fInset: 0.08,
  fRound: 0.45,
  fBevel: 0.3
}
```

Mesh 4x4 control colors:

```ts
[
  ["#141415", "#ABAEB5", "#6C6E75", "#2E3034"],
  ["#696B74", "#2B2C32", "#C8C9CD", "#828694"],
  ["#C5C7CC", "#83868E", "#44464E", "#E4E4E6"],
  ["#42444C", "#E1E2E4", "#9C9FAA", "#5E6069"]
]
```

#### Visual system

- Large `TRACKS` heading.
- Transparent CD jewel cases.
- The active item is centered, largest, brightest, and closest.
- Previous/next items appear smaller and dimmer on both sides.
- Show up to five positions in the cover-flow field when the viewport allows.
- The song artwork is clipped/mapped onto the circular disc inside the clear case.
- The transparent case has restrained reflections, highlights, depth, and micro-motion.
- Under the active case: song title first, artist second, optional time-of-day group label third.

#### Interaction

- Vertical scroll advances the pinned carousel.
- Drag and swipe also change the active item.
- Left/right arrow controls are available and keyboard accessible.
- Text and cover position change in sync.
- The active slide should snap cleanly without feeling like a generic component library carousel.
- No audio autoplay.
- Optional click opens the configured external track search/source in a new tab.

#### Data behavior

- Item count is fully data-driven.
- Scroll length responds to item count.
- If artwork is missing, use a clearly branded DROP placeholder texture, not a broken image.
- All images must be local and rights-cleared before launch.

### 7.9 Art Pieces / Field Notes

#### Background continuity

- The Monochrome Mesh continues from Tracks without restarting or cutting.
- Tracks content fades/exits, but the background remains alive.
- Mesh movement may slow and darken slightly for reading comfort.

#### Structure

- Section heading: `ART PIECES / FIELD NOTES` with data-driven count.
- Vertical editorial sequence inspired by the supplied X2Y motion reference.
- Each item has:
  - index;
  - category;
  - title;
  - creator/artist/architect;
  - year;
  - short selection rationale;
  - image or muted loop video on the right.
- Thin horizontal divider between items.
- Sharp media edges.
- No rounded service cards.

#### Motion

- Text enters through line/clip masks.
- Media enters through a vertical crop reveal with mild parallax.
- Title and media move at slightly different speeds.
- The active row has clear visual priority while adjacent rows can partially enter/leave.
- Reverse scroll reconstructs the previous state.
- Experimental glitch may be used only as a restrained image treatment; readability remains primary.

#### W04 items

1. Brion Memorial - Carlo Scarpa - Architecture - 1970-78.
2. Untitled (S.270) - Ruth Asawa - Art - 1955 / 1957-58.
3. Untitled, from Illuminance - Rinko Kawauchi - Photography - 2011.
4. The Pratfall Effect - Social Psychology - 3 min read - custom DROP explanatory artwork.

### 7.10 Final Footer

#### Entry

- The Mesh gradually loses contrast and fades to pure black after the last Art Piece.
- The footer is not a separate white card or generic site footer.

#### Visual

- Very large `DROP` word across the lower half.
- Use the exact DROP wordmark character, rendered as a subtle outline rather than solid fill.
- Outline is thin and dark: visible before the light arrives but never high-contrast.
- A prismatic luminous horizon crosses the letters.
- The light has a bright white core, blue/cyan edge, and restrained orange/purple spectral fringes.
- It curves and drifts like a living horizon or light refraction.
- The line briefly illuminates the outline sections it passes.

#### Motion and interaction

- The light is a real-time WebGL/GLSL effect, not a screenshot, GIF, or pre-rendered video.
- Scroll controls the main reveal and vertical drift.
- Pointer movement may add subtle local distortion on desktop.
- The effect remains alive without pointer input.
- Reduced-motion mode uses a static blurred gradient ribbon and a simple outline reveal.

#### Footer content

- Default closing line: `A PLACE WITH A POINT OF VIEW.`
- A central CTA is configurable but disabled until final CTA copy/action is supplied.
- Bottom metadata slots: Instagram, location, contact, copyright, and legal.
- Do not invent live destinations. Use clearly named placeholders in the content file.
- Do not place a waitlist/demo button copied from references.

---

## 8. Persistent Header and Navigation Rules

- Loader: no header.
- From hero onward: small final DROP logo fixed at top-left.
- Top-right remains empty in V1.
- No `Join the waitlist` button.
- No conventional full nav over the cinematic scenes.
- Logo color adapts between black and white depending on scene contrast.
- Logo may hide briefly during the largest footer word reveal.
- Language support remains in data/routes; do not add a top-right language toggle without approval.
- Header must not intercept scroll or cover primary content on mobile.

---

## 9. Motion System and State Architecture

### Do not build one giant timeline

Create isolated scenes with a shared page-level state machine:

```ts
type SceneId =
  | "loader"
  | "thesis"
  | "menu"
  | "gridStatement"
  | "pixelA"
  | "films"
  | "pixelB"
  | "tracks"
  | "artPieces"
  | "footer";
```

Each scene owns:

- its section ref;
- its scroll trigger/timeline;
- progress-derived visual state;
- enter/leave cleanup;
- reduced-motion behavior;
- mobile behavior.

### Scroll requirements

- Use scrubbed progress for primary transitions.
- Reversing the scroll must reverse the animation, not jump to a reset state.
- No scroll-jacking that ignores the user's wheel/touch momentum.
- Pin only when the scene benefits from it.
- Recalculate after fonts and critical assets load.
- Kill timelines/triggers on unmount or route change.

### Motion language

- Primary easing: smooth, weighted, cinematic.
- Use crisp stagger for card flips.
- Use masks/clip reveals for editorial text.
- Use scale and perspective for physical media.
- Use opacity only as support, never as the sole transition language.
- Avoid bouncy app-like springs unless used for small tactile controls.

---

## 10. W04 Seed Content: Beautiful Imperfection

The following is the launch seed. Keep all strings editable.

### Lens identity

```ts
{
  week: "W04",
  titleFa: "زیبایی در کامل نبودن",
  titleEn: "BEAUTIFUL IMPERFECTION",
  thesisFa: "زیبایی از «نقص» نمی‌آید؛ از مهارتی می‌آید که تفاوت‌های کوچکِ دست، ماده و زمان را پاک نمی‌کند.",
  tensionFa: "کیفیت باید هر بار قابل‌اعتماد باشد؛ نتیجهٔ دست‌ساز لازم نیست هر بار عیناً تکرار شود.",
  balanceFa: "دقت در کار؛ جا برای ردِ دست و رفتار واقعیِ ماده.",
  notThisFa: "این یک نسخهٔ آماده از کلیشهٔ وابی‌سابی نیست و بی‌دقتی را زیبا جا نمی‌زند؛ اول مهارت و دوام، بعد تفاوت."
}
```

### Menu items

#### Weekly Fruit Tart

- Maker: Éclair.
- Category: Taste / Sweet.
- Rationale: `پایه و روش ثابت‌اند، اما اندازه و فرم میوه‌ها هر بار کمی فرق می‌کند. مهارت، تفاوت طبیعی را حذف نمی‌کند؛ به آن نظم می‌دهد.`
- Asset status: replace AI sample with final Éclair product photography.

#### Mochi Bite Box

- Maker: Mochiki.
- Category: Taste / Sweet.
- Rationale: `قطعه‌ها یک اندازه و یک منطق دارند، اما لازم نیست مثل خروجی قالب کاملاً همسان باشند. این تفاوت کوچک، انتخاب را انسانی نگه می‌دارد.`
- Asset status: replace direction image with final approved product photography.

### Track groups

#### Morning / Small Light

- Julie Byrne - Natural Blue.
- Jessica Pratt - This Time Around.
- Ichiko Aoba - Porcelain.
- Ryuichi Sakamoto - andata.

#### Afternoon / Breath & Texture

- Adrianne Lenker - anything.
- Sam Amidon - Wild Bill Jones.
- Nils Frahm - Ambre.

#### Night / Useful Silence

- Nala Sinephro - Space 1.
- Sarah Davachi - Magdalena.
- Arvo Pärt - Für Alina.
- Midori Takada - Mr. Henri Rousseau's Dream.

The carousel displays individual tracks. `groupTitle`, `period`, and `playlistRationale` remain available as small contextual fields.

### Films

#### 01 / First View / Showing Up

- Director: Kelly Reichardt.
- Year: 2023.
- Rationale: `ساختن وسط مزاحمت، کمبود وقت و کارهای ناتمام ادامه پیدا می‌کند. زیبایی اینجا نتیجهٔ مهارت و کار است، نه ظاهرِ نقص؛ روشن‌ترین مسیر ورود به لنز.`

#### 02 / Second View / Perfect Days

- Director: Wim Wenders.
- Year: 2023.
- Rationale: `روال روزانه دقیق و قابل‌اعتماد است، اما نور، موسیقی و برخوردها هر روز کمی فرق می‌کنند. نگاه دوم نشان می‌دهد تکرارِ خوب لازم نیست زندگی را یکسان کند.`

#### 03 / Completing View / Paterson

- Director: Jim Jarmusch.
- Year: 2016.
- Rationale: `شعرها یک‌باره کامل نمی‌شوند؛ از مشاهده، یادداشت و بازنویسی ساخته می‌شوند. این نگاه تکمیلی تفاوت میان الهامِ خام و مهارتی را روشن می‌کند که به آن فرم می‌دهد.`

### Art Pieces / Field Notes

#### Brion Memorial

- Creator: Carlo Scarpa.
- Category: Architecture.
- Year: 1970-78.
- Rationale: `درزها و لایه‌ها پنهان نشده‌اند؛ دقت ساخت در کنار اثر زمان دیده می‌شود.`
- Rights: image and architecture rights require production review.

#### Untitled (S.270)

- Creator: Ruth Asawa.
- Category: Art.
- Year: 1955 / 1957-58.
- Rationale: `هزاران حلقهٔ دستی یک فرم دقیق می‌سازند؛ تفاوت‌های کوچک مهارت را نشان می‌دهند، نه بی‌دقتی را.`
- Rights: rights pending.

#### Untitled, from Illuminance

- Creator: Rinko Kawauchi.
- Category: Photography.
- Year: 2011.
- Rationale: `پاشش آب یک لحظه فرم می‌گیرد و بلافاصله از هم می‌پاشد؛ قاب دقیق است، اما موضوع عیناً تکرارشدنی نیست. مهارت، تفاوت واقعیِ ماده را نگه می‌دارد.`
- Rights: rights pending.

#### The Pratfall Effect

- Category: Social Psychology / Short Note.
- Duration: 3 min read.
- Label: `COMPETENCE, THEN ONE SMALL SLIP`.
- Summary: `در یک آزمایش کلاسیک، لغزش کوچکی فقط برای فردی که از قبل توانمند دیده شده بود، جذابیت را بیشتر کرد. پس تفاوت انسانی جایگزین کیفیت نیست؛ بعد از کیفیت معنا پیدا می‌کند.`
- Visual: original DROP explanatory artwork.

---

## 11. TypeScript Content Schema

Use Zod or an equivalent runtime validator. A suggested shape:

```ts
type LocalizedText = {
  fa: string;
  en?: string;
};

type MediaAsset = {
  src: string;
  alt: LocalizedText;
  width?: number;
  height?: number;
  rightsStatus:
    | "approved"
    | "rights-pending"
    | "replace-with-final"
    | "original-drop"
    | "development-mock";
  productionAllowed: boolean;
  credit?: string;
  sourceUrl?: string;
  replacementNote?: string;
};

type MenuItem = {
  id: string;
  name: string;
  maker: string;
  category?: LocalizedText;
  rationale: LocalizedText;
  image: MediaAsset;
};

type FilmRecommendation = {
  id: string;
  viewLabel: string;
  title: string;
  director: string;
  year: string;
  genres?: string[];
  rationale: LocalizedText;
  poster: MediaAsset;
  sourceUrl?: string;
};

type TrackRecommendation = {
  id: string;
  title: string;
  artist: string;
  groupId?: string;
  groupTitle?: string;
  period?: "morning" | "afternoon" | "night";
  artwork: MediaAsset;
  sourceUrl?: string;
};

type ArtPiece = {
  id: string;
  category: LocalizedText;
  title: string;
  creator?: string;
  year?: string;
  duration?: string;
  rationale: LocalizedText;
  media: MediaAsset;
  sourceUrl?: string;
};

type WeeklyLens = {
  slug: string;
  week: string;
  title: LocalizedText;
  thesis: LocalizedText;
  tension: LocalizedText;
  balance: LocalizedText;
  notThis: LocalizedText;
  heroMessages: LocalizedText[];
  gridStatement: LocalizedText;
  menuItems: MenuItem[];
  films: FilmRecommendation[];
  tracks: TrackRecommendation[];
  artPieces: ArtPiece[];
  footer: {
    statement: LocalizedText;
    cta?: { label: LocalizedText; href: string; enabled: boolean };
    links: Array<{ label: string; href: string; enabled: boolean }>;
  };
};
```

### Content rules

- Counts displayed in UI derive from array length.
- Empty optional fields do not leave gaps.
- A scene gracefully handles the minimum allowed content count.
- Rights-pending assets show only in development/staging with an explicit internal flag.
- Production build fails or warns loudly when a required asset remains `replace-with-final`.
- Production build also fails while any asset remains `development-mock` or has `productionAllowed: false`.
- During development, use the complete local mock pack instead of broken images or duplicated placeholders.

---

## 12. Recommended Technical Stack

Use current stable releases compatible with the project environment; do not pin obsolete versions merely to match this document.

- Next.js App Router.
- React + TypeScript in strict mode.
- Tailwind CSS or CSS Modules for layout and tokens.
- GSAP + ScrollTrigger for pinned scenes, scrubbed timelines, and reversible choreography.
- Lenis for smooth scrolling, integrated correctly with GSAP's RAF.
- Three.js + React Three Fiber for the loader, shared shader canvas, disc/case depth, and footer effect.
- Custom GLSL for Wavy Dots, Monochrome Mesh, pixel mosaic, loader material, and footer light.
- Framer Motion only for small UI states where GSAP is unnecessary; do not split one scroll animation across two competing engines.
- Zod for content validation.
- `next/image` for production media.
- Playwright for end-to-end and scroll-state testing.

### Important architecture decision

Use one shared, fixed WebGL background canvas where possible. Transition shader scenes by uniforms/state rather than creating multiple simultaneous WebGL contexts.

DOM content remains semantic and above the canvas. WebGL is decorative and receives `aria-hidden="true"`.

---

## 13. Suggested Project Structure

```text
app/
  layout.tsx
  page.tsx
  lens/[slug]/page.tsx
  globals.css

components/
  brand/
    DropWordmark.tsx
    DropPrimaryLogo.tsx
    DropO.tsx
  shell/
    SiteHeader.tsx
    ImmersiveLensPage.tsx
  scenes/
    LoaderScene.tsx
    ThesisScene.tsx
    MenuDeckScene.tsx
    GridStatementScene.tsx
    FilmScene.tsx
    TracksScene.tsx
    ArtPiecesScene.tsx
    FooterScene.tsx
  transitions/
    PixelTransition.tsx
  webgl/
    BackgroundCanvas.tsx
    LoaderMaterial.ts
    WavyDotsShader.ts
    MonochromeMeshShader.ts
    PixelMosaicShader.ts
    FooterLightShader.ts
    JewelCase.tsx

content/
  lenses/
    beautiful-imperfection.ts
  current-lens.ts
  schema.ts

lib/
  motion/
    gsap.ts
    scroll.ts
    reduced-motion.ts
  media/
    rights.ts
  performance/
    quality-tier.ts

public/
  brand/
    drop-wordmark.svg
    drop-primary-logo.svg
  media/
    beautiful-imperfection/
      menu/
      films/
      tracks/
      art/

tests/
  lens-page.spec.ts
  reduced-motion.spec.ts
  content-schema.spec.ts
```

---

## 14. Shader and Background Management

### Shared canvas state

```ts
type BackgroundMode =
  | "offWhiteGlow"
  | "greenGrid"
  | "pixelA"
  | "wavyDots"
  | "pixelB"
  | "monoMesh"
  | "footerLight";
```

The page controller provides scene progress and target mode. Shaders interpolate only where specified. Pixel transitions own the change between modes.

### Quality tiers

- High: full shader detail, DPR capped at 1.75-2, reflections, grain, and pointer response.
- Medium: DPR capped at 1.5, fewer mesh subdivisions, reduced post-processing.
- Low: DPR 1, simplified noise, no expensive refraction, static/slow fallback.
- Reduced motion: static backgrounds with brief crossfades; all content remains accessible.

### Never use

- Video recordings of the MetalForge effects.
- Multiple full-screen canvases layered permanently.
- Unbounded DPR.
- Heavy bloom on all scenes.
- Shader motion that lowers text contrast.

---

## 15. Responsive Behavior

### Desktop, 1200px and wider

- Full pinned choreography.
- Film text left, poster right.
- Five-position music coverflow where space allows.
- Art text/media two-column layout.
- Pointer micro-interactions enabled.

### Tablet, 768-1199px

- Preserve scene order and pinning with shorter scroll budgets.
- Film layout remains two-column if readable; otherwise use a compact stacked composition.
- Three-position coverflow.
- Art media width increases relative to viewport.

### Mobile, below 768px

- Loader remains centered and legible.
- Hero text uses fewer line breaks and safe viewport units (`svh`/`dvh`).
- Menu deck uses narrower fan angles and vertical offsets.
- Film poster appears above or behind the text without reducing readability.
- Tracks are swipe-first, with visible arrow controls.
- Art Pieces become one column: title/details followed by media.
- Footer word can overflow horizontally by design but must keep `DROP` recognizable.
- No feature may depend on hover.
- Avoid long pinned sections that feel trapped on mobile; tune durations separately with `gsap.matchMedia`.

### Browser considerations

- Test iOS Safari viewport changes.
- Avoid fixed-height assumptions based only on `100vh`.
- Validate Safari/WebKit 3D backface behavior for menu cards.
- Provide a non-WebGL fallback when context creation fails.

---

## 16. Accessibility and User Control

- Semantic headings and section landmarks.
- Persian pages use `lang="fa"` and appropriate `dir="rtl"` for text containers.
- The deliberately left/right editorial layout remains controlled by CSS grid, not document direction hacks.
- All meaningful media has localized alt text.
- Decorative canvas and shader layers are hidden from assistive technology.
- Carousel supports keyboard arrows and clear focus states.
- Controls have accessible labels.
- No autoplay audio.
- Any loop video is muted, inline, and pausable when required.
- Respect `prefers-reduced-motion` across every scene.
- Reduced motion must not remove content or make the page unusable.
- Maintain WCAG AA text contrast.
- Do not flash or strobe.
- External links announce/open safely.

---

## 17. Performance Requirements

- Server-render all meaningful text for SEO and accessibility.
- Dynamically load WebGL-heavy modules on the client.
- Preload only loader/hero-critical assets.
- Lazy-load film, tracks, and Art Pieces before their scene enters.
- Use AVIF/WebP for raster images where appropriate.
- Suggested source sizes:
  - menu photography: 1400-1800px long edge;
  - film poster: approximately 1200x1800;
  - track artwork: 1024x1024;
  - art media: 1600px or higher long edge when licensing allows.
- Cap texture size based on quality tier.
- Dispose geometries, materials, and textures on unmount.
- Avoid layout shift after fonts load.
- Target smooth 60fps on capable desktop and stable 30fps or better on mid-range mobile.
- No console errors, WebGL warnings, or accumulating ScrollTriggers.

Suggested launch targets:

- Accessibility score: 95 or higher.
- Best Practices score: 90 or higher.
- Mobile performance: 75 or higher for the full immersive build, while preserving a lighter fallback.
- CLS: under 0.1.

---

## 18. Media Rights and Production Safety

- Do not hotlink film posters, album art, museum images, or product photography.
- Do not ship AI sample product images as final brand photography.
- Every media item has `rightsStatus` and optional credit/source.
- Staging may display watermarked/labeled placeholders.
- Production should block or clearly warn on unresolved required media.
- Keep credit text in the data even when it is not visually prominent in the cinematic scene.
- Add a credits/legal view later if licensing requires it.

---

## 19. Acceptance Criteria

### Loader

- Final DROP geometry is recognizable.
- All modules share one living material.
- O aperture visibly pulses.
- O becomes the portal to the page.
- No hard cut.

### Hero

- Small DROP logo is top-left.
- Top-right is empty.
- Three texts replace one another with scroll.
- Reverse scroll works.

### Menu

- Cards enter as a stack, fan, and flip with stagger.
- Back is black with white DROP logo.
- Front contains image/name/maker only.
- No rounded corners, price, buy, like, or cart.

### Grid and pixel transition

- Grid scene contains one centered statement only.
- Pixel cells align with the grid.
- Transition enters irregularly from below.
- It is scroll-linked and reversible.

### Films

- Exactly one active film at a time.
- Poster is right, information left on desktop.
- Three W04 films appear in order.
- Wavy Dots shader is present and restrained.

### Music transition and tracks

- Film poster/text fade during the second pixel transition.
- A completed dark beat precedes the Tracks entrance.
- Transparent jewel cases are visible.
- Artwork sits on the disc surface.
- Active track is centered with title and artist underneath.
- Carousel supports scroll, drag/swipe, buttons, and keyboard.

### Art Pieces

- Same Monochrome Mesh continues from Tracks.
- Four W04 items appear in editorial rows.
- Text and media reveal with mask/parallax.
- Sharp media edges and thin dividers.

### Footer

- Large outline DROP appears.
- Prismatic horizon is animated in real time.
- Light affects the outline as it passes.
- Footer is responsive and has a reduced-motion fallback.

### General

- Content is data-driven.
- Responsive at 375, 768, 1024, and 1440px widths.
- Keyboard and reduced-motion flows work.
- No content is hidden solely inside WebGL.
- No unlicensed remote media is silently shipped.
- No major visual jump, stuck pin, dead scroll zone, or console error.

---

## 20. Implementation Phases

### Phase 1: Foundation

- Project setup, fonts, tokens, content schema, W04 seed data.
- SVG reconstruction of final DROP logo.
- Page shell, header, reduced-motion utility, quality tiers.

### Phase 2: Loader and thesis

- Procedural logo geometry and material.
- O pulse and portal.
- Pinned thesis scene and brand glow.

### Phase 3: Menu and grid

- Card deck, fan, flip, responsive behavior.
- Grid statement scene.
- Pixel transition A.

### Phase 4: Films

- Wavy Dots shader.
- Three-state poster/text timeline.
- Film responsive layout.

### Phase 5: Music transition and tracks

- Pixel transition B.
- Monochrome Mesh shader.
- Jewel-case carousel, controls, and data behavior.

### Phase 6: Art Pieces and footer

- Editorial field-note rows.
- Mesh continuity.
- Footer outline word and light horizon shader.

### Phase 7: Hardening

- Responsive tuning.
- Reduced-motion and no-WebGL fallbacks.
- Performance profiling.
- Media-rights validation.
- Automated tests and visual QA.

Do not postpone all integration until the end. After each phase, test forward scroll, reverse scroll, route cleanup, and mobile behavior.

---

## 21. QA Matrix

| Area | Required checks |
|---|---|
| Browsers | Chrome, Safari, Firefox, iOS Safari |
| Viewports | 375x812, 768x1024, 1024x768, 1440x900 |
| Input | Mouse wheel, trackpad, touch, keyboard |
| Motion | Forward, reverse, rapid scroll, resize mid-scene |
| Accessibility | Reduced motion, keyboard carousel, focus visibility, headings, alt text |
| Performance | DPR caps, texture memory, trigger cleanup, context loss fallback |
| Content | 2 menu items, 3 films, variable track count, 4 Art Pieces |
| Rights | Approved vs. pending vs. replacement media states |
| Routes | `/`, direct `/lens/beautiful-imperfection`, refresh, back navigation |

---

## 22. Reference Direction

Use these references only for the named behavior:

- **Opacity** - loader material, O/void transition, pinned large text, minimalist pacing: https://opacity.com/
- **Lusion** - stacked cards, fan, stagger, 3D flip: https://lusion.co/
- **Zero University** - grid statement and sequential editorial card rhythm: https://www.zero.university/
- **Run Rob Run** - stepped pixel background replacement: https://www.runrobrun.com/
- **Serhat Durmus** - transparent CD/jewel-case coverflow: https://serhatdurmus.com/
- **X2Y Creative** - vertical Art Pieces editorial reveal: https://www.x2ycreative.com/
- **Existing DROP archive** - content hierarchy and permanent weekly lens model: https://drop-weekly-lens.mafi-kcafe.chatgpt.site/
- **W04 content source**: https://drop-weekly-lens.mafi-kcafe.chatgpt.site/lens/beautiful-imperfection

MetalForge preset sources supplied by the user:

- Wavy Dots: `https://metalforge.xyz/editor#effect=dots&style=wavy&speed=1&brightness=1&tint=%23FFFFFF&background=%23000000&dotSize=1&gridDensity=1&patternScale=1&vignette=1&horizon=-0.45&amplitude=1&depthFade=1`
- Monochrome Mesh: use the full user-supplied configuration hash and the parameter/color tables in Section 7.8.

---

## 23. Final Build Contract for Claude

The build is complete only when:

1. The full scene order is implemented.
2. Every critical motion behavior is present.
3. Content comes from validated data.
4. The final DROP logo and geometry are respected.
5. Shader backgrounds are real-time and have fallbacks.
6. The page works forward and backward through scroll.
7. Mobile, keyboard, and reduced-motion experiences are usable.
8. Media-rights placeholders are explicit.
9. The project passes the acceptance criteria and QA matrix.

If a final asset is missing, build the correct slot and interaction with a labeled local placeholder. Do not change the design structure to avoid the missing asset.

**Final experience statement:** DROP should feel less like browsing sections and more like moving through a weekly point of view.
