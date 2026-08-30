/**
 * Typefaces for the DROP Immersive Weekly Lens (brief §4, "Typography").
 *
 * Both families are loaded through `next/font/google`, which downloads the font
 * files at build time and serves them from our own origin — that is what
 * satisfies the brief's "self-host Vazirmatn until a final licensed Persian
 * brand typeface is approved". No request ever leaves for fonts.googleapis.com
 * at runtime.
 *
 * The exported CSS variable names are load-bearing: `src/app/globals.css`
 * already binds `--font-persian` / `--font-latin` to `--font-vazirmatn` /
 * `--font-montserrat`. Renaming either variable silently drops the whole page
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

import { Montserrat, Vazirmatn } from "next/font/google";

/**
 * Latin display and UI face. ExtraBold (800) and Bold (700) carry display type;
 * Regular (400) carries Latin body copy. Static instances rather than the
 * variable axis, so the three weights ship exactly as designed.
 */
export const montserrat = Montserrat({
  subsets: ["latin"],
  weight: ["400", "700", "800"],
  style: ["normal"],
  display: "swap",
  preload: true,
  adjustFontFallback: true,
  variable: "--font-montserrat",
});

/**
 * Persian face — the primary editorial voice of the page. Carries both Arabic
 * and Latin subsets because Persian text runs routinely embed Latin fragments
 * (maker names, film titles, years) inline. Weights mirror Montserrat's so
 * Persian headings reach the 800 weight `globals.css` sets on h1–h4.
 */
export const vazirmatn = Vazirmatn({
  subsets: ["arabic", "latin"],
  weight: ["400", "700", "800"],
  style: ["normal"],
  display: "swap",
  preload: true,
  adjustFontFallback: true,
  variable: "--font-vazirmatn",
});

/** Both font CSS variables, ready to hang on `<html>`. */
export const fontVariables = `${montserrat.variable} ${vazirmatn.variable}`;
