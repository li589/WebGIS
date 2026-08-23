/**
 * W3.4b：run-layers.ts（job / run-group / 物化 slice）单元测试。
 *
 * 覆盖核心路径：
 *  - workflowSummary 状态聚合（idle/active/mixed/failed/succeeded）
 *  - emitWorkflowProgressTimeSeek（W3.6 时间轴 seek 提示发射与去重）
 *  - removeJobLayerById / syncJobLayerToActiveLayer / upsertJobLayer
 *  - buildWorkflowPayloadForCatalog
 *  - 渐进物化：formatProgressiveSyncMessage / applyProgressiveSyncToJob / syncProgressiveBlockOverlays
 *  - attachAlgorithmProductOverlays（组内绑定 / 游离并入 / OMEGA 归并 / 空态横幅 / 409 容忍）
 *  - reconcileOmegaBlockLayers / reorderLayers / run group 生命周期
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createRunLayersSlice,
  type RunLayersSliceDeps,
} from "@/stores/layers/run-layers";
import { extractOverlayImportsFromResultRefs } from "@/stores/layers/result-adapter";
import {
  isOverlayDismissed,
  isRunDismissed,
} from "@/stores/layers/workspace-persist";
import { materializeWorkflowMapLayers } from "@/services/runtime-api";
import { productTagLabel } from "@/utils/workflow-expected-outputs";
import { WORKFLOW_COPY } from "@/ui-copy/workflow";
import type {
  ActiveLayer,
  ActiveRunLayerGroup,
  JobLayerItem,
} from "@/stores/layers/types";

vi.mock("@/services/runtime-api", () => ({
  materializeWorkflowMapLayers: vi.fn(),
}));

vi.mock("@/stores/log", () => ({
  safeLog: vi.fn(),
}));

let mockOutputEntries: Array<{ name: string; localId: string }> = [];

vi.mock("@/stores/workflow-output-layers", () => ({
  useWorkflowOutputLayersStore: () => ({ entries: mockOutputEntries }),
}));

vi.mock("@/stores/layers/result-adapter", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return { ...actual, extractOverlayImportsFromResultRefs: vi.fn(() => []) };
});

vi.mock("@/stores/layers/workspace-persist", () => ({
  isOverlayDismissed: vi.fn(() => false),
  isRunDismissed: vi.fn(() => false),
}));

type MaterializeResult = Awaited<
  ReturnType<typeof materializeWorkflowMapLayers>
>;
type MaterializedLayer = MaterializeResult["layers"][number];

function mockMaterialize(layers: Array<Partial<MaterializedLayer>>) {
  vi.mocked(materializeWorkflowMapLayers).mockResolvedValue({
    layers: layers as MaterializedLayer[],
  } as MaterializeResult);
}

// ── Harness ───────────────────────────────────────────────────────────────────

let activeLayers: ActiveLayer[];
let idSeq = 0;
let sidebarView: "empty" | "library" | "active";

function makeLayer(overrides: Partial<ActiveLayer> = {}): ActiveLayer {
  idSeq += 1;
  return {
    instanceId: `inst-${idSeq}`,
    catalogId: `cat-${idSeq}`,
    name: `Layer ${idSeq}`,
    visible: true,
    opacity: 1,
    order: activeLayers.length,
    isAdminBoundary: false,
    dataState: "catalog",
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobLayerItem> = {}): JobLayerItem {
  return {
    jobId: "run-1",
    name: "测试工作流",
    commandType: "analysis",
    status: "running",
    progress: 10,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    message: "",
    metrics: [],
    ...overrides,
  };
}

function makeGroup(
  overrides: Partial<ActiveRunLayerGroup> = {},
): ActiveRunLayerGroup {
  idSeq += 1;
  return {
    groupId: `grp-${idSeq}`,
    runId: "",
    title: "计算组",
    status: "computing",
    memberInstanceIds: [],
    dissolvable: false,
    sourceLayerId: "src-layer",
    workflowId: "wf-x",
    progress: 0,
    message: "等待计算…",
    ...overrides,
  };
}

interface SetupResult {
  slice: ReturnType<typeof createRunLayersSlice>;
  calls: {
    addLayer: ReturnType<typeof vi.fn>;
    removeLayer: ReturnType<typeof vi.fn>;
    setSelectedInstanceId: ReturnType<typeof vi.fn>;
    setSidebarView: ReturnType<typeof vi.fn>;
    rememberTrackedWorkflowRun: ReturnType<typeof vi.fn>;
    forgetTrackedWorkflowRun: ReturnType<typeof vi.fn>;
    scheduleWorkspacePersist: ReturnType<typeof vi.fn>;
    isLocalSubmitJobId: ReturnType<typeof vi.fn>;
  };
}

function setup(): SetupResult {
  activeLayers = [];
  idSeq = 0;
  sidebarView = "library";
  let sliceRef: ReturnType<typeof createRunLayersSlice> | null = null;
  const calls = {
    addLayer: vi.fn(),
    removeLayer: vi.fn(),
    setSelectedInstanceId: vi.fn(),
    setSidebarView: vi.fn((view: "empty" | "library" | "active") => {
      sidebarView = view;
    }),
    rememberTrackedWorkflowRun: vi.fn(),
    forgetTrackedWorkflowRun: vi.fn(),
    scheduleWorkspacePersist: vi.fn(),
    isLocalSubmitJobId: vi.fn(() => false),
  };
  const deps: RunLayersSliceDeps = {
    getActiveLayers: () => activeLayers,
    addLayer: (
      catalogId: string,
      _isAdminBoundary?: boolean,
      jobLayer?: JobLayerItem,
    ) => {
      calls.addLayer(catalogId, _isAdminBoundary, jobLayer);
      activeLayers.push(makeLayer({ catalogId, jobLayer, dataState: "real" }));
    },
    removeLayer: (instanceId: string) => {
      calls.removeLayer(instanceId);
      const idx = activeLayers.findIndex((l) => l.instanceId === instanceId);
      if (idx < 0) return;
      const layer = activeLayers[idx]!;
      activeLayers.splice(idx, 1);
      if (layer.runGroupId && sliceRef) {
        const g = sliceRef.runLayerGroups.value.find(
          (x) => x.groupId === layer.runGroupId,
        );
        if (g) {
          g.memberInstanceIds = g.memberInstanceIds.filter(
            (id) => id !== instanceId,
          );
          if (!g.memberInstanceIds.length) {
            sliceRef.runLayerGroups.value =
              sliceRef.runLayerGroups.value.filter(
                (x) => x.groupId !== g.groupId,
              );
          }
        }
      }
    },
    assignLayerAccent: () => ({
      accentColor: "#3b82f6",
      accentGlow: "rgba(59,130,246,.4)",
      chipTone: "blue",
    }),
    setSelectedInstanceId: calls.setSelectedInstanceId,
    getSidebarView: () => sidebarView,
    setSidebarView: calls.setSidebarView,
    getMapCenter: () => ({ lng: 116.4, lat: 39.9 }),
    getCurrentHour: () => 12,
    forgetTrackedWorkflowRun: calls.forgetTrackedWorkflowRun,
    rememberTrackedWorkflowRun: calls.rememberTrackedWorkflowRun,
    isLocalSubmitJobId: calls.isLocalSubmitJobId,
    scheduleWorkspacePersist: calls.scheduleWorkspacePersist,
    genInstanceId: () => `inst-${++idSeq}`,
    addImportedRasterLayer: (name, overlayLayerId, bounds, options) => {
      const layer = makeLayer({
        catalogId: overlayLayerId,
        name,
        dataState: "imported",
        importedRaster: {
          overlayLayerId,
          bounds,
          fileName: name,
          sourceCrs: options?.sourceCrs,
          nativeStep: options?.nativeStep ?? null,
          timeList: options?.timeList,
          followPolicy: options?.followPolicy,
        },
      });
      activeLayers.push(layer);
      return layer;
    },
  };
  const slice = createRunLayersSlice(deps);
  sliceRef = slice;
  return { slice, calls };
}

/** 建组并绑定 runId，返回组与成员图层 */
function setupGroup(
  slice: ReturnType<typeof createRunLayersSlice>,
  options: { runId?: string; tags: string[]; produced?: string[] },
): { group: ActiveRunLayerGroup; members: ActiveLayer[] } {
  const created = slice.createRunLayerGroup({
    title: "反演计算组",
    targets: options.tags.map((t) => ({ name: t, productTag: t })),
    sourceLayerId: "src-layer",
    workflowId: "wf-x",
  });
  if (options.runId) slice.bindRunIdToGroup(created.groupId, options.runId);
  const group = slice.findRunGroupById(created.groupId)!;
  const members = created.memberInstanceIds
    .map((id) => activeLayers.find((l) => l.instanceId === id))
    .filter((l): l is ActiveLayer => Boolean(l));
  options.produced?.forEach((instanceId, i) => {
    const layer = activeLayers.find((l) => l.instanceId === instanceId);
    if (layer) {
      layer.importedRaster = {
        overlayLayerId: `ov-produced-${i}`,
        nativeStep: null,
      };
      layer.dataState = "imported";
    }
  });
  return { group, members };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockOutputEntries = [];
  vi.mocked(isOverlayDismissed).mockReturnValue(false);
  vi.mocked(isRunDismissed).mockReturnValue(false);
  vi.mocked(extractOverlayImportsFromResultRefs).mockReturnValue([]);
  mockMaterialize([]);
});

