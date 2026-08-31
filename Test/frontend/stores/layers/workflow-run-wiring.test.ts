/**
 * 安审 2026-08-22：workflow-run 断线回归锁定（fdd6833 同类事故）。
 *
 * 背景：workflow-runner.ts 定义的 autoAttachProductsForNewLayer 在
 * workflow-run-domain.ts 被解构却未透出（return 漏字段），导致
 * selectors.useWorkflowRun() 拿不到该方法——LayerSidebar.addCatalogItem
 * 每次从目录添加图层都会调用它，断线即 TypeError 整页错误面板。
 * eslint no-unused-vars 信号暴露了这条断线；此测试锁死全链路透传。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";

vi.mock("@/stores/weather-tile-manager", () => ({
  useWeatherTileManager: () => ({
    setLayerActive: vi.fn(),
    clearLayer: vi.fn(),
    setViewport: vi.fn(),
    getLayerStatus: () => ({
      active: false,
      cachedInViewport: 0,
      viewportTotal: 0,
      pending: 0,
      errorType: null,
      errorMessage: null,
    }),
    getMergedGeojsonForViewport: () => null,
    getDataVersion: () => 0,
    dataVersion: { value: 0 },
    statusVersion: { value: 0 },
    activityVersion: { value: 0 },
  }),
}));

vi.mock("@/services/runtime-api", () => ({
  fetchLayerCatalog: vi.fn(async () => ({ items: [] })),
  submitWorkflow: vi.fn(),
  getWorkflowRun: vi.fn(),
  getWorkflowEvents: vi.fn(),
  cancelWorkflowRun: vi.fn(),
  retryWorkflowRun: vi.fn(),
  listActiveWorkflowRuns: vi.fn(async () => []),
  listRecentSucceededRuns: vi.fn(async () => []),
  getWeatherPoint: vi.fn(),
}));

vi.mock("@/services/layer-capabilities", () => ({
  isWeatherLayerDescriptor: () => true,
  supportsMapLayerCapability: () => false,
  supportsParticleFlowCapability: () => false,
  supportsViewportDrivenRefreshCapability: () => false,
}));

vi.mock("@/components/map/weather-render", () => ({
  buildDefaultWeatherRenderHint: () => null,
}));

vi.mock("@/stores/layers/result-adapter", () => ({
  buildJobLayer: vi.fn(),
}));

import { useLayersStore } from "@/stores/layers/index";
import { useWorkflowRun } from "@/stores/layers/selectors";

describe("workflow-run 接线契约（安审 2026-08-22）", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("autoAttachProductsForNewLayer 全链路透传 runner→domain→store→selector", () => {
    const store = useLayersStore();
    expect(typeof store.autoAttachProductsForNewLayer).toBe("function");
    const run = useWorkflowRun();
    expect(typeof run.autoAttachProductsForNewLayer).toBe("function");
  });

  it("workflow-run 方法族同步在列（断线即本测试红）", () => {
    const store = useLayersStore();
    const required = [
      "runWorkflowForCatalog",
      "cancelWorkflowRunForJob",
      "retryWorkflowRunForJob",
      "cleanupAllRetryTimers",
      "restoreActiveWorkflows",
      "registerExternalWorkflowRun",
      "stopWorkflowPolling",
    ] as const;
    for (const key of required) {
      expect(typeof store[key], `store.${key} 应为 function`).toBe("function");
    }
  });
});
