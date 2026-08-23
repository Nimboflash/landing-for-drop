/**
 * DROP brand geometry — the X-unit construction system as data.
 *
 * Everything the wordmark, primary logo, symbol row and the O are drawn from lives here as
 * pure math. The components are dumb: they take a size, ask this module for numbers and path
 * data, and paint them. No component may invent a dimension of its own.
 *
 * ## Two layers, deliberately separate
 *
 * {@link X_UNITS} is the **construction system** — brief §4 plus the brand deck's stroke spec:
 * module `2X`, module spacing `X`, O outer `2X` / inner `X`, symbol-row strokes `X/3`,
 * R leg `X/3`, P bowl `2X/3`.
 *
 * {@link REFERENCE} is the **visual tuning**, measured off the two supplied photographs
 * (`handoff/01-brand/drop-final-wordmark-reference.png` and `drop-final-storefront-logo.jpg`).
 * The brief keeps both: the construction system is the grid, but the final responsive wordmark
 * is "visually tuned to match the final supplied reference". Where the two disagree the
 * photograph wins, and every deviation is named here with the measurement that produced it —
 * so no tuned number sits loose in a component.
 *
 * The deviation the brief calls out is the O: the construction math puts the aperture at `X`
 * across, half the outer diameter; both photographs measure it at 0.30 of the outer diameter.
 * The photograph wins.
 *
 * ## Scaling
 *
 * {@link brandGeometry} is the single entry point. `size` is the rendered side of one module
 * (one tile) in px, and `x = size / 2`. Every returned dimension is a multiple of `x`, so one
 * size prop scales the whole lockup with no drift.
 *
 * ## Drawing
 *
 * A tile is a solid shape with its mark knocked out of it — the sign is vinyl on glass, and the
 * header mark has to sit over scenes of any contrast without carrying a background, so the
 * knockout is a real hole. {@link lockupPaths} returns the three path strings that produce it:
 * the tiles, the mark bodies to remove, and the counters to give back. Bodies union under the
 * default nonzero rule (an R's stem, bowl and leg overlap by design); counters are restored
 * afterwards, so nothing depends on even/odd parity across overlapping siblings.
 *
 * Nothing here imports React, the DOM, or content. It is pure, deterministic math.
 */

/** Which of the eight lockup cells a tile carries. */
export type Glyph = "D" | "R" | "O" | "P" | "teeth" | "alef" | "diagonal" | "chevron";

/**
 * Tile silhouette. Sharp corners are a hard rule; a circle appears only where the physical form
 * requires one — the O, and the tile the Persian alef shares with it.
 */
export type TileShape = "square" | "circle";

/** One tile of a lockup, positioned in that lockup's own coordinate space. */
export interface Tile {
  readonly glyph: Glyph;
  readonly shape: TileShape;
  /** Left edge of the tile's bounding box. */
  readonly x: number;
  /** Top edge of the tile's bounding box. */
  readonly y: number;
  /** Tile side length — always one module. */
  readonly size: number;
}

/** A composed lockup: its intrinsic box, and the tiles inside it. */
export interface Lockup {
  readonly width: number;
  readonly height: number;
  readonly tiles: readonly Tile[];
}

/** Every dimension of the identity at one rendered size, in px. */
export interface BrandGeometry {
  /** The construction unit. One module is `2X`. */
  readonly x: number;
  /** Module (tile) side. */
  readonly module: number;
  /** Gap between adjacent modules, horizontally and vertically. */
  readonly spacing: number;
  /** Module + spacing: centre-to-centre distance between adjacent tiles. */
  readonly pitch: number;
  /** Height of a letterform inside its module. */
  readonly capHeight: number;
  /** Vertical and diagonal stroke weight — the deck's nominal `X/3`, drawn as the sign draws it. */
  readonly stroke: number;
  /** Horizontal stroke weight — optically lighter than the verticals. */
  readonly barStroke: number;
  /** Outer height of the R and P bowls: the deck's `2X/3`. */
  readonly bowlHeight: number;
  /** O outer radius — half a module. */
  readonly oOuterRadius: number;
  /** O aperture radius at rest, tuned to the reference photographs. */
  readonly oRestingInnerRadius: number;
  /** O aperture radius the construction math alone gives (`X/2`). Kept for comparison. */
  readonly oConstructionInnerRadius: number;
  /** D R O P. */
  readonly wordmark: Lockup;
  /** Teeth mark, alef in circle, diagonal bar, chevron. */
  readonly symbolRow: Lockup;
  /** The 4×2 storefront lockup: wordmark over symbol row. */
  readonly primaryLogo: Lockup;
  /** The O on its own — the loader's portal shape. */
  readonly oMark: Lockup;
}

