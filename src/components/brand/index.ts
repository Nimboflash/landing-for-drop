/**
 * The DROP identity as geometry.
 *
 * `geometry.ts` is the single source of every dimension; the components only paint what it
 * returns. `DropLogoMaterial3D` (brief §4) is the loader's own material scene and does not live
 * here — it consumes this module's geometry rather than redrawing it.
 */

export { BrandLockup, DropWordmark, type BrandMarkProps, type BrandVariant } from "./DropWordmark";
export { DropSymbolRow } from "./DropSymbolRow";
export { DropPrimaryLogo } from "./DropPrimaryLogo";
export { DropO, type DropOProps } from "./DropO";

export {
  APERTURE_PULSE_MAX,
  APERTURE_PULSE_MIN,
  DEFAULT_MODULE_SIZE,
  REFERENCE,
  X_UNITS,
  apertureRadius,
  brandGeometry,
  drawnApertureRadius,
  glyphBodyPath,
  glyphCounterPath,
  lockupPaths,
  rLegPolygon,
  tilePath,
  viewBox,
  type BrandGeometry,
  type Glyph,
  type Lockup,
  type LockupPaths,
  type Point,
  type Tile,
  type TileShape,
} from "./geometry";
