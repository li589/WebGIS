import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

const activeLayers = ref<
  Array<{
    instanceId: string;
    catalogId: string;
    visible: boolean;
    opacity: number;
    isAdminBoundary?: boolean;
    name?: string;
    jobLayer?: { status: string };
    importedRaster?: { timeList?: string[] };
  }>
>([]);

const toggleLayerVisibility = vi.fn((instanceId: string) => {
  const layer = activeLayers.value.find((l) => l.instanceId === instanceId);
  if (layer) layer.visible = !layer.visible;
});
const setLayerOpacity = vi.fn((instanceId: string, opacity: number) => {
  const layer = activeLayers.value.find((l) => l.instanceId === instanceId);
  if (layer) layer.opacity = opacity;
});
const addLayer = vi.fn((catalogId: string) => {
  activeLayers.value.push({
    instanceId: `inst-${catalogId}`,
    catalogId,
    visible: true,
    opacity: 1,
  });
});
const selectLayer = vi.fn();
const setSidebarView = vi.fn();
const getCatalogAddBlockReason = vi.fn(
  (_catalogId: string) => null as string | null,
);

const removeLayer = vi.fn((instanceId: string) => {
  activeLayers.value = activeLayers.value.filter(
    (l) => l.instanceId !== instanceId,
  );
});
const bringLayerToFront = vi.fn();
const sendLayerToBack = vi.fn();
const setLayerPaletteOverride = vi.fn();
const setLayerRangeOverride = vi.fn();
const selectedInstanceId = ref("");
const activeLayersDisplay = ref<
  Array<{ instanceId: string; renderHint?: { palette?: string } }>
>([]);

const applyDateHour = vi.fn();
const setHour = vi.fn();
const play = vi.fn();
const pause = vi.fn();
const currentHour = ref(12);
const currentDate = ref(new Date(2024, 0, 15));

vi.mock("@/stores/layers/selectors", () => ({
  useLayerWorkspace: () => ({
    activeLayers,
    activeLayersDisplay,
    selectedInstanceId,
    toggleLayerVisibility,
    setLayerOpacity,
    addLayer,
    selectLayer,
    setSidebarView,
    getCatalogAddBlockReason,
    removeLayer,
    bringLayerToFront,
    sendLayerToBack,
    setLayerPaletteOverride,
    setLayerRangeOverride,
  }),
}));

vi.mock("@/stores/ui", () => ({
  useUiStore: () => ({
    get currentHour() {
      return currentHour.value;
    },
    get currentDate() {
      return currentDate.value;
    },
    applyDateHour,
    setHour,
    play,
    pause,
  }),
}));

vi.mock("@/components/map/layer-symbology", () => ({
  isMapLinkedPalette: () => true,
  resolveCanonicalPaletteIdStrict: (id: string) => id,
  WEATHER_PALETTE_OPTIONS: [
    { id: "viridis", label: "Viridis" },
    { id: "plasma", label: "Plasma" },
    { id: "thermal", label: "热力橙红" },
  ],
}));

