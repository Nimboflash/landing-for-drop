"use client";

import { BrandLockup, type BrandMarkProps } from "./DropWordmark";
import { DEFAULT_MODULE_SIZE, brandGeometry } from "./geometry";

/**
 * The primary logo: the 4×2 storefront lockup — the wordmark row over the symbol row, on one
 * grid, one module gap apart. This is the mark on the back of a menu card and on the footer.
 */
export function DropPrimaryLogo({ size = DEFAULT_MODULE_SIZE, ...props }: BrandMarkProps) {
  const geometry = brandGeometry(size);
  return (
    <BrandLockup mark="primary-logo" geometry={geometry} lockup={geometry.primaryLogo} {...props} />
  );
}