/**
 * The construction system, in X units. Brief §4 plus the brand deck's "final logo" stroke
 * pages. These are the spec numbers, not always the drawn ones — see {@link REFERENCE}.
 */
export const X_UNITS = Object.freeze({
  /** Each core module is `2X` by `2X`. */
  moduleSize: 2,
  /** Module spacing is `X` in the construction system. */
  moduleSpacing: 1,
  /** O outer diameter is `2X`. */
  oOuterDiameter: 2,
  /** O inner diameter is `X`. */
  oInnerDiameter: 1,
  /** Symbol-row strokes are `X/3`. */
  symbolStroke: 1 / 3,
  /** The R leg is `X/3`. */
  rLegStroke: 1 / 3,
  /** The P bowl is `2X/3` deep. */
  pBowlHeight: 2 / 3,
});

/**
 * Visual tuning measured off the supplied reference photographs, in X units.
 *
 * Method: both images were thresholded and their tile and knockout runs measured in pixels, then
 * divided by the local `X` (half the local tile width) so the photographs' perspective cancels.
 * Each value carries the measurement that produced it.
 */
export const REFERENCE = Object.freeze({
  /**
   * Drawn gap between tiles. Measured 39/42/36px against ~163px tiles on the wordmark reference
   * and 35/38/33px against ~143px tiles on the storefront — 0.45X to 0.52X, i.e. half the
   * construction system's `X`. The final sign's tighter row wins over the construction grid.
   */
  moduleSpacing: 0.5,
  /**
   * Drawn aperture diameter. Measured at 46/151 and 41/134 of the outer diameter on the two
   * photographs — 0.30 both times, against the 0.50 the construction math implies. This is the
   * disagreement the brief resolves in favour of the photograph.
   */
  oInnerDiameter: 0.6,
  /**
   * Cap height of a letterform inside its `2X` tile. Measured 0.467, 0.483 and 0.475 of the
   * three square tiles' heights — 0.95X. The letters sit a touch under half the module.
   */
  capHeight: 0.95,
  /**
   * Drawn vertical stroke. The deck's nominal weight is `X/3` = 0.333X; every measurable stroke
   * on the two photographs comes in a little lighter and remarkably consistently — D stem 0.313X,
   * R stem 0.310X, P stem 0.313X, alef bar 0.30X, diagonal bar 0.293X. The photograph wins, and
   * this is what keeps the R and P counters open at the deck's `2X/3` bowl height.
   */
  stroke: 0.31,
  /**
   * Horizontal strokes as a fraction of the vertical one. Horizontals measure ~0.263X against
   * ~0.31X verticals — the usual grotesque optical correction.
   */
  horizontalStrokeRatio: 0.85,
  /** Letterform widths. Measured D 0.905X, R 0.905X, P 0.80X. */
  letterWidth: Object.freeze({ D: 0.9, R: 0.9, P: 0.8 }),
  /** R bowl width, narrower than the letter box so the leg clears it. Measured 0.83X. */
  rBowlWidth: 0.83,
  /** Side of the square box every symbol-row mark is drawn inside. Measured 0.9X–1.03X. */
  markSize: 1,
  /** Gap between the teeth mark's bar and the diamonds below it. Measured 6px at X≈78. */
  teethGap: 1 / 12,
  /** Teeth under the bar. Three, counted off the storefront photograph. */
  teethCount: 3,
});

/** Rendered module size in px when a component is given no explicit size. */
export const DEFAULT_MODULE_SIZE = 64;

/** Aperture scale at the bottom of the loader's resting pulse (brief §7.1). */
export const APERTURE_PULSE_MIN = 0.84;

/** Aperture scale at the top of the loader's resting pulse (brief §7.1). */
export const APERTURE_PULSE_MAX = 1.08;

