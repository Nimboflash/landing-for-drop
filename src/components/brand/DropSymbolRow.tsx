"use client";

import { BrandLockup, type BrandMarkProps } from "./DropWordmark";
import { DEFAULT_MODULE_SIZE, brandGeometry } from "./geometry";

/**
 * The symbol row: the teeth/line mark, the Persian alef in the circle that answers the Latin O,
 * the diagonal bar, and the chevron. The second row of the storefront lockup, usable on its own.
 */
export function DropSymbolRow({ size = DEFAULT_MODULE_SIZE, ...props }: BrandMarkProps) {
  const geometry = brandGeometry(size);
  return (
    <BrandLockup mark="symbol-row" geometry={geometry} lockup={geometry.symbolRow} {...props} />
  );
}