afterEach(() => {
  vi.useRealTimers();
});

// ── workflowSummary ───────────────────────────────────────────────────────────

describe("workflowSummary", () => {
  it("空列表为 idle", () => {
    const { slice } = setup();
    expect(slice.workflowSummary.value).toMatchObject({
      total: 0,
      overall: "idle",
      tone: "idle",
      hasError: false,
    });
  });

  it("running/queued/retry_pending 计为 active", () => {
    const { slice } = setup();
    slice.setJobLayers([
      makeJob({ jobId: "a", status: "running" }),
      makeJob({ jobId: "b", status: "queued" }),
      makeJob({ jobId: "c", status: "retry_pending" }),
    ]);
    const s = slice.workflowSummary.value;
    expect(s.overall).toBe("active");
    expect(s.tone).toBe("active");
    expect(s.running).toBe(1);
    expect(s.queued).toBe(1);
    expect(s.retryPending).toBe(1);
  });

  it("失败与成功并存为 mixed/warning", () => {
    const { slice } = setup();
    slice.setJobLayers([
      makeJob({ jobId: "a", status: "succeeded" }),
      makeJob({ jobId: "b", status: "failed" }),
    ]);
    expect(slice.workflowSummary.value.overall).toBe("mixed");
    expect(slice.workflowSummary.value.tone).toBe("warning");
  });

  it("仅失败为 failed/error 且 hasError", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "a", status: "failed" })]);
    const s = slice.workflowSummary.value;
    expect(s.overall).toBe("failed");
    expect(s.tone).toBe("error");
    expect(s.hasError).toBe(true);
  });

  it("仅成功为 succeeded/success；workflowError 置位时 hasError", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "a", status: "succeeded" })]);
    expect(slice.workflowSummary.value.overall).toBe("succeeded");
    expect(slice.workflowSummary.value.hasError).toBe(false);
    slice.workflowError.value = "boom";
    expect(slice.workflowSummary.value.hasError).toBe(true);
  });

  it("cancelled 不影响 overall", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "a", status: "cancelled" })]);
    const s = slice.workflowSummary.value;
    expect(s.cancelled).toBe(1);
    expect(s.overall).toBe("idle");
  });
});

// ── emitWorkflowProgressTimeSeek（W3.6）────────────────────────────────────────

describe("emitWorkflowProgressTimeSeek", () => {
  it("非 running 状态不发射", () => {
    const { slice } = setup();
    slice.setJobLayers([
      makeJob({ jobId: "run-1", catalogId: "cat-1", status: "succeeded" }),
    ]);
    slice.emitWorkflowProgressTimeSeek(slice.jobLayers.value[0]!, "succeeded", {
      phase: "block_commit",
      timeKey: "20240501",
    });
    expect(slice.workflowProgressTimeSeek.value).toBeNull();
  });

  it("非块提交阶段不发射", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1", catalogId: "cat-1" })]);
    slice.emitWorkflowProgressTimeSeek(slice.jobLayers.value[0]!, "running", {
      phase: "download",
      timeKey: "20240501",
    });
    expect(slice.workflowProgressTimeSeek.value).toBeNull();
  });

  it("block_commit + timeKey 发射 seek 提示并标记 in-flight 键", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1", catalogId: "cat-1" })]);
    slice.emitWorkflowProgressTimeSeek(slice.jobLayers.value[0]!, "running", {
      phase: "block_commit",
      timeKey: "20240501",
    });
    const hint = slice.workflowProgressTimeSeek.value;
    expect(hint).toMatchObject({
      runId: "run-1",
      catalogId: "cat-1",
      timeKey: "20240501",
      sliceLabel: "20240501",
    });
    expect(slice.jobLayers.value[0]!.inFlightTimeKeys).toContain("20240501");
  });

  it("同 jobId+timeKey 去重（不重复发射）", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1", catalogId: "cat-1" })]);
    const job = slice.jobLayers.value[0]!;
    slice.emitWorkflowProgressTimeSeek(job, "running", {
      phase: "block_refresh",
      timeKey: "20240501",
    });
    const first = slice.workflowProgressTimeSeek.value;
    slice.emitWorkflowProgressTimeSeek(job, "running", {
      phase: "block_refresh",
      timeKey: "20240501",
    });
    expect(slice.workflowProgressTimeSeek.value).toBe(first);
  });

  it("range 型 timeKey 透传为 sliceLabel", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1", catalogId: "cat-1" })]);
    slice.emitWorkflowProgressTimeSeek(slice.jobLayers.value[0]!, "running", {
      phase: "artifact",
      timeKey: "20240501_20240508",
    });
    expect(slice.workflowProgressTimeSeek.value?.sliceLabel).toBe(
      "20240501_20240508",
    );
  });

  it("dateStart/dateEnd 组合：sliceLabel 压缩为 8 位日期区间", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1", catalogId: "cat-1" })]);
    slice.emitWorkflowProgressTimeSeek(slice.jobLayers.value[0]!, "running", {
      phase: "block_commit",
      dateStart: "2024-05-01",
      dateEnd: "2024-05-08",
    });
    expect(slice.workflowProgressTimeSeek.value?.sliceLabel).toBe(
      "20240501_20240508",
    );
    expect(slice.workflowProgressTimeSeek.value?.timeKey).toBe("2024-05-01");
    const keys = slice.jobLayers.value[0]!.inFlightTimeKeys ?? [];
    expect(keys).toContain("2024-05-01");
    expect(keys).toContain("2024-05-01_2024-05-08");
  });

  it("无 catalogId 或非法 timeKey 不发射", () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1" })]);
    slice.emitWorkflowProgressTimeSeek(slice.jobLayers.value[0]!, "running", {
      phase: "block_commit",
      timeKey: "20240501",
    });
    expect(slice.workflowProgressTimeSeek.value).toBeNull();

    slice.setJobLayers([makeJob({ jobId: "run-2", catalogId: "cat-2" })]);
    slice.emitWorkflowProgressTimeSeek(slice.jobLayers.value[0]!, "running", {
      phase: "block_commit",
      timeKey: "not-a-date",
    });
    expect(slice.workflowProgressTimeSeek.value).toBeNull();
  });
});