/** Wordmark tile order — the row spells the brand, so the order is the content. */
const WORDMARK_GLYPHS: readonly Glyph[] = ["D", "R", "O", "P"];

/** Symbol-row tile order, left to right on the storefront sign. */
const SYMBOL_ROW_GLYPHS: readonly Glyph[] = ["teeth", "alef", "diagonal", "chevron"];

/**
 * The two circular tiles: the O, and the tile carrying the vertical bar the brand deck glosses
 * as the Persian الف, deliberately paired with the Latin O. Everything else is a sharp square.
 */
const CIRCULAR_GLYPHS: ReadonlySet<Glyph> = new Set<Glyph>(["O", "alef"]);

function tileShape(glyph: Glyph): TileShape {
  return CIRCULAR_GLYPHS.has(glyph) ? "circle" : "square";
}

function row(glyphs: readonly Glyph[], moduleSize: number, pitch: number, top: number): Tile[] {
  return glyphs.map((glyph, index) => ({
    glyph,
    shape: tileShape(glyph),
    x: index * pitch,
    y: top,
    size: moduleSize,
  }));
}

/**
 * Every dimension of the identity at one rendered size.
 *
 * @param size rendered side of one module (one tile) in px.
 */
export function brandGeometry(size: number = DEFAULT_MODULE_SIZE): BrandGeometry {
  const moduleSize = size;
  const x = moduleSize / X_UNITS.moduleSize;
  const spacing = x * REFERENCE.moduleSpacing;
  const pitch = moduleSize + spacing;
  const stroke = x * REFERENCE.stroke;
  const rowWidth = WORDMARK_GLYPHS.length * moduleSize + (WORDMARK_GLYPHS.length - 1) * spacing;

  return {
    x,
    module: moduleSize,
    spacing,
    pitch,
    capHeight: x * REFERENCE.capHeight,
    stroke,
    barStroke: stroke * REFERENCE.horizontalStrokeRatio,
    bowlHeight: x * X_UNITS.pBowlHeight,
    oOuterRadius: (x * X_UNITS.oOuterDiameter) / 2,
    oRestingInnerRadius: (x * REFERENCE.oInnerDiameter) / 2,
    oConstructionInnerRadius: (x * X_UNITS.oInnerDiameter) / 2,
    wordmark: {
      width: rowWidth,
      height: moduleSize,
      tiles: row(WORDMARK_GLYPHS, moduleSize, pitch, 0),
    },
    symbolRow: {
      width: rowWidth,
      height: moduleSize,
      tiles: row(SYMBOL_ROW_GLYPHS, moduleSize, pitch, 0),
    },
    primaryLogo: {
      width: rowWidth,
      height: moduleSize * 2 + spacing,
      tiles: [
        ...row(WORDMARK_GLYPHS, moduleSize, pitch, 0),
        ...row(SYMBOL_ROW_GLYPHS, moduleSize, pitch, pitch),
      ],
    },
    oMark: {
      width: moduleSize,
      height: moduleSize,
      tiles: row(["O"], moduleSize, pitch, 0),
    },
  };
}

/* ------------------------------------------------------------------ *
 * The O aperture
 * ------------------------------------------------------------------ */

/**
 * Aperture scale mapped onto the O's inner radius.
 *
 * `1` is the resting aperture. The loader pulses between {@link APERTURE_PULSE_MIN} and
 * {@link APERTURE_PULSE_MAX}, then drives the same scale far past `1` so the aperture becomes
 * the portal that swallows the viewport. So this stays linear, strictly increasing and unbounded
 * above; a negative scale clamps to a closed aperture.
 */
export function apertureRadius(geometry: BrandGeometry, apertureScale: number): number {
  return geometry.oRestingInnerRadius * Math.max(0, apertureScale);
}

/**
 * The aperture radius actually painted into the O tile, clamped to the tile.
 *
 * Once the aperture reaches the outer edge the ring is gone and the tile is fully consumed,
 * which is what the portal expansion looks like from the flat mark's side. The unclamped value
 * stays available from {@link apertureRadius} for whatever drives the portal itself.
 */
