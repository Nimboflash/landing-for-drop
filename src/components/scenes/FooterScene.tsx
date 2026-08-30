"use client";

/**
 * The final scene: the giant outline DROP and its prismatic light horizon (brief §7.10, ticket 14).
 *
 * The footer sits on the black the Monochrome Mesh faded into — it is NOT a separate white card
 * and NOT a generic site footer. A very large DROP wordmark spans the lower half as a thin, dark
 * OUTLINE: visible before the light arrives, never high-contrast, never a solid fill. Below it,
 * the closing statement, a CTA slot that ships disabled, and the metadata slots — all from data.
 *
 * ## Division of labour with the shader
 *
 * | layer | owner |
 * | --- | --- |
 * | the prismatic horizon, its bloom, drift, pointer distortion and no-WebGL ribbon | `FooterLightShader` on the shared canvas |
 * | the outline wordmark, its reveal, and the illumination the light leaves on it | this component |
 *
 * The light is behind the DOM, so a dark outline crossing it would only ever read as a silhouette.
 * The brief asks for the opposite — "The line briefly illuminates the outline sections it passes" —
 * so the wordmark is drawn twice: a dark base outline, and a bright copy masked to a soft band that
 * follows the beam. Both the band's position and the bright copy's strength come from
 * {@link footerLightUniforms}, the shader's own pure helper, so the illumination cannot drift out
 * of step with the light it is supposed to be coming from.
 *
 * ## Exact brand geometry, drawn as outline
 *
 * The wordmark is the tile-and-knockout construction from `@/components/brand` — solid tiles with
 * the letterforms knocked out, D/R/P square and O a circle — drawn as contours instead of fills.
 * Never a font, never a traced bitmap; this file states no dimension of its own.
 *
 * Stroking the knockout paths directly would expose their construction seams: an R's body is a
 * stem, a bowl and a leg that overlap on purpose, and stroked overlapping subpaths draw their
 * internal edges. So the contour is built in a mask instead — each group is grown by one stroke
 * width and the solid form is then subtracted, leaving a hairline ring hugging the *union's*
 * outside. That is the drawn letter's true contour, at any size, with no boolean-path library.
 *
 * ## This scene decides nothing
 *
 * No ScrollTrigger, no progress of its own, no background mode: the scene-state reducer already
 * decided all of it (BUILD-GUIDE seam 2, one-way data flow). The reveal is a pure function of the
 * `footerReveal` the reducer hands down — which is what makes it exactly reversible, and why there
 * is no GSAP here: a tween would fight the scrub it is being scrubbed by.
 *
 * ## Observable state (BUILD-GUIDE seam 3)
 *
 * Kept from the placeholder, unchanged: `data-footer-statement`, `data-footer-statement-en`,
 * `data-footer-links`, and `data-footer-link` + `data-enabled` on every slot.
 *
 * Changed by this ticket: `data-footer-cta` is now ALWAYS rendered, carrying `data-enabled` —
 * the brief keeps the CTA "configurable but disabled until final CTA copy/action is supplied",
 * which is a slot that must be visible as disabled, not an element that disappears.
 *
 * Added: `data-footer` and `data-reveal-percent` on the root (the reducer's reveal, rounded, so
 * the page seam can assert the reveal advances and rewinds without reading a computed style),
 * `data-motion` (`"scrubbed"` / `"static"`), and `data-footer-wordmark` on the outline stage.
 *
 * ## Disabled means non-interactive
 *
 * A disabled slot renders as text, never as a dead link, and never as a pill copied from the
 * layout reference — so nothing here is focusable as a link and no destination is invented.
 * The reference frame for this scene also carries a "Schedule demo" button; the brief forbids it.
 *
 * ## Reduced motion and no-JavaScript
 *
 * Reduced motion gets a static outline reveal: fully drawn, no wipe, no drift (the shader supplies
 * its own static ribbon). Nothing is ever hidden by progress — every string is server-rendered and
 * stays in the accessibility tree at every reveal value, so a JavaScript-disabled render reads the
 * complete footer with the outline already faintly present.
 */

import { useId, type CSSProperties, type ReactNode } from "react";

import { brandGeometry, lockupPaths } from "@/components/brand";
import { footerLightUniforms } from "@/components/webgl/FooterLightShader";
import type { FooterLink, LocalizedText, WeeklyLens } from "@/content";

import styles from "./FooterScene.module.css";

/* ------------------------------------------------------------------ tuning */

/**
 * Nominal module size the wordmark geometry is built at. Pure choice of user units: the SVG is
 * scaled by its `viewBox`, so this number never reaches the screen — every proportion inside it
 * still comes from `brandGeometry`.
 */