// ── job layer 列表维护 ────────────────────────────────────────────────────────

describe("removeJobLayerById", () => {
  it("移除 job 并清理活跃图层上的幽灵引用", () => {
    const { slice } = setup();
    const job = makeJob({ jobId: "run-x" });
    const layer = makeLayer({ jobLayer: job });
    activeLayers.push(layer);
    slice.setJobLayers([job, makeJob({ jobId: "run-y" })]);
    slice.removeJobLayerById("run-x");
    expect(slice.jobLayers.value.map((j) => j.jobId)).toEqual(["run-y"]);
    expect(layer.jobLayer).toBeUndefined();
  });
});

describe("syncJobLayerToActiveLayer", () => {
  it("优先按 jobId 匹配已有活跃图层原地更新", () => {
    const { slice, calls } = setup();
    const job1 = makeJob({ jobId: "run-1", progress: 10 });
    const layer = makeLayer({ catalogId: "cat-a", jobLayer: job1 });
    activeLayers.push(layer);
    const job2 = makeJob({ jobId: "run-1", progress: 50 });
    slice.syncJobLayerToActiveLayer("cat-other", job2);
    expect(layer.jobLayer).toBe(job2);
    expect(layer.dataState).toBe("real");
    expect(calls.addLayer).not.toHaveBeenCalled();
  });

  it("按 catalogId 匹配非边界图层挂载 jobLayer", () => {
    const { slice } = setup();
    const layer = makeLayer({ catalogId: "cat-a" });
    const admin = makeLayer({ catalogId: "cat-a", isAdminBoundary: true });
    activeLayers.push(layer, admin);
    const job = makeJob({ jobId: "run-1" });
    slice.syncJobLayerToActiveLayer("cat-a", job);
    expect(layer.jobLayer).toBe(job);
    expect(layer.dataState).toBe("real");
    expect(admin.jobLayer).toBeUndefined();
  });

  it("无匹配时走 addLayer", () => {
    const { slice, calls } = setup();
    const job = makeJob({ jobId: "run-1" });
    slice.syncJobLayerToActiveLayer("cat-new", job);
    expect(calls.addLayer).toHaveBeenCalledWith("cat-new", false, job);
  });
});

describe("upsertJobLayer", () => {
  it("缺失 catalogId 时补写；新 job 插入队首", () => {
    const { slice, calls } = setup();
    slice.setJobLayers([makeJob({ jobId: "old", catalogId: "cat-old" })]);
    slice.upsertJobLayer("cat-new", makeJob({ jobId: "run-new" }));
    expect(slice.jobLayers.value[0]!.jobId).toBe("run-new");
    expect(slice.jobLayers.value[0]!.catalogId).toBe("cat-new");
    expect(calls.rememberTrackedWorkflowRun).toHaveBeenCalled();
    expect(calls.scheduleWorkspacePersist).toHaveBeenCalled();
  });

  it("已存在的 job 原位替换", () => {
    const { slice } = setup();
    slice.setJobLayers([
      makeJob({ jobId: "a", catalogId: "cat-a" }),
      makeJob({ jobId: "b", catalogId: "cat-b" }),
    ]);
    slice.upsertJobLayer(
      "cat-a",
      makeJob({ jobId: "a", status: "succeeded", progress: 100 }),
    );
    expect(slice.jobLayers.value.map((j) => j.jobId)).toEqual(["a", "b"]);
    expect(slice.jobLayers.value[0]!.progress).toBe(100);
  });

  it("cancelled 终态会 forgetTrackedWorkflowRun", () => {
    const { slice, calls } = setup();
    slice.upsertJobLayer(
      "cat-a",
      makeJob({ jobId: "run-c", status: "cancelled" }),
    );
    expect(calls.forgetTrackedWorkflowRun).toHaveBeenCalledWith("run-c");
  });

  it("failed 真实 run 触发组清理：占位移除、产物解锁并标（部分）", () => {
    const { slice, calls } = setup();
    const { group, members } = setupGroup(slice, {
      runId: "run-f",
      tags: ["SM", "VOD"],
      produced: [],
    });
    members[0]!.importedRaster = {
      overlayLayerId: "ov-sm",
      nativeStep: null,
    };
    members[0]!.dataState = "imported";
    members[0]!.name = productTagLabel("SM");
    slice.upsertJobLayer(
      "cat-src",
      makeJob({ jobId: "run-f", status: "failed" }),
    );
    expect(activeLayers.map((l) => l.instanceId)).not.toContain(
      members[1]!.instanceId,
    );
    expect(calls.removeLayer).toHaveBeenCalledWith(members[1]!.instanceId);
    expect(members[0]!.runGroupLocked).toBe(false);
    expect(members[0]!.name).toContain("（部分）");
    expect(group.dissolvable).toBe(true);
    expect(group.status).toBe("failed");
  });

  it("local-submit 失败按 catalog 清理占位组", () => {
    const { slice, calls } = setup();
    calls.isLocalSubmitJobId.mockReturnValue(true);
    const { group, members } = setupGroup(slice, { runId: "", tags: ["SM"] });
    activeLayers[0]!.catalogId = "cat-src";
    activeLayers[0]!.runGroupId = group.groupId;
    members[0]!.catalogId = "cat-src";
    slice.upsertJobLayer(
      "cat-src",
      makeJob({ jobId: "local-1", status: "failed", message: "提交失败" }),
    );
    expect(group.status).toBe("failed");
    expect(group.dissolvable).toBe(true);
    expect(group.message).toBe("提交失败");
  });
});

