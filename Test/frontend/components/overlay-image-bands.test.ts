/**
 * overlay 条带化判据回归（2026-08-23）。
 *
 * isMercatorLinearPng：后端 _reproject_to_mercator_linear 产物（行按
 * Mercator y 均匀，如 smap-aux-* 全球层 1440x1440）不得条带化——曾把
 * Mercator 线性行误当等纬度行切带导致南北大范围拉伸错位。
 */
import { describe, expect, it } from "vitest";

import {
  isMercatorLinearPng,
  needsBanding,
} from "@/components/map/overlay-image-bands";

describe("overlay banding 判据", () => {
  it("等经纬网格（thematic 中国层 256x176）→ 需要条带化", () => {
    const bounds: [number, number, number, number] = [
      72.87, 14.87, 137.13, 59.13,
    ];
    expect(needsBanding(bounds)).toBe(true);
    expect(isMercatorLinearPng(bounds, 256, 176)).toBe(false);
  });

  it("Mercator 线性网格（smap-aux 全球层 1440x1440）→ 不得条带化", () => {
    const bounds: [number, number, number, number] = [
      -180, -85.0511287798066, 180, 85.0511287798066,
    ];
    expect(needsBanding(bounds)).toBe(true); // 跨度大，但…
    expect(isMercatorLinearPng(bounds, 1440, 1440)).toBe(true); // …Mercator 线性，跳过
  });

  it("GPCP 全球 Mercator 线性网格（720x720）→ 不得条带化", () => {
    const bounds: [number, number, number, number] = [
      -180, -85.0511287798066, 180, 85.0511287798066,
    ];
    // GPCP 导出器 target_resolution=0.5 产出 720x720；旧判据把正方形
    // 误判为等纬，进入条带化后图层空白/错位。
    expect(isMercatorLinearPng(bounds, 720, 720)).toBe(true);
  });

  it("等经纬全球层（旧格式 1440x720）→ 需要条带化", () => {
    const bounds: [number, number, number, number] = [-180, -90, 180, 90];
    expect(isMercatorLinearPng(bounds, 1440, 720)).toBe(false);
  });

  it("小跨度图层不触发条带化", () => {
    expect(needsBanding([100, 20, 110, 25])).toBe(false);
  });

  it("CLCD 中国层（2005x1152 等经纬）→ 需要条带化", () => {
    const bounds: [number, number, number, number] = [
      73.486, 18.16, 135.087, 53.561,
    ];
    expect(isMercatorLinearPng(bounds, 2005, 1152)).toBe(false);
  });
});
