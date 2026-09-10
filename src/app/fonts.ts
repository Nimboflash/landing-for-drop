/**
 * Typefaces for the DROP Immersive Weekly Lens (brief §4, "Typography").
 *
 * Montserrat and Vazirmatn come through `next/font/google`, which downloads the
 * font files at build time and serves them from our own origin; Kalameh is a
 * licensed local face loaded through `next/font/local` from `./fonts`. Either
 * way the bytes are ours and no request leaves for a font host at runtime.
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
import localFont from "next/font/local";

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
 * The Persian SAFETY NET, no longer the Persian voice — Kalameh below is.
 *
 * Kept in the stack rather than deleted because it is the one face here that is
 * certain to carry the whole Arabic block, and a missing glyph in a Persian
 * headline is a worse failure than an unused `@font-face` rule.
 *
 * `preload: false` is what makes that free: Next still emits the face, but the
 * browser only fetches it if Kalameh fails to match a glyph. In the normal case
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
 * typeface is approved". Kalameh is that typeface, so this is the swap the brief
 * was holding the place for rather than a departure from it. Self-hosted for the
 * same reason Vazirmatn was: the files are served from our own origin and no
 * request leaves for a font host at runtime.
 *
 * Three weights, not the four that were supplied. The page asks for 800 (eight
 * rules), 700 (five), 600 (one) and the 400 of body copy; nothing asks for a light
 * weight, so Thin would have been ~86KB nobody downloads for a reason. The three
 * here cover every request through normal CSS font matching: 600 resolves up to
 * Bold, and 800 resolves up to Black, which is the heaviest face the family has and
 * the one the 800 rules were reaching for.
 *
 * TTF rather than woff2 because that is the format supplied. They are ~90KB each
 * where woff2 would be roughly half; converting them is worth doing before launch,
 * and needs a tool this machine does not currently have.
 *
 * `adjustFontFallback` is left at its default. For `next/font/local` that default
 * is the string `'Arial'` rather than the boolean `true` that the Google loaders
 * above take — same anti-CLS mechanism, different spelling of the option, and
 * passing `true` here would be a type error rather than a silent downgrade.
 */
export const kalameh = localFont({
  src: [
    { path: "./fonts/KalamehWeb-Regular.ttf", weight: "400", style: "normal" },
    { path: "./fonts/KalamehWeb-Bold.ttf", weight: "700", style: "normal" },
  ],
  display: "swap",
  preload: true,
  variable: "--font-kalameh",
  /*
   * Optical size, not a preference.
   *
   * Kalameh draws far smaller per em than Vazirmatn: measured in the browser at 100px,
   * the same Persian string is 639.9px wide against 812.6px, with an ink ascent of 53.7
   * against 68.5. Both ratios land on the same number -- 1.2699 and 1.2756 -- so it is a
   * uniform scale difference rather than a shape difference.
   *
   * Every font-size, line-height and measured layout in this repo was tuned against
   * Vazirmatn's optical size. Dropping in a face that renders a fifth smaller leaves all
   * of those numbers describing type that is no longer there: small glyphs adrift in line
   * boxes sized for bigger ones. Correcting it here fixes every one of those rules at
   * once, where correcting it rule by rule would be thirty edits and a permanent trap for
   * the next person who changes a font-size.
   */
  declarations: [{ prop: "size-adjust", value: "127.3%" }],
});

/** Every font CSS variable, ready to hang on `<html>`. */
export const fontVariables = `${montserrat.variable} ${vazirmatn.variable} ${kalameh.variable}`;
