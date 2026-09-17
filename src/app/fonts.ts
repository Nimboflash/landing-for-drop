/**
 * Typefaces for the DROP Immersive Weekly Lens (brief §4, "Typography").
 *
 * Vazirmatn comes through `next/font/google`, which downloads the font files at
 * build time and serves them from our own origin; Satoshi and Abar are local
 * faces loaded through `next/font/local` from `./fonts`. Either way the bytes
 * are ours and no request leaves for a font host at runtime.
 *
 * The exported CSS variable names are load-bearing: `src/app/globals.css`
 * already binds `--font-persian` / `--font-latin` to `--font-abar` /
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
 * by building both ways, on the Google loader that Vazirmatn still uses:
 * passing `fallback` makes the emitted variable
 * `"Vazirmatn", Tahoma, sans-serif` and drops the
 * `@font-face { font-family: "Vazirmatn Fallback"; size-adjust: … }` rule
 * entirely — i.e. it silently disables `adjustFontFallback` and with it the
 * whole anti-CLS mechanism. Without it the variable is
 * `"Vazirmatn", "Vazirmatn Fallback"` and the metric-override face is
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
 * The Persian SAFETY NET, no longer the Persian voice — Abar below is.
 *
 * Kept in the stack rather than deleted because it is the one face here that is
 * certain to carry the whole Arabic block, and a missing glyph in a Persian
 * headline is a worse failure than an unused `@font-face` rule.
 *
 * `preload: false` is what makes that free: Next still emits the face, but the
 * browser only fetches it if Abar fails to match a glyph. In the normal case
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
 * Brief §4 says to "self-host Vazirmatn until a final licensed Persian brand typeface is
 * approved". Abar is that typeface, so this is the swap the brief was holding the place for.
 * Self-hosted, like everything else here: the bytes are served from our own origin and no
 * request leaves for a font host at runtime.
 *
 * THE NO-ENGLISH CUT, and that is a decision about who draws what. Abar ships three variable
 * files — the full face, one with Persian numerals, and one with no Latin at all. The lens data
 * has zero Persian strings containing Latin letters and zero Persian digits, both counted rather
 * than assumed, so the numeral cut buys nothing. The no-English cut is what keeps the existing
 * arrangement true: Latin that appears inside Persian text falls through to Satoshi, which is
 * the face meant to draw it. It is also 22KB lighter than the full one.
 *
 * One variable file covering 400-900 rather than static cuts. The page asks for Persian at 400,
 * 600, 700 and 800, and a range covers all four exactly — the lesson the Latin swap taught, where
 * a declared 600 had been quietly rendering as 700 for want of a face to land on.
 */
export const abar = localFont({
  src: [
    {
      path: "./fonts/AbarNoEn-VF.woff2",
      weight: "400 900",
      style: "normal",
    },
  ],
  display: "swap",
  preload: true,
  variable: "--font-abar",
  /*
   * Optical size, measured against the face this replaces rather than chosen.
   *
   * Every font-size and line-height in this repo is tuned against Aria as it rendered — which is
   * Aria at its own 106.3%. At 100px the same Persian string sets 13.9529em wide in Aria against
   * 15.555em in Abar, with ink ascents of 0.7611 and 0.845: ratios of 0.897 and 0.9007. Two
   * measurements that close together describe a uniform scale, not a difference in shape, so a
   * single number can carry it.
   *
   * 0.89885 x 106.3% = 95.5%. Abar simply draws larger per em than Aria did.
   *
   * It also leaves the leading alone, which is the thing a face swap usually breaks: Abar's ink
   * runs 1.135em ascender to descender, which at this adjustment is 1.0845em against the 1.18
   * the Persian headings set — and Aria's was 1.0758em. The two faces land within a hundredth of
   * each other, so `--leading-fa-display` needs no retuning.
   */
  declarations: [{ prop: "size-adjust", value: "95.5%" }],
});

/** Every font CSS variable, ready to hang on `<html>`. */
export const fontVariables = `${satoshi.variable} ${vazirmatn.variable} ${abar.variable}`;
