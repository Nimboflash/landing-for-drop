/**
 * Tracks coverflow field geometry — the pure helpers behind the jewel-case carousel.
 *
 * These functions had no unit coverage anywhere: they are exported from the scene but consumed
 * only inside its own render, so nothing was pinning their behaviour. `ringOffset` in particular
 * is worth pinning, because the property that matters (every track has neighbours, no two land on
 * the same slot) is easy to break with an innocent-looking change to the modulo.
 *
 * Nothing here asserts a transform, a pixel or a CSS value — those belong to manual visual QA.
 */

import { describe, expect, it } from "vitest";

import { ringOffset } from "@/components/scenes/TracksScene";

/** Playlist lengths worth exercising: the schema's minimum, an even count, and W04's own 11. */
const COUNTS = [3, 4, 5, 11] as const;

const range = (n: number) => Array.from({ length: n }, (_, i) => i);

describe("ringOffset", () => {
  it("puts the active track at the centre of the field, at every count", () => {
    for (const count of COUNTS) {
      for (const active of range(count)) {
        expect(ringOffset(active, active, count)).toBe(0);
      }
    }
  });

  it("never lands two tracks on the same slot", () => {
    // This is the property that makes the field paintable at all: the map from index to slot has
    // to be injective, or two jewel cases would occupy one position.
    for (const count of COUNTS) {
      for (const active of range(count)) {
        const offsets = range(count).map((index) => ringOffset(index, active, count));
        expect(new Set(offsets).size).toBe(count);
      }
    }
  });

  it("gives every position a neighbour on both sides — including the ends", () => {
    /*
     * The reason this helper exists. With a plain `index - activeIndex`, the first track has
     * nothing to its left and the last nothing to its right, so the coverflow collapses from five
     * cases to three at both ends of the playlist.
     */
    for (const count of COUNTS) {
      for (const active of range(count)) {
        const offsets = range(count).map((index) => ringOffset(index, active, count));
        expect(offsets.some((offset) => offset === 1)).toBe(true);
        expect(offsets.some((offset) => offset === -1)).toBe(true);
      }
    }
  });

  it("takes the shortest way round, so no case travels further than half the playlist", () => {
    for (const count of COUNTS) {
      for (const active of range(count)) {
        for (const index of range(count)) {
          expect(Math.abs(ringOffset(index, active, count))).toBeLessThanOrEqual(
            Math.floor(count / 2),
          );
        }
      }
    }
  });

  it("wraps the ends, which is the whole point", () => {
    // 11 tracks, sitting on the first: the case to its left is the LAST track, not empty space.
    expect(ringOffset(10, 0, 11)).toBe(-1);
    // …and sitting on the last, the case to its right is the first.
    expect(ringOffset(0, 10, 11)).toBe(1);
  });

  it("is safe for degenerate counts rather than dividing by zero", () => {
    expect(ringOffset(0, 0, 0)).toBe(0);
    expect(ringOffset(3, 1, -2)).toBe(0);
    expect(ringOffset(0, 0, 1)).toBe(0);
  });
});