export function drawnApertureRadius(geometry: BrandGeometry, apertureScale: number): number {
  return Math.min(apertureRadius(geometry, apertureScale), geometry.oOuterRadius);
}

/* ------------------------------------------------------------------ *
 * Path primitives — every subpath is wound the same way (clockwise on
 * screen) so mark bodies union under the nonzero rule.
 * ------------------------------------------------------------------ */

/** A point in lockup space. */
export type Point = readonly [number, number];

function n(value: number): string {
  return Number(value.toFixed(4)).toString();
}

function polygon(points: readonly Point[]): string {
  return (
    points.map(([px, py], index) => `${index === 0 ? "M" : "L"}${n(px)} ${n(py)}`).join("") + "Z"
  );
}

function rect(x: number, y: number, width: number, height: number): string {
  return polygon([
    [x, y],
    [x + width, y],
    [x + width, y + height],
    [x, y + height],
  ]);
}

function circle(cx: number, cy: number, r: number): string {
  if (r <= 0) return "";
  return (
    `M${n(cx - r)} ${n(cy)}` +
    `A${n(r)} ${n(r)} 0 1 1 ${n(cx + r)} ${n(cy)}` +
    `A${n(r)} ${n(r)} 0 1 1 ${n(cx - r)} ${n(cy)}Z`
  );
}

/**
 * The DROP letter shape: flat on the left, rounded on the right, with the corner radius as large
 * as the box allows. The D's contour, the D's counter, and the R and P bowls and their counters
 * are all this one shape at different sizes — which is why the letters read as a family rather
 * than three separate drawings.
 */
function flatLeftRoundRight(x: number, y: number, width: number, height: number): string {
  if (width <= 0 || height <= 0) return "";
  const r = Math.min(width, height / 2);
  return (
    `M${n(x)} ${n(y)}` +
    `L${n(x + width - r)} ${n(y)}` +
    `A${n(r)} ${n(r)} 0 0 1 ${n(x + width)} ${n(y + r)}` +
    `L${n(x + width)} ${n(y + height - r)}` +
    `A${n(r)} ${n(r)} 0 0 1 ${n(x + width - r)} ${n(y + height)}` +
    `L${n(x)} ${n(y + height)}Z`
  );
}

/* ------------------------------------------------------------------ *
 * Letterforms
 * ------------------------------------------------------------------ */

/** Top-left corner of the `capHeight`-tall letter box, centred in its tile. */
function letterOrigin(geometry: BrandGeometry, tile: Tile, width: number): Point {
  return [tile.x + (tile.size - width) / 2, tile.y + (tile.size - geometry.capHeight) / 2];
}

/**
 * The R leg as an explicit quadrilateral.
 *
 * Exported because its weight is a spec number the brand deck states outright (`X/3`) and is
 * only checkable on the drawn shape: the leg is sheared, so its *horizontal* cross-section is
 * wider than its perpendicular weight. The horizontal cross-section that yields a perpendicular
 * `X/3` is solved by fixed-point iteration rather than guessed, so retuning the letter width or
 * the bowl height can never silently change the leg's weight.
 *
 * Its angle is set by the *visible* run — from the bowl's baseline out to the foot — and only
 * then is the head pushed a horizontal stroke further up, so it is swallowed by the bowl instead
 * of shelving out from under it. That is the junction the drawn letter makes, and the reason the
 * mark bodies are unioned rather than parity-combined. Tucking the head by lengthening the leg
 * instead would stand it up and cost the letter its diagonal.
 *
 * Wound clockwise from the junction with the bowl.
 */
export function rLegPolygon(geometry: BrandGeometry, tile: Tile): readonly Point[] {
  const width = geometry.x * REFERENCE.letterWidth.R;
  const [ox, oy] = letterOrigin(geometry, tile, width);
  const bottom = oy + geometry.capHeight;
  const rise = geometry.capHeight - geometry.bowlHeight;

  // horizontal = perpendicular / cos(angle from vertical), and the angle itself depends on the
  // horizontal width — so solve for the fixed point.
  let horizontal = geometry.stroke;
  for (let i = 0; i < 64; i += 1) {
    const run = width - horizontal - geometry.stroke;
    horizontal = geometry.stroke * Math.hypot(1, run / rise);
  }

  const slope = (width - horizontal - geometry.stroke) / rise;
  const tuck = geometry.barStroke;
  const top = oy + geometry.bowlHeight - tuck;
  const headX = ox + geometry.stroke - slope * tuck;

  return [
    [headX, top],
    [headX + horizontal, top],
    [ox + width, bottom],
    [ox + width - horizontal, bottom],
  ];
}

