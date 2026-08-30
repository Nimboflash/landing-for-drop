/**
 * Brand geometry — pure math only.
 *
 * Everything here is asserted against the geometry module's public API: the construction
 * constants from brief §4 and the brand deck, the reference-photograph tuning, and the numbers
 * `brandGeometry` derives from them. No React trees, no CSS class names, no SVG path strings —
 * path data is a drawing, and the way it is verified is by eye against the two reference
 * photographs, not by string comparison.
 *
 * Expected values come from the brief, the brand deck, or the measurements recorded in
 * `REFERENCE` — never from re-running the implementation's own arithmetic.
 */

import { describe, expect, it } from "vitest";

import {
  APERTURE_PULSE_MAX,
  APERTURE_PULSE_MIN,
  X_UNITS,
  apertureRadius,
  brandGeometry,
  drawnApertureRadius,
  rLegPolygon,
  type BrandGeometry,
  type Glyph,
  type Lockup,
  type Point,
} from "@/components/brand/geometry";

/** Two arbitrary rendered sizes with an awkward, non-round ratio between them. */
const SMALL_MODULE = 24;
const LARGE_MODULE = 84;
const SCALE = LARGE_MODULE / SMALL_MODULE;

/** Half a module, by definition of the construction unit. */
const X_AT_SMALL = SMALL_MODULE / X_UNITS.moduleSize;

/** Every number reachable from a geometry object, with the path that reached it. */
function numericLeaves(value: unknown, path = ""): [string, number][] {
  if (typeof value === "number") return [[path, value]];
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => numericLeaves(item, `${path}[${index}]`));
  }
  if (value !== null && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) =>
      numericLeaves(item, path === "" ? key : `${path}.${key}`),
    );
  }
  return [];
}

function glyphsOf(lockup: Lockup): Glyph[] {
  return lockup.tiles.map((tile) => tile.glyph);
}

/** Perpendicular distance from a point to the line through `a` and `b`. */
function distanceToLine(point: Point, a: Point, b: Point): number {
  const [px, py] = point;
  const [ax, ay] = a;
  const [bx, by] = b;
  const [dx, dy] = [bx - ax, by - ay];
  return Math.abs(dx * (ay - py) - (ax - px) * dy) / Math.hypot(dx, dy);
}

describe("construction system (brief §4 + brand deck stroke spec)", () => {
  it("is modular on a unit X: modules are 2X, spacing is X", () => {
    expect(X_UNITS.moduleSize).toBe(2);
    expect(X_UNITS.moduleSpacing).toBe(1);
  });

  it("puts the O at 2X outside and X inside", () => {
    expect(X_UNITS.oOuterDiameter).toBe(2);
    expect(X_UNITS.oInnerDiameter).toBe(1);
  });

  it("carries the deck's stroke spec: symbol strokes X/3, R leg X/3, P bowl 2X/3", () => {
    expect(X_UNITS.symbolStroke).toBeCloseTo(1 / 3, 10);
    expect(X_UNITS.rLegStroke).toBeCloseTo(1 / 3, 10);
    expect(X_UNITS.pBowlHeight).toBeCloseTo(2 / 3, 10);
  });
});

describe("one size prop scales the whole lockup", () => {
  it("scales every derived dimension by the same factor, with no drift", () => {
    const small = numericLeaves(brandGeometry(SMALL_MODULE));
    const large = numericLeaves(brandGeometry(LARGE_MODULE));

    expect(large.map(([key]) => key)).toEqual(small.map(([key]) => key));
    expect(small.length).toBeGreaterThan(40);

    for (const [index, [key, value]] of small.entries()) {
      const [, scaled] = large[index];
      expect(scaled / SCALE, `${key} drifted`).toBeCloseTo(value, 10);
    }
  });

  it("defines X as half a module", () => {
    expect(brandGeometry(SMALL_MODULE).x).toBeCloseTo(X_AT_SMALL, 10);
    expect(brandGeometry(SMALL_MODULE).module).toBe(SMALL_MODULE);
  });
});

describe("the wordmark row", () => {
  const geometry = brandGeometry(SMALL_MODULE);

  it("spells DROP", () => {
    expect(glyphsOf(geometry.wordmark)).toEqual(["D", "R", "O", "P"]);
  });

  it("is four modules wide plus three gaps", () => {
    const { tiles, width, height } = geometry.wordmark;
    expect(width).toBeCloseTo(tiles.length * geometry.module + 3 * geometry.spacing, 10);
    expect(height).toBe(geometry.module);
  });

  it("sits every tile on the same baseline, one pitch apart", () => {
    const { tiles } = geometry.wordmark;
    for (const [index, tile] of tiles.entries()) {
      expect(tile.y).toBe(0);
      expect(tile.size).toBe(geometry.module);
      if (index > 0) {
        expect(tile.x - tiles[index - 1].x).toBeCloseTo(geometry.pitch, 10);
      }
    }
  });

  it("leaves exactly one module gap of `spacing` between neighbours", () => {
    const { tiles } = geometry.wordmark;
    for (let index = 1; index < tiles.length; index += 1) {
      const gap = tiles[index].x - (tiles[index - 1].x + tiles[index - 1].size);
      expect(gap).toBeCloseTo(geometry.spacing, 10);
    }
  });
});