describe("executeAgentUiIntent", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    activeLayers.value = [
      {
        instanceId: "i1",
        catalogId: "cmfd-precip-cn",
        visible: false,
        opacity: 1,
      },
    ];
    vi.clearAllMocks();
  });

  it("toggles visibility on when requested", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = await executeAgentUiIntent({
      name: "set_layer_visibility",
      args: { catalog_id: "cmfd-precip-cn", visible: true },
    });
    expect(result.ok).toBe(true);
    expect(toggleLayerVisibility).toHaveBeenCalledWith("i1");
    expect(activeLayers.value[0]?.visible).toBe(true);
  });

  it("adds layer when missing then shows it", async () => {
    activeLayers.value = [];
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = await executeAgentUiIntent({
      name: "set_layer_visibility",
      args: { catalog_id: "dem-etopo", visible: true },
    });
    expect(addLayer).toHaveBeenCalledWith("dem-etopo");
    expect(result.ok).toBe(true);
  });

  it("refuses to add when catalog is blocked", async () => {
    activeLayers.value = [];
    getCatalogAddBlockReason.mockReturnValueOnce("无权限");
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = await executeAgentUiIntent({
      name: "set_layer_visibility",
      args: { catalog_id: "secret-layer", visible: true },
    });
    expect(result.ok).toBe(false);
    expect(addLayer).not.toHaveBeenCalled();
  });

  it("sets opacity", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = await executeAgentUiIntent({
      name: "set_layer_opacity",
      args: { catalog_id: "cmfd-precip-cn", opacity: 0.5 },
    });
    expect(result.ok).toBe(true);
    expect(setLayerOpacity).toHaveBeenCalledWith("i1", 0.5);
  });

  it("fits layer via handler", async () => {
    const fit = vi.fn(() => true);
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = await executeAgentUiIntent(
      { name: "fit_layer", args: { catalog_id: "cmfd-precip-cn" } },
      { fitToLayerExtent: fit },
    );
    expect(result.ok).toBe(true);
    expect(fit).toHaveBeenCalledWith("i1");
  });

  it("lists active layers with names instead of opaque placeholder", async () => {
    activeLayers.value = [
      {
        instanceId: "i1",
        catalogId: "cmfd-precip-cn",
        visible: true,
        opacity: 1,
        name: "CMFD 降水",
      },
      {
        instanceId: "i2",
        catalogId: "admin-boundary",
        visible: true,
        opacity: 1,
        isAdminBoundary: true,
        name: "边界",
      },
    ];
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = await executeAgentUiIntent({
      name: "list_active_layers",
      args: {},
    });
    expect(result.ok).toBe(true);
    expect(result.message).toContain("CMFD 降水");
    // 正文只给人看的中文名，内部 catalog_id 不进对话
    expect(result.message).not.toContain("cmfd-precip-cn");
    expect(result.message).not.toContain("已使用客户端活动图层上下文");
    expect(result.message).not.toContain("边界");
  });

  it("reports empty active layers clearly", async () => {
    activeLayers.value = [];
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = await executeAgentUiIntent({
      name: "list_active_layers",
      args: {},
    });
    expect(result.ok).toBe(true);
    expect(result.message).toContain("没有活动图层");
  });

  it("handles fit_china and zoom_to_china intent via handler", async () => {
    const fitChina = vi.fn(() => true);
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res1 = await executeAgentUiIntent(
      { name: "fit_china", args: {} },
      { fitChina },
    );
    expect(res1.ok).toBe(true);
    expect(fitChina).toHaveBeenCalledTimes(1);
    expect(res1.message).toContain("中国全境");

    const res2 = await executeAgentUiIntent(
      { name: "zoom_to_china", args: {} },
      { fitChina },
    );
    expect(res2.ok).toBe(true);
    expect(fitChina).toHaveBeenCalledTimes(2);

    const resFail = await executeAgentUiIntent(
      { name: "fit_china", args: {} },
      {},
    );
    expect(resFail.ok).toBe(false);
  });

  it("handles locate_coordinate intent via handler", async () => {
    const locate = vi.fn(() => true);
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent(
      {
        name: "locate_coordinate",
        args: { lng: 116.4074, lat: 39.9042, zoom: 11 },
      },
      { locateCoordinate: locate },
    );
    expect(res.ok).toBe(true);
    expect(locate).toHaveBeenCalledWith(116.4074, 39.9042, 11);
    expect(res.message).toContain("116.4074");

    const resInvalid = await executeAgentUiIntent(
      { name: "locate_coordinate", args: { lng: "abc" } },
      { locateCoordinate: locate },
    );
    expect(resInvalid.ok).toBe(false);

    const resOutOfRange = await executeAgentUiIntent(
      { name: "locate_coordinate", args: { lng: 200, lat: 39 } },
      { locateCoordinate: locate },
    );
    expect(resOutOfRange.ok).toBe(false);
    expect(locate).toHaveBeenCalledTimes(1);
  });

  it("handles switch_basemap intent via handler", async () => {
    const setBasemap = vi.fn(() => true);
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent(
      { name: "switch_basemap", args: { basemap_id: "tianditu-img" } },
      { setBasemap },
    );
    expect(res.ok).toBe(true);
    expect(setBasemap).toHaveBeenCalledWith("tianditu-img");
    // source id 是内部标识，只用于调用 handler，不出现在给人看的文案里
    expect(res.message).not.toContain("tianditu-img");

    const resEmpty = await executeAgentUiIntent(
      { name: "switch_basemap", args: {} },
      { setBasemap },
    );
    expect(resEmpty.ok).toBe(false);

    const setBasemapFail = vi.fn(() => false);
    const resUnknown = await executeAgentUiIntent(
      { name: "switch_basemap", args: { basemap_id: "not-a-real-basemap" } },
      { setBasemap: setBasemapFail },
    );
    expect(resUnknown.ok).toBe(false);
    expect(setBasemapFail).toHaveBeenCalledWith("not-a-real-basemap");
  });

  it("sets timeline hour and date with local date label", async () => {
    applyDateHour.mockImplementation((d: Date, h: number) => {
      currentDate.value = d;
      currentHour.value = h;
    });
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent({
      name: "set_timeline",
      args: { hour: 8, date: "2024-06-01" },
    });
    expect(res.ok).toBe(true);
    expect(applyDateHour).toHaveBeenCalled();
    // Must use local YYYY-MM-DD, not toISOString().slice(0,10) (UTC shift)
    expect(res.message).toContain("2024-06-01");
    expect(res.message).not.toContain("T00:00");
  });

  it("reports the frame that actually shows when the day has data", async () => {
    applyDateHour.mockImplementation((d: Date, h: number) => {
      currentDate.value = d;
      currentHour.value = h;
    });
    activeLayers.value = [
      {
        instanceId: "i1",
        catalogId: "imported-38993117b963",
        visible: true,
        opacity: 0.9,
        name: "土壤水分（SMAP 平均）",
        importedRaster: { timeList: ["20251201", "20251202", "20251203"] },
      },
    ];
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent({
      name: "set_timeline",
      args: { date: "2025-12-02" },
    });
    expect(res.ok).toBe(true);
    expect(res.message).toContain("2025-12-02");
    expect(res.message).toContain("土壤水分（SMAP 平均）");
    expect(res.message).not.toContain("imported-38993117b963");
  });

  it("says the day has no data instead of pretending it switched", async () => {
    applyDateHour.mockImplementation((d: Date, h: number) => {
      currentDate.value = d;
      currentHour.value = h;
    });
    activeLayers.value = [
      {
        instanceId: "i1",
        catalogId: "imported-38993117b963",
        visible: true,
        opacity: 0.9,
        name: "土壤水分（SMAP 平均）",
        importedRaster: { timeList: ["20251201", "20251202", "20251203"] },
      },
    ];
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent({
      name: "set_timeline",
      args: { date: "2025-12-20" },
    });
    // 该日不在帧清单里、且页面没接上取帧入口：必须明说「没接上」，
    // 不能再糊成「该日落在时间块内」——那会让人以为只是块粒度问题。
    expect(res.ok).toBe(false);
    expect(res.message).toContain("没接上");
    expect(res.message).toContain("2025-12-03");
  });

  it("fetches an on-demand frame when the day is outside the frame list", async () => {
    applyDateHour.mockImplementation((d: Date, h: number) => {
      currentDate.value = d;
      currentHour.value = h;
    });
    activeLayers.value = [
      {
        instanceId: "i1",
        catalogId: "imported-38993117b963",
        visible: true,
        opacity: 0.9,
        name: "土壤水分（SMAP 平均）",
        importedRaster: { timeList: ["20251201", "20251202", "20251203"] },
      },
    ];
    const ensureOnDemandFrame = vi.fn(async () => ({
      ok: true,
      applied: true,
      cached: false,
    }));
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent(
      { name: "set_timeline", args: { date: "2025-12-20" } },
      { ensureOnDemandFrame },
    );
    expect(ensureOnDemandFrame).toHaveBeenCalledWith(
      "imported-38993117b963",
      expect.any(Date),
    );
    expect(res.ok).toBe(true);
    expect(res.message).toContain("单日图");
    expect(res.message).toContain("刚从取数服务取得");
  });

  it("reports the fetch failure reason instead of pretending success", async () => {
    applyDateHour.mockImplementation((d: Date, h: number) => {
      currentDate.value = d;
      currentHour.value = h;
    });
    activeLayers.value = [
      {
        instanceId: "i1",
        catalogId: "imported-38993117b963",
        visible: true,
        opacity: 0.9,
        name: "土壤水分（SMAP 平均）",
        importedRaster: { timeList: ["20251201", "20251202", "20251203"] },
      },
    ];
    const ensureOnDemandFrame = vi.fn(async () => ({
      ok: false,
      applied: false,
      cached: false,
      message: "NAS 成果不覆盖这一天",
    }));
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent(
      { name: "set_timeline", args: { date: "2025-12-20" } },
      { ensureOnDemandFrame },
    );
    expect(res.ok).toBe(false);
    expect(res.message).toContain("2025-12-03");
    expect(res.message).toContain("该日没有可用的单日数据");
    expect(res.message).not.toContain("NAS");
  });

  it("toggles timeline playing", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const started = await executeAgentUiIntent({
      name: "set_timeline_playing",
      args: { playing: true },
    });
    expect(started.ok).toBe(true);
    expect(play).toHaveBeenCalled();
    const paused = await executeAgentUiIntent({
      name: "set_timeline_playing",
      args: { playing: false },
    });
    expect(paused.ok).toBe(true);
    expect(pause).toHaveBeenCalled();
  });

  it("accepts string booleans and rejects missing playing", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    // 模型偶尔把布尔写成字符串：旧实现 typeof !== 'boolean' 直接拒
    const asString = await executeAgentUiIntent({
      name: "set_timeline_playing",
      args: { playing: "true" },
    });
    expect(asString.ok).toBe(true);
    expect(play).toHaveBeenCalled();
    // 真没传必须仍当失败，不能被 strictBool 的 false 兜成「暂停」
    const missing = await executeAgentUiIntent({
      name: "set_timeline_playing",
      args: {},
    });
    expect(missing.ok).toBe(false);
  });

  it("removes layer when not running", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent({
      name: "remove_layer",
      args: { catalog_id: "cmfd-precip-cn" },
    });
    expect(res.ok).toBe(true);
    // 只从面板移除，不删后端产物（与侧栏 × 行为一致）
    expect(removeLayer).toHaveBeenCalledWith("i1", {
      deleteBackendFile: false,
    });
  });

  it("refuses remove when job is running", async () => {
    activeLayers.value = [
      {
        instanceId: "i1",
        catalogId: "cmfd-precip-cn",
        visible: true,
        opacity: 1,
        jobLayer: { status: "running" },
      },
    ];
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent({
      name: "remove_layer",
      args: { catalog_id: "cmfd-precip-cn" },
    });
    expect(res.ok).toBe(false);
    expect(removeLayer).not.toHaveBeenCalled();
  });

  it("reorders layer to front", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent({
      name: "reorder_layer",
      args: { catalog_id: "cmfd-precip-cn", action: "front" },
    });
    expect(res.ok).toBe(true);
    expect(bringLayerToFront).toHaveBeenCalledWith("i1");
  });

  it("sets layer symbology palette and range", async () => {
    activeLayersDisplay.value = [
      { instanceId: "i1", renderHint: { palette: "thermal" } },
    ];
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent({
      name: "set_layer_symbology",
      args: {
        catalog_id: "cmfd-precip-cn",
        palette: "viridis",
        vmin: 0,
        vmax: 10,
      },
    });
    expect(res.ok).toBe(true);
    expect(setLayerPaletteOverride).toHaveBeenCalledWith("i1", "viridis");
    expect(setLayerRangeOverride).toHaveBeenCalledWith("i1", {
      vmin: 0,
      vmax: 10,
    });
  });

  it("rejects an unknown palette instead of silently doing nothing", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = await executeAgentUiIntent({
      name: "set_layer_symbology",
      args: { catalog_id: "cmfd-precip-cn", palette: "rainbow-ultra" },
    });
    // 旧实现：认不出来也照样落库，渲染时被兜底成默认色带 ⇒ 回执说「已换配色」但颜色没变
    expect(res.ok).toBe(false);
    expect(setLayerPaletteOverride).not.toHaveBeenCalled();
    expect(res.message).toContain("viridis");
  });

  it("rejects a half date instead of quietly picking a day", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const monthOnly = await executeAgentUiIntent({
      name: "set_timeline",
      args: { date: "2025-12" },
    });
    // new Date("2025-12") 会被宽松解析成 12-01，助手就会真的切到某一天
    expect(monthOnly.ok).toBe(false);
    expect(applyDateHour).not.toHaveBeenCalled();

    const noDash = await executeAgentUiIntent({
      name: "set_timeline",
      args: { date: "20251215" },
    });
    expect(noDash.ok).toBe(false);

    const okDash = await executeAgentUiIntent({
      name: "set_timeline",
      args: { date: "2025-12-15" },
    });
    expect(okDash.ok).toBe(true);
  });
});