function bowlBody(geometry: BrandGeometry, ox: number, oy: number, width: number): string {
  return flatLeftRoundRight(ox, oy, width, geometry.bowlHeight);
}

function bowlCounter(geometry: BrandGeometry, ox: number, oy: number, width: number): string {
  return flatLeftRoundRight(
    ox + geometry.stroke,
    oy + geometry.barStroke,
    width - 2 * geometry.stroke,
    geometry.bowlHeight - 2 * geometry.barStroke,
  );
}

/* ------------------------------------------------------------------ *
 * Symbol-row marks
 * ------------------------------------------------------------------ */

/** Bar over a row of diamonds — the decorative teeth/line mark. */
function teethMark(geometry: BrandGeometry, tile: Tile): string {
  const side = geometry.x * REFERENCE.markSize;
  const gap = geometry.x * REFERENCE.teethGap;
  const toothSize = side / REFERENCE.teethCount;
  const toothRadius = toothSize / 2;
  // the bar is a horizontal stroke, so it takes the horizontal weight
  const height = geometry.barStroke + gap + toothSize;

  const ox = tile.x + (tile.size - side) / 2;
  const oy = tile.y + (tile.size - height) / 2;
  const cy = oy + geometry.barStroke + gap + toothRadius;

  let teeth = "";
  for (let i = 0; i < REFERENCE.teethCount; i += 1) {
    const cx = ox + (i + 0.5) * toothSize;
    teeth += polygon([
      [cx, cy - toothRadius],
      [cx + toothRadius, cy],
      [cx, cy + toothRadius],
      [cx - toothRadius, cy],
    ]);
  }
  return rect(ox, oy, side, geometry.barStroke) + teeth;
}

/** The Persian alef: a vertical bar, sharing the O's circular tile shape. */
function alefMark(geometry: BrandGeometry, tile: Tile): string {
  const height = geometry.x * REFERENCE.markSize;
  return rect(
    tile.x + (tile.size - geometry.stroke) / 2,
    tile.y + (tile.size - height) / 2,
    geometry.stroke,
    height,
  );
}

/** A bar of length `X` and weight `X/3` lying on the tile's rising diagonal. */
function diagonalMark(geometry: BrandGeometry, tile: Tile): string {
  const half = geometry.stroke / 2;
  const reach = (geometry.x * REFERENCE.markSize) / 2;
  const cx = tile.x + tile.size / 2;
  const cy = tile.y + tile.size / 2;
  const d = Math.SQRT1_2;
  const [ax, ay] = [d * reach, -d * reach]; // along the rising diagonal
  const [nx, ny] = [d * half, d * half]; // its normal
  return polygon([
    [cx - ax - nx, cy - ay - ny],
    [cx + ax - nx, cy + ay - ny],
    [cx + ax + nx, cy + ay + ny],
    [cx - ax + nx, cy - ay + ny],
  ]);
}

/** A mitred chevron pointing right: arms at 45°, weight `X/3`, ends butt-cut. */
function chevronMark(geometry: BrandGeometry, tile: Tile): string {
  const height = geometry.x * REFERENCE.markSize;
  // half-diagonal of the stroke: how far a 45° butt cut and a 90° mitre run out
  const k = (geometry.stroke * Math.SQRT1_2) / 2;
  const width = height / 2 + 2 * k;
  const ox = tile.x + (tile.size - width) / 2;
  const oy = tile.y + (tile.size - height) / 2;
  const mid = oy + height / 2;

  return polygon([
    [ox + 2 * k, oy],
    [ox + width, mid],
    [ox + 2 * k, oy + height],
    [ox, oy + height - 2 * k],
    [ox + height / 2 - 2 * k, mid],
    [ox, oy + 2 * k],
  ]);
}

/* ------------------------------------------------------------------ *
 * Tile paths
 * ------------------------------------------------------------------ */

