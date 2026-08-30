"use client";

import { useId } from "react";

import styles from "./brand.module.css";
import {
  DEFAULT_MODULE_SIZE,
  brandGeometry,
  lockupPaths,
  viewBox,
  type BrandGeometry,
  type Lockup,
} from "./geometry";

/**
 * Which way round the mark is painted.
 *
 * `dark` gives dark tiles for a light scene, `light` gives light tiles for a dark one. The
 * knockout is always a real hole, so the letters take whatever is behind the mark — which is how
 * the persistent header can swap contrast per scene without carrying a background (brief §8).
 */
export type BrandVariant = "dark" | "light";

/** Props every DROP mark accepts. */
export interface BrandMarkProps {
  /** Rendered side of one module (one tile) in px. Scales the whole lockup. */
  size?: number;
  /** Tile polarity for the scene the mark sits on. */
  variant?: BrandVariant;
  className?: string;
  /**
   * Accessible name, also rendered as an SVG `<title>`. Omit it (and `aria-label`) for
   * decorative use — the mark is then hidden from assistive technology.
   */
  title?: string;
  /** Accessible name without a visible tooltip. Takes precedence over `title`. */
  "aria-label"?: string;
}

interface BrandLockupProps extends BrandMarkProps {
  /** Value of the `data-brand` attribute the page seam asserts against. */
  mark: string;
  geometry: BrandGeometry;
  lockup: Lockup;
  /** Drives the O's aperture where the lockup has one. `1` is the resting aperture. */
  apertureScale?: number;
}

/**
 * The one renderer behind every DROP mark.
 *
 * Tiles are painted in `currentColor` through a mask: the marks are removed from them, then the
 * counters of D, R and P are given back. A mask rather than an even/odd single path because the
 * letterforms genuinely overlap themselves — an R's leg tucks under its bowl the way the drawn
 * letter does — and overlapping siblings would punch parity holes.
 *
 * Exported from this file rather than its own because the ticket owns a fixed file list; the
 * natural home is `BrandLockup.tsx`, and moving it there is a pure rename.
 */
export function BrandLockup({
  mark,
  geometry,
  lockup,
  apertureScale = 1,
  variant = "dark",
  className,
  title,
  "aria-label": ariaLabel,
}: BrandLockupProps) {
  const instanceId = useId();
  // `useId` output is not guaranteed to be url()-safe; keep only characters that are.
  const maskId = `drop-${mark}-${instanceId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const paths = lockupPaths(geometry, lockup, apertureScale);
  const label = ariaLabel ?? title;
  const classes = [styles.mark, styles[variant], className].filter(Boolean).join(" ");
  const hasAperture = lockup.tiles.some((tile) => tile.glyph === "O");

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      className={classes}
      width={lockup.width}
      height={lockup.height}
      viewBox={viewBox(lockup)}
      data-brand={mark}
      data-variant={variant}
      {...(hasAperture ? { "data-aperture-scale": apertureScale } : {})}
      {...(label === undefined
        ? { "aria-hidden": true, focusable: false }
        : { role: "img", "aria-label": label })}
    >
      {title === undefined ? null : <title>{title}</title>}
      <mask
        id={maskId}
        maskUnits="userSpaceOnUse"
        x={0}
        y={0}
        width={lockup.width}
        height={lockup.height}
      >
        <rect x={0} y={0} width={lockup.width} height={lockup.height} fill="#fff" />
        {paths.bodies === "" ? null : <path d={paths.bodies} fill="#000" />}
        {paths.counters === "" ? null : <path d={paths.counters} fill="#fff" />}
      </mask>
      <path d={paths.tiles} fill="currentColor" mask={`url(#${maskId})`} />
    </svg>
  );
}

/**
 * The DROP wordmark: D, R, O, P as four tiles with the letterforms knocked out, the O a circle
 * among three sharp squares.
 */
export function DropWordmark({ size = DEFAULT_MODULE_SIZE, ...props }: BrandMarkProps) {
  const geometry = brandGeometry(size);
  return <BrandLockup mark="wordmark" geometry={geometry} lockup={geometry.wordmark} {...props} />;
}