// ── buildWorkflowPayloadForCatalog ────────────────────────────────────────────

describe("buildWorkflowPayloadForCatalog", () => {
  it("默认字段：layer_id 回退 catalogId，参数来自地图上下文", () => {
    const { slice } = setup();
    const payload = slice.buildWorkflowPayloadForCatalog(
      "cat-x",
      "土壤水分",
      ["map_layer"],
      { west: 1, south: 2, east: 3, north: 4 },
    ) as Record<string, Record<string, unknown>>;
    expect(payload["layer_id"]).toBe("cat-x");
    expect(payload["command_type"]).toBe("analysis");
    expect(payload["requested_outputs"]).toEqual(["map_layer"]);
    expect(payload["parameters"]).toMatchObject({
      hour: 12,
      latitude: 39.9,
      longitude: 116.4,
    });
    expect(payload["map_context"]).toMatchObject({
      active_layer_id: "cat-x",
      map_mode: "2d",
    });
    expect(payload["algorithm_request"]).toBeUndefined();
    expect(payload["weather_request"]).toBeUndefined();
  });

  it("backendLayerId 覆盖 layer_id；非空请求体附加", () => {
    const { slice } = setup();
    const payload = slice.buildWorkflowPayloadForCatalog(
      "cat-x",
      "土壤水分",
      [],
      null,
      "be-layer-1",
      { mode: "sf" },
      { hours: 24 },
    ) as Record<string, unknown>;
    expect(payload["layer_id"]).toBe("be-layer-1");
    expect(payload["algorithm_request"]).toEqual({ mode: "sf" });
    expect(payload["weather_request"]).toEqual({ hours: 24 });
    const mapContext = payload["map_context"] as Record<string, unknown>;
    expect(mapContext["viewport_bbox"]).toBeUndefined();
  });
});

// ── 渐进物化 ─────────────────────────────────────────────────────────────────

describe("formatProgressiveSyncMessage", () => {
  it("四种分支文案", () => {
    const { slice } = setup();
    expect(slice.formatProgressiveSyncMessage(0, true)).toBe(
      WORKFLOW_COPY.progressiveSyncFailed,
    );
    expect(slice.formatProgressiveSyncMessage(2, true)).toBe(
      WORKFLOW_COPY.progressiveSyncPartial.replace("{count}", "2"),
    );
    expect(slice.formatProgressiveSyncMessage(3, false)).toBe(
      WORKFLOW_COPY.progressiveSyncOk.replace("{count}", "3"),
    );
    expect(slice.formatProgressiveSyncMessage(0, false)).toBe("");
  });
});

describe("applyProgressiveSyncToJob", () => {
  it("成功：计数与时间戳更新、错误清除", () => {
    const { slice } = setup();
    const job = makeJob({ jobId: "run-1", progressiveOverlayError: "旧错误" });
    slice.setJobLayers([job]);
    slice.applyProgressiveSyncToJob("cat-1", "run-1", 4, false);
    expect(job.progressiveOverlayCount).toBe(4);
    expect(job.progressiveOverlayError).toBeUndefined();
    expect(job.progressiveOverlayAt).toBeTruthy();
    expect(job.message).toContain("4");
  });

  it("失败：diagnosticNotes 头插并截断至 8 条", () => {
    const { slice } = setup();
    const job = makeJob({
      jobId: "run-1",
      diagnosticNotes: Array.from({ length: 8 }, (_, i) => `note-${i}`),
    });
    slice.setJobLayers([job]);
    slice.applyProgressiveSyncToJob("cat-1", "run-1", 0, true, "HTTP 500");
    expect(job.progressiveOverlayError).toBe("HTTP 500");
    expect(job.diagnosticNotes?.[0]).toBe("HTTP 500");
    expect(job.diagnosticNotes?.length).toBe(8);
    expect(job.message).toBe(WORKFLOW_COPY.progressiveSyncFailed);
  });

  it("job 不存在时安全无操作", () => {
    const { slice } = setup();
    expect(() =>
      slice.applyProgressiveSyncToJob("cat-1", "run-none", 1, false),
    ).not.toThrow();
  });
});

describe("syncProgressiveBlockOverlays", () => {
  it("节流：8 秒内第二次调用直接跳过", async () => {
    vi.useFakeTimers();
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1", catalogId: "cat-1" })]);
    mockMaterialize([
      { overlay_layer_id: "ov-1", title: "SM", product_tag: "SM" },
    ]);
    await slice.syncProgressiveBlockOverlays("run-1", "cat-1");
    expect(materializeWorkflowMapLayers).toHaveBeenCalledTimes(1);
    await slice.syncProgressiveBlockOverlays("run-1", "cat-1");
    expect(materializeWorkflowMapLayers).toHaveBeenCalledTimes(1);
    expect(slice.jobLayers.value[0]!.progressiveOverlayCount).toBe(1);
  });

  it("8 秒后再次执行", async () => {
    vi.useFakeTimers();
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1", catalogId: "cat-1" })]);
    mockMaterialize([
      { overlay_layer_id: "ov-1", title: "SM", product_tag: "SM" },
    ]);
    await slice.syncProgressiveBlockOverlays("run-1", "cat-1");
    vi.advanceTimersByTime(9_000);
    await slice.syncProgressiveBlockOverlays("run-1", "cat-1");
    expect(materializeWorkflowMapLayers).toHaveBeenCalledTimes(2);
  });

  it("已 dismiss 的 run 不触发物化", async () => {
    const { slice } = setup();
    vi.mocked(isRunDismissed).mockReturnValue(true);
    await slice.syncProgressiveBlockOverlays("run-1", "cat-1");
    expect(materializeWorkflowMapLayers).not.toHaveBeenCalled();
  });

  it("attach 异常落入错误诊断", async () => {
    const { slice } = setup();
    slice.setJobLayers([makeJob({ jobId: "run-1", catalogId: "cat-1" })]);
    vi.mocked(extractOverlayImportsFromResultRefs).mockImplementation(() => {
      throw new Error("adapter boom");
    });
    await slice.syncProgressiveBlockOverlays("run-1", "cat-1");
    const job = slice.jobLayers.value[0]!;
    expect(job.progressiveOverlayError).toBe("adapter boom");
    expect(job.diagnosticNotes?.[0]).toBe("adapter boom");
    expect(job.message).toBe(WORKFLOW_COPY.progressiveSyncFailed);
  });

  it("空 runId 不触发", async () => {
    const { slice } = setup();
    await slice.syncProgressiveBlockOverlays("", "cat-1");
    expect(materializeWorkflowMapLayers).not.toHaveBeenCalled();
  });
});