/** The tile silhouette on its own — a sharp square, or a circle for the O and the alef. */
export function tilePath(tile: Tile): string {
  return tile.shape === "circle"
    ? circle(tile.x + tile.size / 2, tile.y + tile.size / 2, tile.size / 2)
    : rect(tile.x, tile.y, tile.size, tile.size);
}

/**
 * The solid mark removed from a tile. Subpaths may overlap — an R's stem, bowl and leg do — and
 * union under the nonzero rule.
 *
 * @param apertureScale only meaningful for the O; `1` is the resting aperture.
 */
export function glyphBodyPath(
  geometry: BrandGeometry,
  tile: Tile,
  apertureScale: number = 1,
): string {
  const { x, stroke, capHeight } = geometry;

  switch (tile.glyph) {
    case "D": {
      const width = x * REFERENCE.letterWidth.D;
      const [ox, oy] = letterOrigin(geometry, tile, width);
      return flatLeftRoundRight(ox, oy, width, capHeight);
    }
    case "R": {
      const width = x * REFERENCE.letterWidth.R;
      const [ox, oy] = letterOrigin(geometry, tile, width);
      return (
        rect(ox, oy, stroke, capHeight) +
        bowlBody(geometry, ox, oy, x * REFERENCE.rBowlWidth) +
        polygon(rLegPolygon(geometry, tile))
      );
    }
    case "P": {
      const width = x * REFERENCE.letterWidth.P;
      const [ox, oy] = letterOrigin(geometry, tile, width);
      return rect(ox, oy, stroke, capHeight) + bowlBody(geometry, ox, oy, width);
    }
    case "O":
      return circle(
        tile.x + tile.size / 2,
        tile.y + tile.size / 2,
        drawnApertureRadius(geometry, apertureScale),
      );
    case "teeth":
      return teethMark(geometry, tile);
    case "alef":
      return alefMark(geometry, tile);
    case "diagonal":
      return diagonalMark(geometry, tile);
    case "chevron":
      return chevronMark(geometry, tile);
  }
}

/**
 * The islands of tile given back inside a mark: the counters of D, R and P. Empty for every
 * mark that has none.
 */
export function glyphCounterPath(geometry: BrandGeometry, tile: Tile): string {
  const { x, stroke, barStroke, capHeight } = geometry;

  switch (tile.glyph) {
    case "D": {
      const width = x * REFERENCE.letterWidth.D;
      const [ox, oy] = letterOrigin(geometry, tile, width);
      return flatLeftRoundRight(
        ox + stroke,
        oy + barStroke,
        width - 2 * stroke,
        capHeight - 2 * barStroke,
      );
    }
    case "R": {
      const width = x * REFERENCE.letterWidth.R;
      const [ox, oy] = letterOrigin(geometry, tile, width);
      return bowlCounter(geometry, ox, oy, x * REFERENCE.rBowlWidth);
    }
    case "P": {
      const width = x * REFERENCE.letterWidth.P;
      const [ox, oy] = letterOrigin(geometry, tile, width);
      return bowlCounter(geometry, ox, oy, width);
    }
    default:
      return "";
  }
}

/** The three path strings a lockup is painted from. */
export interface LockupPaths {
  /** The solid tiles. */
  readonly tiles: string;
  /** The marks to knock out of them. */
  readonly bodies: string;
  /** The counters to give back inside those marks. */
  readonly counters: string;
}

/**
 * Path data for a whole lockup.
 *
 * @param apertureScale drives the O's aperture; `1` is the resting aperture.
 */
export function lockupPaths(
  geometry: BrandGeometry,
  lockup: Lockup,
  apertureScale: number = 1,
): LockupPaths {
  let tiles = "";
  let bodies = "";
  let counters = "";
  for (const tile of lockup.tiles) {
    tiles += tilePath(tile);
    bodies += glyphBodyPath(geometry, tile, apertureScale);
    counters += glyphCounterPath(geometry, tile);
  }
  return { tiles, bodies, counters };
}

/** `viewBox` for a lockup drawn in its own coordinate space. */
export function viewBox(lockup: Lockup): string {
  return `0 0 ${n(lockup.width)} ${n(lockup.height)}`;
}