const WORDMARK_MODULE_UNITS = 100;

/**
 * Rendered stroke weight, in CSS pixels. Held constant at every size by `non-scaling-stroke`:
 * a stroke measured in user units would be a hairline on a phone and a rope on a 4K display,
 * and "thin outline" is a property of the drawn line, not of the coordinate system.
 */
const OUTLINE_STROKE_PX = 1.1;

/** The tiles read as the frame around the letters, so they sit a step behind them. */
const TILE_OUTLINE_ALPHA = 0.55;

/** Slack around the lockup box so the outer half of a stroke is never clipped by the viewBox. */
const OUTLINE_PAD_UNITS = 4;

/**
 * Outline alpha at reveal 0 as a fraction of its resting alpha. Not zero: the brief wants the
 * outline "visible before the light arrives", and this is also the state a JavaScript-disabled
 * render is served.
 */
const OUTLINE_STRENGTH_FLOOR = 0.35;

/** Wipe edge at reveal 0 and at reveal 1, as a percentage of the wordmark's own height. */
const OUTLINE_EDGE_FLOOR_PERCENT = 45;
const OUTLINE_EDGE_FULL_PERCENT = 122;

/** How far the outline settles upward across the reveal, in small viewport heights. */
const OUTLINE_LIFT_SVH = 1.8;

/** Content opacity at footer progress 0. A settle, never a hide — the text is always readable. */
const CONTENT_OPACITY_FLOOR = 0.72;

/** How far the closing block and the metadata row settle, in small viewport heights. */
const CONTENT_LIFT_SVH = 1.2;

/* -------------------------------------------------------------------- pure */

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value < 0) return 0;
  if (value > 1) return 1;
  return value;
}

/** Smoothstep — the same shape the light itself eases with, so the two arrive together. */
function ease(value: number): number {
  const t = clamp01(value);
  return t * t * (3 - 2 * t);
}

function mix(from: number, to: number, t: number): number {
  return from + (to - from) * t;
}

/** English where the data has it, Persian otherwise — never an empty slot (brief §11). */
function englishOr(text: LocalizedText): string {
  return text.en ?? text.fa;
}

/** A Latin run inside a Persian document: the metadata labels and the English closing line. */
function Latin({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={className} lang="en" dir="ltr">
      {children}
    </span>
  );
}

/**
 * Whether a data slot carries a real destination. A slot is live only when the content says so
 * AND names somewhere to go — "Do not invent live destinations" (brief §7.10), and an enabled
 * flag with an empty href is a slot still waiting for its final address.
 */
function isLive(slot: { href: string; enabled: boolean }): boolean {
  return slot.enabled && slot.href.trim() !== "";
}

/* -------------------------------------------------------- outline wordmark */

const WORDMARK_GEOMETRY = brandGeometry(WORDMARK_MODULE_UNITS);
const WORDMARK_LOCKUP = WORDMARK_GEOMETRY.wordmark;
const WORDMARK_PATHS = lockupPaths(WORDMARK_GEOMETRY, WORDMARK_LOCKUP);

/** The padded drawing box: the lockup plus stroke slack on every side. */
const WORDMARK_BOX = {
  x: -OUTLINE_PAD_UNITS,
  y: -OUTLINE_PAD_UNITS,
  width: WORDMARK_LOCKUP.width + OUTLINE_PAD_UNITS * 2,
  height: WORDMARK_LOCKUP.height + OUTLINE_PAD_UNITS * 2,
} as const;

/** Rendered aspect ratio of that box. The stylesheet sizes the figure from it. */
const WORDMARK_ASPECT = WORDMARK_BOX.width / WORDMARK_BOX.height;

/**
 * Where the beam comes to rest, in the shader's own UV-y. Taken from the shader rather than
 * written down, because the stylesheet hangs the word so that the settled horizon crosses its
 * middle: if the light's resting height is ever retuned, the word follows it instead of drifting
 * out of the composition.
 */
const SETTLED_HORIZON = footerLightUniforms(1).horizonY;

/**
 * One copy of the outline wordmark.
 *
 * The mask is the whole technique. Painting order inside it:
 *
 * 1. the tile silhouettes, stroked down the middle — four tiles that never overlap, so a plain
 *    centred stroke is already their exact contour;
 * 2. the knocked-out marks, grown by one stroke width (filled *and* stroked at twice the weight);
 * 3. the same marks solid in black, which removes everything but the grown rim — a hairline ring
 *    on the outside of the union, with every construction seam inside it erased;
 * 4. and 5. the counters of D, R and P, given the same treatment, so the letters keep their
 *    inner contours.
 *
 * The mark is then a single rect painted in `currentColor` through that mask, which is what lets
 * one component serve as both the dark base outline and the bright illuminated copy.
 */