// ── attachAlgorithmProductOverlays ────────────────────────────────────────────

describe("attachAlgorithmProductOverlays", () => {
  it("run 已 dismiss 返回 0 且不物化", async () => {
    const { slice } = setup();
    vi.mocked(isRunDismissed).mockReturnValue(true);
    const count = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-1",
      "run-1",
    );
    expect(count).toBe(0);
    expect(materializeWorkflowMapLayers).not.toHaveBeenCalled();
  });

  it("按 runId 组内绑定各产品成员", async () => {
    const { slice, calls } = setup();
    const { members } = setupGroup(slice, {
      runId: "run-1",
      tags: ["SM", "VOD"],
    });
    mockMaterialize([
      { overlay_layer_id: "ov-sm", title: "SM", product_tag: "SM" },
      { overlay_layer_id: "ov-vod", title: "VOD", product_tag: "VOD" },
    ]);
    const count = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-src",
      "run-1",
    );
    expect(count).toBe(2);
    expect(members[0]!.importedRaster?.overlayLayerId).toBe("ov-sm");
    expect(members[0]!.dataState).toBe("imported");
    expect(members[1]!.importedRaster?.overlayLayerId).toBe("ov-vod");
    expect(calls.scheduleWorkspacePersist).toHaveBeenCalled();
  });

  it("已有同 overlay 游离层：刷新 timeList 并剪除 ready 的 in-flight 键", async () => {
    const { slice } = setup();
    const existing = makeLayer({
      catalogId: "ov-sm",
      dataState: "imported",
      importedRaster: { overlayLayerId: "ov-sm", nativeStep: null },
    });
    activeLayers.push(existing);
    slice.setJobLayers([
      makeJob({
        jobId: "run-1",
        catalogId: "cat-1",
        inFlightTimeKeys: ["20240501"],
      }),
    ]);
    mockMaterialize([
      {
        overlay_layer_id: "ov-sm",
        title: "SM",
        product_tag: "SM",
        time_list: ["20240501", "20240509"],
      },
    ]);
    const count = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-1",
      "run-1",
    );
    expect(count).toBe(1);
    expect(existing.importedRaster?.timeList).toEqual(["20240501", "20240509"]);
    expect(existing.importedRaster?.timeSlices).toBeUndefined();
    expect(existing.importedRaster?.nativeStep).toBeTruthy();
    expect(slice.jobLayers.value[0]!.inFlightTimeKeys).toHaveLength(0);
  });

  it("OMEGA_BLOCK 游离层 + 组内占位：并入组并移除游离条目", async () => {
    const { slice } = setup();
    const { group, members } = setupGroup(slice, {
      runId: "run-1",
      tags: ["OMEGA"],
    });
    const orphan = makeLayer({
      catalogId: "ov-om2",
      name: "OMEGA_BLOCK",
      dataState: "imported",
      importedRaster: { overlayLayerId: "ov-om2", nativeStep: null },
    });
    activeLayers.push(orphan);
    mockMaterialize([
      {
        overlay_layer_id: "ov-om2",
        title: "OMEGA_BLOCK",
        product_tag: "OMEGA_BLOCK",
      },
    ]);
    await slice.attachAlgorithmProductOverlays([], "cat-src", "run-1");
    expect(members[0]!.importedRaster?.overlayLayerId).toBe("ov-om2");
    expect(members[0]!.dataState).toBe("imported");
    expect(activeLayers.map((l) => l.instanceId)).not.toContain(
      orphan.instanceId,
    );
    expect(group.memberInstanceIds).not.toContain(orphan.instanceId);
  });

  it("OMEGA_BLOCK 无组时并入任意 OMEGA 占位", async () => {
    const { slice } = setup();
    const placeholder = makeLayer({
      name: "OMEGA",
      runGroupProductTag: "OMEGA",
    });
    activeLayers.push(placeholder);
    vi.mocked(extractOverlayImportsFromResultRefs).mockReturnValue([
      {
        overlayLayerId: "ov-om",
        title: "OMEGA_BLOCK",
        productTag: "OMEGA_BLOCK",
      },
    ]);
    const count = await slice.attachAlgorithmProductOverlays(
      [{ title: "x" }] as Parameters<
        typeof extractOverlayImportsFromResultRefs
      >[0],
      "cat-src",
    );
    expect(count).toBe(1);
    expect(placeholder.importedRaster?.overlayLayerId).toBe("ov-om");
    expect(placeholder.name).toBe(productTagLabel("OMEGA"));
    expect(placeholder.dataState).toBe("imported");
  });

  it("优先绑定到 wf-out 输出目录对应活跃图层", async () => {
    const { slice, calls } = setup();
    mockOutputEntries = [{ name: "土壤水分 (SM)", localId: "wf-out-sm" }];
    const target = makeLayer({ catalogId: "wf-out-sm" });
    activeLayers.push(target);
    vi.mocked(extractOverlayImportsFromResultRefs).mockReturnValue([
      {
        overlayLayerId: "ov-a",
        title: "Algorithm Map Layer: SM",
        productTag: "SM",
      },
    ]);
    const count = await slice.attachAlgorithmProductOverlays(
      [] as Parameters<typeof extractOverlayImportsFromResultRefs>[0],
      "cat-src",
    );
    expect(count).toBe(1);
    expect(target.importedRaster?.overlayLayerId).toBe("ov-a");
    expect(target.dataState).toBe("imported");
    expect(calls.addLayer).not.toHaveBeenCalled();
  });

  it("无匹配时新增游离图层并挂入运行组", async () => {
    const { slice } = setup();
    const { group } = setupGroup(slice, { runId: "run-9", tags: ["VOD"] });
    mockMaterialize([
      { overlay_layer_id: "ov-new", title: "SM", product_tag: "SM" },
    ]);
    const count = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-src",
      "run-9",
    );
    expect(count).toBe(1);
    const added = activeLayers.find(
      (l) => l.importedRaster?.overlayLayerId === "ov-new",
    );
    expect(added).toBeTruthy();
    expect(added!.runGroupId).toBe(group.groupId);
    expect(added!.runGroupLocked).toBe(true);
    expect(group.memberInstanceIds).toContain(added!.instanceId);
  });

  it("R4：Algorithm Output 前缀标题不泄漏为图层名", async () => {
    // file 类产物 title 形态是 "Algorithm Output: {label}"（区别于 map_layer 的
    // "Algorithm Map Layer:"）——normalizeProductTag 未剥此前缀时，title 会
    // 作为未知 tag 经 productTagLabel 透传成图层名（大写技术前缀泄漏）。
    const { slice } = setup();
    mockMaterialize([
      { overlay_layer_id: "ov-out", title: "Algorithm Output: 月降水" },
    ]);
    const count = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-src",
      "run-r4",
    );
    expect(count).toBe(1);
    const added = activeLayers.find(
      (l) => l.importedRaster?.overlayLayerId === "ov-out",
    );
    expect(added).toBeTruthy();
    expect(added!.name).toBe("月降水");
  });

  it("succeeded 空产物延迟二次确认后写入可见空态横幅", async () => {
    vi.useFakeTimers();
    const { slice } = setup();
    slice.setJobLayers([
      makeJob({ jobId: "run-ok", catalogId: "cat-1", status: "succeeded" }),
    ]);
    mockMaterialize([]); // 二次确认仍空 → 写横幅
    const count = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-1",
      "run-ok",
    );
    expect(count).toBe(0);
    // 延迟确认窗口内不写横幅（succeeded 事件先到、产物登记后到的竞态防护）
    expect(slice.workflowError.value).toBeNull();
    await vi.advanceTimersByTimeAsync(2_500);
    expect(slice.workflowError.value).toBe(WORKFLOW_COPY.noMapLayers);
    vi.useRealTimers();
  });

  it("running 空产物清除残留空态横幅", async () => {
    const { slice } = setup();
    slice.workflowError.value = WORKFLOW_COPY.noMapLayers;
    slice.setJobLayers([
      makeJob({ jobId: "run-r", catalogId: "cat-1", status: "running" }),
    ]);
    mockMaterialize([]);
    await slice.attachAlgorithmProductOverlays([], "cat-1", "run-r");
    expect(slice.workflowError.value).toBeNull();
  });

  it("409 / 不可物化冲突不写错误横幅", async () => {
    const { slice } = setup();
    slice.setJobLayers([
      makeJob({ jobId: "run-f", catalogId: "cat-1", status: "failed" }),
    ]);
    vi.mocked(materializeWorkflowMapLayers).mockRejectedValue(
      new Error("409 cannot materialize ExecutionStatus.failed"),
    );
    const count = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-1",
      "run-f",
    );
    expect(count).toBe(0);
    expect(slice.workflowError.value).toBeNull();
  });

  it("其它物化失败写入 workflowError", async () => {
    const { slice } = setup();
    slice.setJobLayers([
      makeJob({ jobId: "run-e", catalogId: "cat-1", status: "succeeded" }),
    ]);
    vi.mocked(materializeWorkflowMapLayers).mockRejectedValue(
      new Error("boom"),
    );
    await slice.attachAlgorithmProductOverlays([], "cat-1", "run-e");
    expect(slice.workflowError.value).toContain("工作流结果图层加载失败");
    expect(slice.workflowError.value).toContain("boom");
  });

  it("已 dismiss 的 overlay 被过滤返回 0；forceBind 可绕过", async () => {
    const { slice } = setup();
    const { members } = setupGroup(slice, { runId: "run-1", tags: ["SM"] });
    mockMaterialize([
      { overlay_layer_id: "ov-sm", title: "SM", product_tag: "SM" },
    ]);
    vi.mocked(isOverlayDismissed).mockReturnValue(true);
    const filtered = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-src",
      "run-1",
    );
    expect(filtered).toBe(0);
    const forced = await slice.attachAlgorithmProductOverlays(
      [],
      "cat-src",
      "run-1",
      {
        forceBind: true,
      },
    );
    expect(forced).toBe(1);
    expect(members[0]!.importedRaster?.overlayLayerId).toBe("ov-sm");
  });
});

