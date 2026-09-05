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
  activeLayers.value = activeLayers.value.filter((l) => l.instanceId !== instanceId);
});
const bringLayerToFront = vi.fn();
const sendLayerToBack = vi.fn();
const setLayerPaletteOverride = vi.fn();
const setLayerRangeOverride = vi.fn();
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
    const result = executeAgentUiIntent({
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
    const result = executeAgentUiIntent({
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
    const result = executeAgentUiIntent({
      name: "set_layer_visibility",
      args: { catalog_id: "secret-layer", visible: true },
    });
    expect(result.ok).toBe(false);
    expect(addLayer).not.toHaveBeenCalled();
  });

  it("sets opacity", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = executeAgentUiIntent({
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
    const result = executeAgentUiIntent(
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
    const result = executeAgentUiIntent({
      name: "list_active_layers",
      args: {},
    });
    expect(result.ok).toBe(true);
    expect(result.message).toContain("CMFD 降水");
    expect(result.message).toContain("cmfd-precip-cn");
    expect(result.message).not.toContain("已使用客户端活动图层上下文");
    expect(result.message).not.toContain("边界");
  });

  it("reports empty active layers clearly", async () => {
    activeLayers.value = [];
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const result = executeAgentUiIntent({
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
    const res1 = executeAgentUiIntent(
      { name: "fit_china", args: {} },
      { fitChina },
    );
    expect(res1.ok).toBe(true);
    expect(fitChina).toHaveBeenCalledTimes(1);
    expect(res1.message).toContain("中国全境");

    const res2 = executeAgentUiIntent(
      { name: "zoom_to_china", args: {} },
      { fitChina },
    );
    expect(res2.ok).toBe(true);
    expect(fitChina).toHaveBeenCalledTimes(2);

    const resFail = executeAgentUiIntent({ name: "fit_china", args: {} }, {});
    expect(resFail.ok).toBe(false);
  });

  it("handles locate_coordinate intent via handler", async () => {
    const locate = vi.fn(() => true);
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = executeAgentUiIntent(
      {
        name: "locate_coordinate",
        args: { lng: 116.4074, lat: 39.9042, zoom: 11 },
      },
      { locateCoordinate: locate },
    );
    expect(res.ok).toBe(true);
    expect(locate).toHaveBeenCalledWith(116.4074, 39.9042, 11);
    expect(res.message).toContain("116.4074");

    const resInvalid = executeAgentUiIntent(
      { name: "locate_coordinate", args: { lng: "abc" } },
      { locateCoordinate: locate },
    );
    expect(resInvalid.ok).toBe(false);

    const resOutOfRange = executeAgentUiIntent(
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
    const res = executeAgentUiIntent(
      { name: "switch_basemap", args: { basemap_id: "tianditu-img" } },
      { setBasemap },
    );
    expect(res.ok).toBe(true);
    expect(setBasemap).toHaveBeenCalledWith("tianditu-img");
    expect(res.message).toContain("tianditu-img");

    const resEmpty = executeAgentUiIntent(
      { name: "switch_basemap", args: {} },
      { setBasemap },
    );
    expect(resEmpty.ok).toBe(false);

    const setBasemapFail = vi.fn(() => false);
    const resUnknown = executeAgentUiIntent(
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
    const res = executeAgentUiIntent({
      name: "set_timeline",
      args: { hour: 8, date: "2024-06-01" },
    });
    expect(res.ok).toBe(true);
    expect(applyDateHour).toHaveBeenCalled();
    // Must use local YYYY-MM-DD, not toISOString().slice(0,10) (UTC shift)
    expect(res.message).toBe("已将时间轴设为 2024-06-01 08:00");
  });

  it("toggles timeline playing", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    expect(
      executeAgentUiIntent({
        name: "set_timeline_playing",
        args: { playing: true },
      }).ok,
    ).toBe(true);
    expect(play).toHaveBeenCalled();
    expect(
      executeAgentUiIntent({
        name: "set_timeline_playing",
        args: { playing: false },
      }).ok,
    ).toBe(true);
    expect(pause).toHaveBeenCalled();
  });

  it("removes layer when not running", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = executeAgentUiIntent({
      name: "remove_layer",
      args: { catalog_id: "cmfd-precip-cn" },
    });
    expect(res.ok).toBe(true);
    expect(removeLayer).toHaveBeenCalledWith("i1");
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
    const res = executeAgentUiIntent({
      name: "remove_layer",
      args: { catalog_id: "cmfd-precip-cn" },
    });
    expect(res.ok).toBe(false);
    expect(removeLayer).not.toHaveBeenCalled();
  });

  it("reorders layer to front", async () => {
    const { executeAgentUiIntent } =
      await import("@/components/agent/agent-ui-intent");
    const res = executeAgentUiIntent({
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
    const res = executeAgentUiIntent({
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
});
