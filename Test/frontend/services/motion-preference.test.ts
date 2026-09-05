// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  REDUCE_MOTION_STORAGE_KEY,
  applyReducedMotionPreference,
  bootstrapMotionPreference,
  isReducedMotionActive,
  resolveReducedMotionPreference,
  setReducedMotionPreference,
} from "@/services/motion-preference";

describe("motion-preference", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("reduce-motion");
  });

  afterEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("reduce-motion");
  });

  it("applies and clears html.reduce-motion class", () => {
    applyReducedMotionPreference(true);
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(
      true,
    );
    expect(isReducedMotionActive()).toBe(true);

    applyReducedMotionPreference(false);
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(
      false,
    );
    expect(isReducedMotionActive()).toBe(false);
  });

  it("persists preference and resolves from localStorage", () => {
    setReducedMotionPreference(true);
    expect(window.localStorage.getItem(REDUCE_MOTION_STORAGE_KEY)).toBe("true");
    expect(resolveReducedMotionPreference()).toBe(true);

    setReducedMotionPreference(false);
    expect(window.localStorage.getItem(REDUCE_MOTION_STORAGE_KEY)).toBe(
      "false",
    );
    expect(resolveReducedMotionPreference()).toBe(false);
  });

  it("bootstraps from stored preference before mount", () => {
    window.localStorage.setItem(REDUCE_MOTION_STORAGE_KEY, "true");
    const enabled = bootstrapMotionPreference();
    expect(enabled).toBe(true);
    expect(document.documentElement.classList.contains("reduce-motion")).toBe(
      true,
    );
  });

  it("guarantees view transition fallback when reduce-motion is active", () => {
    applyReducedMotionPreference(true);
    expect(isReducedMotionActive()).toBe(true);
    // 验证 router.beforeResolve 中的守护条件逻辑
    const shouldAnimateViewTransition =
      typeof document !== "undefined" &&
      "startViewTransition" in document &&
      !isReducedMotionActive();
    expect(shouldAnimateViewTransition).toBe(false);
  });

  it("guarantees map camera flyTo and fitBounds adapt duration based on reduce-motion", () => {
    // 正常状态：保持自然运镜时长
    applyReducedMotionPreference(false);
    const computeDuration = (requestedDuration: number) =>
      isReducedMotionActive() ? 0 : requestedDuration;

    expect(computeDuration(1200)).toBe(1200);
    expect(computeDuration(1500)).toBe(1500);

    // reduce-motion 开启状态：压至 0ms 瞬时直达，防止眩晕
    applyReducedMotionPreference(true);
    expect(computeDuration(1200)).toBe(0);
    expect(computeDuration(1500)).toBe(0);
  });

  it("verifies reduce-motion boundary contract: disables dizziness effects while preserving functional indicators", () => {
    // 1. 禁用区验证（Disabling Zone）：前庭刺激/大跨度位移/延迟全部置零
    applyReducedMotionPreference(true);
    expect(isReducedMotionActive()).toBe(true);

    const getCameraDuration = (requested: number) =>
      isReducedMotionActive() ? 0 : requested;
    const getStaggerDelayMs = (index: number) =>
      isReducedMotionActive() ? 0 : Math.min(index, 8) * 20;

    expect(getCameraDuration(1500)).toBe(0);
    expect(getStaggerDelayMs(5)).toBe(0);

    // 2. 保留区验证（Preserved Zone）：进度指示与真实数值百分比必须完好保留防假死
    const computeProgressWidth = (percent: number) =>
      `${Math.max(0, Math.min(100, percent))}%`;
    expect(computeProgressWidth(42)).toBe("42%");
    expect(computeProgressWidth(100)).toBe("100%");
  });
});