// ── reconcileOmegaBlockLayers ─────────────────────────────────────────────────

describe("reconcileOmegaBlockLayers", () => {
  it("游离 OMEGA_BLOCK 并入 OMEGA 占位并移除游离层", () => {
    const { slice } = setup();
    const placeholder = makeLayer({
      name: "OMEGA",
      runGroupProductTag: "OMEGA",
    });
    const orphan = makeLayer({
      name: "OMEGA_BLOCK",
      dataState: "imported",
      importedRaster: { overlayLayerId: "ov-om", nativeStep: null },
    });
    activeLayers.push(placeholder, orphan);
    slice.reconcileOmegaBlockLayers();
    expect(placeholder.importedRaster?.overlayLayerId).toBe("ov-om");
    expect(placeholder.dataState).toBe("imported");
    expect(activeLayers.map((l) => l.instanceId)).not.toContain(
      orphan.instanceId,
    );
  });

  it("无占位时仅重命名为 ω 显示名", () => {
    const { slice } = setup();
    const orphan = makeLayer({
      name: "OMEGA_BLOCK",
      dataState: "imported",
      importedRaster: { overlayLayerId: "ov-om", nativeStep: null },
    });
    activeLayers.push(orphan);
    slice.reconcileOmegaBlockLayers();
    expect(orphan.name).toBe(productTagLabel("OMEGA"));
    expect(activeLayers).toHaveLength(1);
  });

  it("游离层属于旧组时清理组成员关系，组空则删除组", () => {
    const { slice } = setup();
    const oldGroup = makeGroup({ groupId: "grp-old", memberInstanceIds: [] });
    slice.runLayerGroups.value.push(oldGroup);
    const placeholder = makeLayer({
      name: "OMEGA",
      runGroupProductTag: "OMEGA",
    });
    const orphan = makeLayer({
      name: "OMEGA_BLOCK",
      dataState: "imported",
      runGroupId: "grp-old",
      importedRaster: { overlayLayerId: "ov-om", nativeStep: null },
    });
    oldGroup.memberInstanceIds.push(orphan.instanceId);
    activeLayers.push(placeholder, orphan);
    slice.reconcileOmegaBlockLayers();
    expect(slice.runLayerGroups.value.map((g) => g.groupId)).not.toContain(
      "grp-old",
    );
  });
});

// ── reorderLayers ─────────────────────────────────────────────────────────────

describe("reorderLayers", () => {
  function setupOrdered(slice: ReturnType<typeof createRunLayersSlice>) {
    const a = makeLayer({ instanceId: "A", order: 3 });
    const b = makeLayer({ instanceId: "B", order: 2 });
    const c = makeLayer({ instanceId: "C", order: 1 });
    const d = makeLayer({ instanceId: "D", order: 0 });
    activeLayers.push(a, b, c, d);
    return { a, b, c, d };
  }

  it("普通图层重排后重写 order", () => {
    const { slice, calls } = setup();
    const { a, b, c, d } = setupOrdered(slice);
    slice.reorderLayers(0, 2);
    expect(b.order).toBe(3);
    expect(c.order).toBe(2);
    expect(a.order).toBe(1);
    expect(d.order).toBe(0);
    expect(calls.scheduleWorkspacePersist).toHaveBeenCalled();
  });

  it("越界索引无操作", () => {
    const { slice } = setup();
    const { a } = setupOrdered(slice);
    slice.reorderLayers(9, 0);
    expect(a.order).toBe(3);
  });

  it("锁定组成员不可拖出组外", () => {
    const { slice } = setup();
    const { a, b, c } = setupOrdered(slice);
    const group = makeGroup({
      memberInstanceIds: [a.instanceId, b.instanceId],
    });
    slice.runLayerGroups.value.push(group);
    a.runGroupId = group.groupId;
    b.runGroupId = group.groupId;
    a.runGroupLocked = true;
    b.runGroupLocked = true;
    slice.reorderLayers(0, 2);
    expect(a.order).toBe(3);
    expect(c.order).toBe(1);
  });

  it("锁定组成员在组内调序走组内路径", () => {
    const { slice } = setup();
    const { a, b } = setupOrdered(slice);
    const group = makeGroup({
      memberInstanceIds: [a.instanceId, b.instanceId],
    });
    slice.runLayerGroups.value.push(group);
    a.runGroupId = group.groupId;
    b.runGroupId = group.groupId;
    a.runGroupLocked = true;
    b.runGroupLocked = true;
    slice.reorderLayers(0, 1);
    expect(group.memberInstanceIds).toEqual([b.instanceId, a.instanceId]);
    expect(b.order).toBeGreaterThan(a.order);
  });

  it("外部图层不可插入锁定组块中间", () => {
    const { slice } = setup();
    const { a, d } = setupOrdered(slice);
    const group = makeGroup({ memberInstanceIds: [a.instanceId] });
    slice.runLayerGroups.value.push(group);
    a.runGroupId = group.groupId;
    a.runGroupLocked = true;
    slice.reorderLayers(3, 0);
    expect(d.order).toBe(0);
    expect(a.order).toBe(3);
  });
});