describe("the symbol row", () => {
  const geometry = brandGeometry(SMALL_MODULE);

  it("runs teeth mark, alef, diagonal bar, chevron", () => {
    expect(glyphsOf(geometry.symbolRow)).toEqual(["teeth", "alef", "diagonal", "chevron"]);
  });

  it("shares the wordmark's row width so the two stack on one grid", () => {
    expect(geometry.symbolRow.width).toBe(geometry.wordmark.width);
  });
});

describe("the primary logo", () => {
  const geometry = brandGeometry(SMALL_MODULE);
  const { tiles } = geometry.primaryLogo;

  it("is a 4×2 lockup: the wordmark over the symbol row", () => {
    expect(tiles).toHaveLength(8);
    expect(tiles.slice(0, 4).map((tile) => tile.glyph)).toEqual(glyphsOf(geometry.wordmark));
    expect(tiles.slice(4).map((tile) => tile.glyph)).toEqual(glyphsOf(geometry.symbolRow));
  });

  it("aligns the two rows column for column, one spacing apart", () => {
    for (let column = 0; column < 4; column += 1) {
      expect(tiles[column + 4].x).toBeCloseTo(tiles[column].x, 10);
      expect(tiles[column + 4].y - tiles[column].y).toBeCloseTo(geometry.pitch, 10);
    }
    expect(geometry.primaryLogo.height).toBeCloseTo(2 * geometry.module + geometry.spacing, 10);
  });
});

describe("sharp corners are the rule; circles are the exception", () => {
  const geometry = brandGeometry(SMALL_MODULE);

  it("makes only the O and the alef tile circular", () => {
    const circular = geometry.primaryLogo.tiles
      .filter((tile) => tile.shape === "circle")
      .map((tile) => tile.glyph);
    expect(circular).toEqual(["O", "alef"]);
  });

  it("makes every other tile a sharp square", () => {
    const square = geometry.primaryLogo.tiles
      .filter((tile) => tile.shape === "square")
      .map((tile) => tile.glyph);
    expect(square).toEqual(["D", "R", "P", "teeth", "diagonal", "chevron"]);
  });
});

describe("the O", () => {
  const geometry = brandGeometry(SMALL_MODULE);

  it("is one module across", () => {
    expect(geometry.oOuterRadius * 2).toBe(geometry.module);
    expect(geometry.oOuterRadius * 2).toBeCloseTo(X_UNITS.oOuterDiameter * geometry.x, 10);
  });

  it("draws the aperture from the reference photograph, not the construction math", () => {
    // Both supplied photographs measure the aperture at 0.30 of the outer diameter; the
    // construction system would put it at 0.50. The brief resolves that in the photo's favour.
    expect(geometry.oRestingInnerRadius / geometry.oOuterRadius).toBeCloseTo(0.3, 10);
    expect(geometry.oRestingInnerRadius).toBeLessThan(geometry.oConstructionInnerRadius);
    expect(geometry.oConstructionInnerRadius * 2).toBeCloseTo(X_UNITS.oInnerDiameter * geometry.x, 10);
  });

  it("stands alone as a one-tile lockup", () => {
    expect(glyphsOf(geometry.oMark)).toEqual(["O"]);
    expect(geometry.oMark.width).toBe(geometry.module);
    expect(geometry.oMark.height).toBe(geometry.module);
  });
});

