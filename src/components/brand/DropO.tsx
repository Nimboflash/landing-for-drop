"use client";

import { BrandLockup, type BrandMarkProps } from "./DropWordmark";
import { DEFAULT_MODULE_SIZE, brandGeometry } from "./geometry";

export interface DropOProps extends BrandMarkProps {
  /**
   * The aperture, as a multiple of its resting inner radius.
   *
   * `1` rests. The loader pulses between `APERTURE_PULSE_MIN` and `APERTURE_PULSE_MAX` while
   * D/R/P settle, then drives this far past `1` so the aperture becomes the portal (brief §7.1) —
   * so the prop is continuous and unbounded above, not a three-state switch. Once the aperture
   * reaches the tile's edge the ring is gone and the tile is fully consumed, which is what the
   * expansion looks like from the flat mark's side.
   */
  apertureScale?: number;
}

/**
 * The O — "one shape, endless possibilities". A circular tile with the aperture knocked out of
 * its centre, on its own.
 */
export function DropO({
  size = DEFAULT_MODULE_SIZE,
  apertureScale = 1,
  ...props
}: DropOProps) {
  const geometry = brandGeometry(size);
  return (
    <BrandLockup
      mark="o"
      geometry={geometry}
      lockup={geometry.oMark}
      apertureScale={apertureScale}
      {...props}
    />
  );
}