// ── run group 生命周期 ────────────────────────────────────────────────────────

describe("createRunLayerGroup / bindRunIdToGroup", () => {
  it("创建占位成员与组，切换侧栏并选中首个成员", () => {
    const { slice, calls } = setup();
    activeLayers.push(makeLayer({ order: 5 }));
    const created = slice.createRunLayerGroup({
      title: "反演组",
      targets: [
        { name: "SM", productTag: "SM" },
        { name: "VOD", productTag: "VOD" },
      ],
      sourceLayerId: "src",
      workflowId: "wf-1",
      memberCatalogIds: ["wf-run-a-sm", "wf-run-a-vod"],
    });
    expect(created.memberCatalogIds).toEqual(["wf-run-a-sm", "wf-run-a-vod"]);
    const group = slice.findRunGroupById(created.groupId);
    expect(group).not.toBeNull();
    expect(group!.status).toBe("computing");
    expect(group!.memberInstanceIds).toHaveLength(2);
    expect(calls.setSidebarView).toHaveBeenCalledWith("active");
    expect(calls.setSelectedInstanceId).toHaveBeenCalledWith(
      created.memberInstanceIds[0],
    );
    const members = activeLayers.filter(
      (l) => l.runGroupId === created.groupId,
    );
    expect(members[0]!.order).toBeGreaterThan(members[1]!.order);
  });

  it("未提供 memberCatalogIds 时生成 wf-run 前缀 id", () => {
    const { slice } = setup();
    const created = slice.createRunLayerGroup({
      title: "T",
      targets: [{ name: "X", productTag: "result" }],
      sourceLayerId: "src",
      workflowId: "wf",
    });
    expect(created.memberCatalogIds[0]).toMatch(/^wf-run-/);
  });

  it("bindRunIdToGroup 写入并持久化；未知组无操作", () => {
    const { slice, calls } = setup();
    const { group } = setupGroup(slice, { tags: ["SM"] });
    slice.bindRunIdToGroup(group.groupId, "run-42");
    expect(group.runId).toBe("run-42");
    expect(calls.scheduleWorkspacePersist).toHaveBeenCalled();
    slice.bindRunIdToGroup("grp-none", "run-x");
    expect(slice.runLayerGroups.value).toHaveLength(1);
  });
});

describe("cleanupUnproducedRunLayers", () => {
  it("无产物成员移除，有产物成员解锁并标（部分）", () => {
    const { slice, calls } = setup();
    const { group, members } = setupGroup(slice, {
      runId: "run-1",
      tags: ["SM", "VOD"],
    });
    members[0]!.importedRaster = { overlayLayerId: "ov-sm", nativeStep: null };
    members[0]!.name = productTagLabel("SM");
    slice.cleanupUnproducedRunLayers("run-1");
    expect(calls.removeLayer).toHaveBeenCalledWith(members[1]!.instanceId);
    expect(members[0]!.runGroupLocked).toBe(false);
    expect(members[0]!.name).toContain("（部分）");
    expect(group.dissolvable).toBe(true);
  });

  it("全部成员无产物时组整体移除", () => {
    const { slice } = setup();
    const { group, members } = setupGroup(slice, {
      runId: "run-2",
      tags: ["SM"],
    });
    slice.cleanupUnproducedRunLayers("run-2");
    expect(activeLayers.map((l) => l.instanceId)).not.toContain(
      members[0]!.instanceId,
    );
    expect(slice.runLayerGroups.value.map((g) => g.groupId)).not.toContain(
      group.groupId,
    );
  });

  it("未知 runId 无操作", () => {
    const { slice } = setup();
    setupGroup(slice, { runId: "run-3", tags: ["SM"] });
    slice.cleanupUnproducedRunLayers("run-none");
    expect(slice.runLayerGroups.value).toHaveLength(1);
  });

  it("succeeded：空占位成员移除、产物成员不加（部分）、组保留且状态 ready", () => {
    const { slice, calls } = setup();
    const { group, members } = setupGroup(slice, {
      runId: "run-ok",
      tags: ["SM", "VOD"],
    });
    members[0]!.importedRaster = { overlayLayerId: "ov-sm", nativeStep: null };
    members[0]!.name = productTagLabel("SM");
    slice.cleanupUnproducedRunLayers("run-ok", { succeeded: true });
    expect(calls.removeLayer).toHaveBeenCalledWith(members[1]!.instanceId);
    expect(members[0]!.runGroupLocked).toBe(false);
    expect(members[0]!.name).not.toContain("（部分）");
    expect(group.status).toBe("ready");
    expect(group.dissolvable).toBe(true);
    expect(slice.runLayerGroups.value.map((g) => g.groupId)).toContain(
      group.groupId,
    );
  });

  it("succeeded：全部成员无产物时组整体移除", () => {
    const { slice } = setup();
    const { group } = setupGroup(slice, {
      runId: "run-ok2",
      tags: ["SM", "VOD"],
    });
    slice.cleanupUnproducedRunLayers("run-ok2", { succeeded: true });
    expect(slice.runLayerGroups.value.map((g) => g.groupId)).not.toContain(
      group.groupId,
    );
  });
});