describe("the O aperture scale", () => {
  const geometry = brandGeometry(SMALL_MODULE);

  it("rests at 1", () => {
    expect(apertureRadius(geometry, 1)).toBe(geometry.oRestingInnerRadius);
  });

  it("brackets the resting radius across the loader's pulse", () => {
    expect(APERTURE_PULSE_MIN).toBe(0.84);
    expect(APERTURE_PULSE_MAX).toBe(1.08);
    expect(apertureRadius(geometry, APERTURE_PULSE_MIN)).toBeLessThan(geometry.oRestingInnerRadius);
    expect(apertureRadius(geometry, APERTURE_PULSE_MAX)).toBeGreaterThan(
      geometry.oRestingInnerRadius,
    );
  });

  it("maps monotonically and continuously onto the inner radius from the pulse to the portal", () => {
    const samples = 600;
    const from = APERTURE_PULSE_MIN;
    const to = 6;
    let previous = apertureRadius(geometry, from);
    let biggestStep = 0;

    for (let step = 1; step <= samples; step += 1) {
      const scale = from + ((to - from) * step) / samples;
      const radius = apertureRadius(geometry, scale);
      expect(radius, `aperture went backwards at scale ${scale}`).toBeGreaterThan(previous);
      biggestStep = Math.max(biggestStep, radius - previous);
      previous = radius;
    }

    // no jump anywhere in the range: the portal has to open smoothly, not snap
    expect(biggestStep).toBeLessThan(geometry.oRestingInnerRadius * 0.05);
  });

  it("opens past the tile so the aperture can become the portal", () => {
    expect(apertureRadius(geometry, 6)).toBeGreaterThan(geometry.oOuterRadius);
    // painted into the flat mark it stops at the tile edge — by then the ring is gone
    expect(drawnApertureRadius(geometry, 6)).toBe(geometry.oOuterRadius);
    expect(drawnApertureRadius(geometry, 1)).toBe(geometry.oRestingInnerRadius);
  });

  it("closes rather than inverting below zero", () => {
    expect(apertureRadius(geometry, 0)).toBe(0);
    expect(apertureRadius(geometry, -2)).toBe(0);
  });
});

describe("stroke weights", () => {
  const geometry = brandGeometry(LARGE_MODULE);

  it("draws stems and symbol strokes at the 0.31X the sign is cut at", () => {
    // Measured on both photographs: D stem 0.313X, R stem 0.310X, P stem 0.313X, alef 0.30X.
    expect(geometry.stroke / geometry.x).toBeCloseTo(0.31, 10);
  });

  it("stays within a hair of the deck's nominal X/3", () => {
    const nominal = X_UNITS.symbolStroke * geometry.x;
    expect(Math.abs(geometry.stroke - nominal) / nominal).toBeLessThan(0.1);
  });

  it("draws the R and P bowls 2X/3 deep", () => {
    expect(geometry.bowlHeight).toBeCloseTo(X_UNITS.pBowlHeight * geometry.x, 10);
  });

  it("keeps horizontals optically lighter than verticals, but not by much", () => {
    expect(geometry.barStroke).toBeLessThan(geometry.stroke);
    expect(geometry.barStroke).toBeGreaterThan(geometry.stroke * 0.7);
  });

  it("fits a letterform inside half its module", () => {
    expect(geometry.capHeight).toBeLessThanOrEqual(geometry.x);
    expect(geometry.capHeight).toBeGreaterThan(geometry.x * 0.9);
  });
});

describe("the R leg", () => {
  const geometry: BrandGeometry = brandGeometry(LARGE_MODULE);
  const rTile = geometry.wordmark.tiles[1];
  const leg = rLegPolygon(geometry, rTile);

  it("carries the deck's stroke weight measured perpendicular to the shear", () => {
    // The leg is sheared, so its horizontal cross-section is wider than its weight. The weight
    // is the distance from a corner on one long edge to the line of the other.
    const [innerTop, outerTop, outerFoot, innerFoot] = leg;
    expect(distanceToLine(innerTop, outerTop, outerFoot)).toBeCloseTo(geometry.stroke, 6);
    expect(distanceToLine(outerFoot, innerTop, innerFoot)).toBeCloseTo(geometry.stroke, 6);
  });

  it("is wider horizontally than its weight, because it leans", () => {
    const [innerTop, outerTop] = leg;
    expect(outerTop[0] - innerTop[0]).toBeGreaterThan(geometry.stroke);
  });

  it("tucks its head under the bowl and lands on the baseline", () => {
    const [innerTop, , outerFoot] = leg;
    const letterTop = rTile.y + (rTile.size - geometry.capHeight) / 2;
    expect(innerTop[1]).toBeCloseTo(letterTop + geometry.bowlHeight - geometry.barStroke, 10);
    expect(innerTop[1]).toBeLessThan(letterTop + geometry.bowlHeight);
    expect(outerFoot[1]).toBeCloseTo(letterTop + geometry.capHeight, 10);
  });

  it("stays inside its tile", () => {
    for (const [px, py] of leg) {
      expect(px).toBeGreaterThanOrEqual(rTile.x);
      expect(px).toBeLessThanOrEqual(rTile.x + rTile.size);
      expect(py).toBeGreaterThanOrEqual(rTile.y);
      expect(py).toBeLessThanOrEqual(rTile.y + rTile.size);
    }
  });
});
