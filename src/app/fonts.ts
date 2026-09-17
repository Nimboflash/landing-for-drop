/**
 * Typefaces for the DROP Immersive Weekly Lens (brief §4, "Typography").
 *
 * Vazirmatn comes through `next/font/google`, which downloads the font files at
 * build time and serves them from our own origin; Satoshi and Aria are local
 * faces loaded through `next/font/local` from `./fonts`. Either way the bytes
 * are ours and no request leaves for a font host at runtime.
 *
 * The exported CSS variable names are load-bearing: `src/app/globals.css`
 * already binds `--font-persian` / `--font-latin` to `--font-aria` /
 * `--font-satoshi`. Renaming either variable silently drops the whole page
 * back to the fallback stack.
 *
 * `adjustFontFallback: true` makes Next generate a metric-adjusted local
 * fallback face (ascent/descent/line-gap/size-adjust derived from the real
 * font), so the `display: "swap"` handoff swaps glyphs without reflowing text.
 * That is what keeps CLS under the brief's 0.1 launch target (brief §17,
 * "Avoid layout shift after fonts load").
 *
 * DO NOT ADD A `fallback` ARRAY HERE. Verified against Next 16.3.2 + Turbopack
 * by building both ways: passing `fallback` makes the emitted variable
 * `"Montserrat", Helvetica Neue, Arial, sans-serif` and drops the
 * `@font-face { font-family: "Montserrat Fallback"; size-adjust: … }` rule
 * entirely — i.e. it silently disables `adjustFontFallback` and with it the
 * whole anti-CLS mechanism. Without it the variable is
 * `"Montserrat", "Montserrat Fallback"` and the metric-override face is
 * emitted. Plain-family fallbacks are not lost: `globals.css` already appends
 * them in `--font-latin` (Helvetica Neue, Arial, sans-serif) and
 * `--font-persian` (Tahoma, sans-serif), which is where that stack belongs.
 */

import { Vazirmatn } from "next/font/google";
import localFont from "next/font/local";

/**
 * Latin display and UI face.
 *
 * Satoshi, self-hosted from `./fonts` under the ITF Free Font License, which permits
 * self-hosting and commercial use. `Satoshi-LICENSE.txt` ships beside the file.
 *
 * THE VARIABLE CUT, not static instances — a deliberate reversal of what Montserrat did here,
 * and the reason is a bug that swap exposed. The page asks for Latin at 400, 600 and 700.
 * Montserrat was loaded at 400/700/800, so the 600 on the thesis eyebrow had no face to land
 * on: CSS weight matching takes the first weight at or above 600 and it was rendering at 700.
 * Satoshi's static cuts are 300/400/500/700/900 and would have missed it the same way. One
 * variable file covers the range continuously, so a declared 600 is a 600 — and it is 42KB
 * against the five static cuts it replaces.
 *
 * `adjustFontFallback: "Arial"` for a LOCAL font, where the Google loader takes a boolean:
 * the local signature is `'Arial' | 'Times New Roman' | false`, and passing `true` is a type
 * error rather than a no-op.
 */
export const satoshi = localFont({
  src: [
    {
      path: "./fonts/Satoshi-Variable.woff2",
      weight: "300 900",
      style: "normal",
    },
  ],
  display: "swap",
  preload: true,
  adjustFontFallback: "Arial",
  variable: "--font-satoshi",
});

/**
 * The Persian SAFETY NET, no longer the Persian voice — Aria below is.
 *
 * Kept in the stack rather than deleted because it is the one face here that is
 * certain to carry the whole Arabic block, and a missing glyph in a Persian
 * headline is a worse failure than an unused `@font-face` rule.
 *
 * `preload: false` is what makes that free: Next still emits the face, but the
 * browser only fetches it if Aria fails to match a glyph. In the normal case
 * nothing downloads, so the safety net costs a rule and no bytes.
 */
export const vazirmatn = Vazirmatn({
  subsets: ["arabic", "latin"],
  weight: ["400", "700", "800"],
  style: ["normal"],
  display: "swap",
  preload: false,
  adjustFontFallback: true,
  variable: "--font-vazirmatn",
});

/**
 * Persian face — the primary editorial voice of the page.
 *
 * Brief §4 says to "self-host Vazirmatn until a final licensed Persian brand
 * typeface is approved". Aria is that typeface, so this is the swap the brief was
 * holding the place for rather than a departure from it. Self-hosted for the same
 * reason Vazirmatn was: the files are served from our own origin and no request
 * leaves for a font host at runtime.
 *
 * FOUR weights, and every one of them is a real face rather than a near miss. The
 * page asks for 800 (eight rules), 700 (five), 600 (one) and the 400 of body copy,
 * and Aria draws all four: usWeightClass 400 / 600 / 700 / 800 read straight from
 * each file's OS/2 table. That is the thing the previous face could not do — it had
 * no 800, so CSS matched upward to Black and every heading rendered a step heavy,
 * and dropping Black to avoid that collapsed the hero and the closing statement onto
 * one weight. Nothing is being approximated here.
 *
 * The family ships twelve weights; the eight nothing asks for are not shipped. Aria
 * also has a second face at four of those classes (Normal beside Regular, UltraBold
 * beside ExtraBold, Heavy beside Black) — the conventional member is taken in each
 * case.
 *
 * woff2, converted from the supplied TTFs: 1153KB of TTF became 379KB, which is the
 * difference between four weights being affordable and not.
 *
 * `adjustFontFallback` is left at its default. For `next/font/local` that default
 * is the string `'Arial'` rather than the boolean `true` that the Google loaders
 * above take — same anti-CLS mechanism, different spelling of the option, and
 * passing `true` here would be a type error rather than a silent downgrade.
 */
export const aria = localFont({
  src: [
    { path: "./fonts/Aria-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/Aria-SemiBold.woff2", weight: "600", style: "normal" },
    { path: "./fonts/Aria-Bold.woff2", weight: "700", style: "normal" },
    { path: "./fonts/Aria-ExtraBold.woff2", weight: "800", style: "normal" },
  ],
  display: "swap",
  preload: true,
  variable: "--font-aria",
  /*
   * Optical size, measured rather than chosen.
   *
   * Aria sets about 6.5% smaller per em than Vazirmatn, which every font-size and
   * line-height in this repo was tuned against. At 100px the same Persian string is
   * 7.595em wide against 8.1265em, with an ink ascent of 0.648 against 0.6846 — ratios
   * of 1.070 and 1.057, close enough to each other to be a uniform scale rather than a
   * difference in shape.
   *
   * 106.3% is the mean of the two. It also brings the `ch` unit back into line: Aria's
   * zero is 0.527em against Vazirmatn's 0.562em, a ratio of 1.066 that tracks the text
   * ratio almost exactly, so adjusting the face fixes the measures at the same time.
   * (The previous face did NOT behave that way — its zero was 19% out of step with its
   * own text, which is why every ch measure had to be hand-corrected and then undone.)
   */
  declarations: [{ prop: "size-adjust", value: "106.3%" }],
});

/** Every font CSS variable, ready to hang on `<html>`. */
export const fontVariables = `${satoshi.variable} ${vazirmatn.variable} ${aria.variable}`;