describe("refreshRunGroupDissolvable", () => {
  it("failed/cancelled 组可拆并解锁成员", () => {
    const { slice } = setup();
    const { group, members } = setupGroup(slice, { tags: ["SM"] });
    group.status = "failed";
    members[0]!.runGroupLocked = true;
    slice.refreshRunGroupDissolvable(group.groupId);
    expect(group.dissolvable).toBe(true);
    expect(members[0]!.runGroupLocked).toBe(false);
  });

  it("ready 且全部可显示时可拆", () => {
    const { slice } = setup();
    const { group, members } = setupGroup(slice, { tags: ["SM"] });
    group.status = "ready";
    members[0]!.importedRaster = { overlayLayerId: "ov", nativeStep: null };
    slice.refreshRunGroupDissolvable(group.groupId);
    expect(group.dissolvable).toBe(true);
    expect(members[0]!.runGroupLocked).toBe(false);
  });

  it("ready 但存在不可显示成员时保持锁定", () => {
    const { slice } = setup();
    const { group } = setupGroup(slice, { tags: ["SM"] });
    group.status = "ready";
    slice.refreshRunGroupDissolvable(group.groupId);
    expect(group.dissolvable).toBe(false);
  });

  it("未知组无操作", () => {
    const { slice } = setup();
    expect(() => slice.refreshRunGroupDissolvable("grp-none")).not.toThrow();
  });
});

describe("updateRunGroupFromJob / updateRunGroupForCatalog", () => {
  it("状态映射与进度壳文案", () => {
    const { slice } = setup();
    const { group } = setupGroup(slice, { runId: "run-1", tags: ["SM"] });
    slice.updateRunGroupFromJob("run-1", {
      status: "running",
      progress: 55,
      message: "反演中",
      nodeProgress: [
        {
          nodeId: "n1",
          nodeLabel: "SF 反演",
          stage: "inversion",
          progress: 40,
        },
      ],
    });
    expect(group.status).toBe("computing");
    expect(group.progress).toBe(55);
    expect(typeof group.message).toBe("string");
    expect(group.message!.length).toBeGreaterThan(0);

    slice.updateRunGroupFromJob("run-1", {
      status: "succeeded",
      progress: 100,
      message: "",
    });
    expect(group.status).toBe("ready");
    slice.updateRunGroupFromJob("run-1", {
      status: "cancelled",
      progress: 100,
      message: "",
    });
    expect(group.status).toBe("cancelled");
  });

  it("未知 runId 无操作", () => {
    const { slice } = setup();
    slice.updateRunGroupFromJob("run-none", {
      status: "running",
      progress: 1,
      message: "",
    });
    expect(slice.runLayerGroups.value).toHaveLength(0);
  });

  it("updateRunGroupForCatalog 按成员图层定位组并写真实 runId", () => {
    const { slice, calls } = setup();
    const { group, members } = setupGroup(slice, { tags: ["SM"] });
    activeLayers[0]!.catalogId = "cat-src";
    members[0]!.catalogId = "cat-src";
    calls.isLocalSubmitJobId.mockReturnValue(false);
    slice.updateRunGroupForCatalog("cat-src", {
      jobId: "run-77",
      status: "running",
      progress: 30,
      message: "m",
    });
    expect(group.runId).toBe("run-77");
    expect(group.progress).toBe(30);
    // local-submit 占位阶段不写 runId
    calls.isLocalSubmitJobId.mockReturnValue(true);
    slice.updateRunGroupForCatalog("cat-src", {
      jobId: "local-1",
      status: "running",
      progress: 40,
      message: "m",
    });
    expect(group.runId).toBe("run-77");
  });

  it("成员不在组内时回退按 runId 更新", () => {
    const { slice } = setup();
    const group = makeGroup({ runId: "run-88" });
    slice.runLayerGroups.value.push(group);
    slice.updateRunGroupForCatalog("cat-none", {
      jobId: "run-88",
      status: "succeeded",
      progress: 100,
      message: "done",
    });
    expect(group.status).toBe("ready");
  });
});

describe("dissolveRunGroup", () => {
  it("清除成员组字段并删除组", () => {
    const { slice, calls } = setup();
    const { group, members } = setupGroup(slice, { tags: ["SM", "VOD"] });
    slice.dissolveRunGroup(group.groupId);
    expect(members[0]!.runGroupId).toBeUndefined();
    expect(members[0]!.runGroupProductTag).toBeUndefined();
    expect(members[0]!.runGroupLocked).toBeUndefined();
    expect(slice.runLayerGroups.value).toHaveLength(0);
    expect(calls.scheduleWorkspacePersist).toHaveBeenCalled();
  });
});

describe("reorderWithinRunGroup / moveRunGroupBlock", () => {
  it("非法索引无操作", () => {
    const { slice } = setup();
    const { group } = setupGroup(slice, { tags: ["SM", "VOD"] });
    slice.reorderWithinRunGroup(group.groupId, -1, 0);
    slice.reorderWithinRunGroup(group.groupId, 0, 99);
    expect(group.memberInstanceIds).toHaveLength(2);
  });

  it("组内有效调序重写 order", () => {
    const { slice } = setup();
    const { group, members } = setupGroup(slice, { tags: ["SM", "VOD"] });
    slice.reorderWithinRunGroup(group.groupId, 0, 1);
    expect(group.memberInstanceIds[0]).toBe(members[1]!.instanceId);
    const top = activeLayers.find(
      (l) => l.instanceId === members[1]!.instanceId,
    )!;
    const bottom = activeLayers.find(
      (l) => l.instanceId === members[0]!.instanceId,
    )!;
    expect(top.order).toBeGreaterThan(bottom.order);
  });

  it("moveRunGroupBlock 整组移动到锚点之后/之前与队尾", () => {
    const { slice } = setup();
    const { group, members } = setupGroup(slice, { tags: ["SM", "VOD"] });
    const anchor = makeLayer({ instanceId: "anchor", order: -1 });
    const tail = makeLayer({ instanceId: "tail", order: -2 });
    activeLayers.push(anchor, tail);
    slice.moveRunGroupBlock(group.groupId, anchor.instanceId, true);
    expect(anchor.order).toBeLessThan(members[0]!.order);
    slice.moveRunGroupBlock(group.groupId, anchor.instanceId, false);
    expect(anchor.order).toBeGreaterThan(members[0]!.order);
    slice.moveRunGroupBlock(group.groupId, null, true);
    const memberOrders = members.map((m) => m.order);
    const others = activeLayers
      .filter((l) => !group.memberInstanceIds.includes(l.instanceId))
      .map((l) => l.order);
    expect(Math.min(...memberOrders)).toBeGreaterThan(Math.max(...others));
  });
});

describe("findRunGroupByMember / findRunGroupById", () => {
  it("按成员与按 id 查找", () => {
    const { slice } = setup();
    const { group, members } = setupGroup(slice, { tags: ["SM"] });
    expect(slice.findRunGroupByMember(members[0]!.instanceId)?.groupId).toBe(
      group.groupId,
    );
    expect(slice.findRunGroupByMember("inst-none")).toBeNull();
    expect(slice.findRunGroupById(group.groupId)?.groupId).toBe(group.groupId);
    expect(slice.findRunGroupById("grp-none")).toBeNull();
  });

  it("成员无组时返回 null", () => {
    const { slice } = setup();
    const layer = makeLayer({});
    activeLayers.push(layer);
    expect(slice.findRunGroupByMember(layer.instanceId)).toBeNull();
  });
});