function OutlineWordmark({ className }: { className?: string }) {
  const instanceId = useId();
  // `useId` output is not guaranteed to be url()-safe; keep only characters that are.
  const maskId = `drop-footer-outline-${instanceId.replace(/[^a-zA-Z0-9_-]/g, "")}`;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      viewBox={`${WORDMARK_BOX.x} ${WORDMARK_BOX.y} ${WORDMARK_BOX.width} ${WORDMARK_BOX.height}`}
      preserveAspectRatio="xMidYMid meet"
      aria-hidden="true"
      focusable="false"
    >
      <mask
        id={maskId}
        maskUnits="userSpaceOnUse"
        x={WORDMARK_BOX.x}
        y={WORDMARK_BOX.y}
        width={WORDMARK_BOX.width}
        height={WORDMARK_BOX.height}
      >
        <path
          d={WORDMARK_PATHS.tiles}
          fill="none"
          stroke="#fff"
          strokeWidth={OUTLINE_STROKE_PX}
          vectorEffect="non-scaling-stroke"
          opacity={TILE_OUTLINE_ALPHA}
        />
        <path
          d={WORDMARK_PATHS.bodies}
          fill="#fff"
          stroke="#fff"
          strokeWidth={OUTLINE_STROKE_PX * 2}
          vectorEffect="non-scaling-stroke"
        />
        <path d={WORDMARK_PATHS.bodies} fill="#000" />
        {WORDMARK_PATHS.counters === "" ? null : (
          <>
            <path
              d={WORDMARK_PATHS.counters}
              fill="#fff"
              stroke="#fff"
              strokeWidth={OUTLINE_STROKE_PX * 2}
              vectorEffect="non-scaling-stroke"
            />
            <path d={WORDMARK_PATHS.counters} fill="#000" />
          </>
        )}
      </mask>
      <rect
        x={WORDMARK_BOX.x}
        y={WORDMARK_BOX.y}
        width={WORDMARK_BOX.width}
        height={WORDMARK_BOX.height}
        fill="currentColor"
        mask={`url(#${maskId})`}
      />
    </svg>
  );
}

/* --------------------------------------------------------------- component */

export interface FooterSceneProps {
  /** The lens's footer block: closing statement, optional CTA, and the metadata slots. */
  footer: WeeklyLens["footer"];
  /**
   * The reducer's `transitionState.footerReveal`, 0..1. Drives the outline reveal, and — through
   * the shader's own `footerLightUniforms` — where the light is and how bright it burns. Reverse
   * scroll re-emits the same value and every derivation below is pure, so the scene rewinds
   * exactly rather than resetting.
   */
  footerReveal: number;
  /** The footer scene's scroll progress, 0..1. Settles the closing block and the metadata row. */
  progress: number;
  /** The reducer's reduced-motion flag: static outline reveal, no wipe, no drift. */
  reducedMotion: boolean;
}

/** The custom properties the stylesheet reads. Every one of them is reducer output, eased. */
type FooterStyle = CSSProperties & {
  "--footer-wordmark-aspect": string;
  "--footer-horizon-settled": string;
  "--footer-outline-strength": string;
  "--footer-outline-edge": string;
  "--footer-outline-lift": string;
  "--footer-light-intensity": string;
  "--footer-horizon": string;
  "--footer-content-opacity": string;
  "--footer-content-lift": string;
};

