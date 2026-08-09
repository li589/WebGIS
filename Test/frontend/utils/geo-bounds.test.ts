import { describe, expect, it } from "vitest";

import {
  isGlobalMapViewport,
  lngSpanDegrees,
  normalizeLngBounds,
} from "@/utils/geo-bounds";

describe("geo-bounds global viewport helpers", () => {
  it("lngSpanDegrees handles antimeridian wrap", () => {
    expect(lngSpanDegrees(170, -170)).toBe(20);
    expect(lngSpanDegrees(-180, 180)).toBe(360);
  });

  it("isGlobalMapViewport detects near-global bbox", () => {
    expect(isGlobalMapViewport({ west: -180, east: 180 })).toBe(true);
    expect(isGlobalMapViewport({ west: 100, east: 140 })).toBe(false);
    expect(isGlobalMapViewport(null)).toBe(false);
  });

  it("normalizeLngBounds closes near-global slit to world", () => {
    expect(normalizeLngBounds(-170, 170)).toEqual({ west: -180, east: 180 });
  });
});