export function FooterScene({ footer, footerReveal, progress, reducedMotion }: FooterSceneProps) {
  const reveal = clamp01(footerReveal);
  const revealed = ease(reveal);

  /**
   * The light, from the shader's own helper. `coreIntensity` is how hard the beam is burning and
   * `horizonY` is where it sits in UV-y (0 = the bottom of the frame) — the illuminated copy uses
   * the first as its strength and the second as its band position, so it tracks the real light
   * instead of a second guess at it.
   */
  const light = footerLightUniforms(reveal);

  // Reduced motion: the outline is simply there. The band still follows the light, because that
  // is a scroll position rather than an animation — and the shader moves it under reduced motion
  // too, so holding it still here would only put the glow somewhere the beam is not.
  const strength = reducedMotion ? 1 : mix(OUTLINE_STRENGTH_FLOOR, 1, revealed);
  const edgePercent = reducedMotion
    ? OUTLINE_EDGE_FULL_PERCENT
    : mix(OUTLINE_EDGE_FLOOR_PERCENT, OUTLINE_EDGE_FULL_PERCENT, revealed);
  const lift = reducedMotion ? 0 : (1 - revealed) * OUTLINE_LIFT_SVH;

  const settled = reducedMotion ? 1 : ease(clamp01(progress));

  const style: FooterStyle = {
    "--footer-wordmark-aspect": WORDMARK_ASPECT.toFixed(4),
    "--footer-horizon-settled": SETTLED_HORIZON.toFixed(4),
    "--footer-outline-strength": strength.toFixed(3),
    "--footer-outline-edge": `${edgePercent.toFixed(2)}%`,
    "--footer-outline-lift": `${(-lift).toFixed(3)}svh`,
    "--footer-light-intensity": light.coreIntensity.toFixed(3),
    "--footer-horizon": light.horizonY.toFixed(4),
    "--footer-content-opacity": mix(CONTENT_OPACITY_FLOOR, 1, settled).toFixed(3),
    "--footer-content-lift": `${((1 - settled) * CONTENT_LIFT_SVH).toFixed(3)}svh`,
  };

  const cta = footer.cta;

  return (
    /*
     * A real <footer> rather than a <div>: this is the closing content of the document and it
     * carries the Instagram, location, contact, copyright and legal slots.
     *
     * No explicit role="contentinfo" on purpose. This element sits inside the scene machine's
     * <section> (and inside <main>), and HTML-AAM only maps <footer> to `contentinfo` when it is
     * NOT a descendant of section/article/main. Forcing the role here would instead trip axe's
     * landmark-contentinfo-is-top-level rule, trading a missing landmark for a real violation.
     * Promoting it to a true top-level landmark means rendering the footer scene outside <main>,
     * which changes the element the scene machine pins — recorded in docs/qa/, not done here.
     */
    <footer
      className={styles.footer}
      style={style}
      data-footer
      data-reveal-percent={Math.round(reveal * 100)}
      data-motion={reducedMotion ? "static" : "scrubbed"}
    >
      {/*
        Decorative: the giant word is the brand's own name repeated as artwork, and the persistent
        header already carries the DROP mark with an accessible name. Nothing is announced twice,
        and no content lives only inside it.
      */}
      <div className={styles.wordmarkStage} data-footer-wordmark aria-hidden="true">
        <div className={styles.wordmark}>
          <OutlineWordmark className={styles.outline} />
          <OutlineWordmark className={`${styles.outline} ${styles.outlineLit}`} />
        </div>
      </div>

      <div className={styles.closing}>
        <p className={styles.statement} dir="rtl" data-footer-statement>
          {footer.statement.fa}
        </p>
        <p className={styles.statementEn} data-footer-statement-en>
          <Latin>{englishOr(footer.statement)}</Latin>
        </p>
        {cta ? <FooterCta cta={cta} /> : null}
      </div>

      <ul className={styles.links} dir="ltr" data-footer-links>
        {footer.links.map((link) => (
          <FooterSlot key={link.label} link={link} />
        ))}
      </ul>
    </footer>
  );
}

/**
 * The central CTA slot.
 *
 * Brief §7.10: "A central CTA is configurable but disabled until final CTA copy/action is
 * supplied." So the slot is always rendered and always reflects the data — a live anchor only
 * once the content names both an action and a destination, and otherwise inert text in a sharp
 * bordered slot that reads as clearly unavailable. Never a `<button>` (it would announce an
 * action that does not exist yet), never a waitlist or demo pill.
 */
function FooterCta({ cta }: { cta: NonNullable<WeeklyLens["footer"]["cta"]> }) {
  const live = isLive(cta);
  const label = cta.label.fa;
  const labelEn = englishOr(cta.label);

  if (live) {
    return (
      <a className={styles.cta} href={cta.href} data-footer-cta data-enabled="true">
        {label}
      </a>
    );
  }

  return (
    <p className={styles.cta} data-footer-cta data-enabled="false">
      <span dir="rtl">{label}</span>
      <Latin className={styles.ctaEn}>{labelEn}</Latin>
    </p>
  );
}

/**
 * One metadata slot. The count of slots is the array's length — the brief names five (Instagram,
 * location, contact, copyright, legal) and the content carries five, but this file counts none of
 * them. A disabled slot is plain text: not an anchor, so it is not focusable as a link.
 */
function FooterSlot({ link }: { link: FooterLink }) {
  const live = isLive(link);

  return (
    <li className={styles.link} data-footer-link data-enabled={link.enabled}>
      {live ? (
        <a href={link.href}>
          <Latin>{link.label}</Latin>
        </a>
      ) : (
        <Latin>{link.label}</Latin>
      )}
    </li>
  );
}

export default FooterScene;
