import { describe, expect, it } from "vitest";
import {
  buildAgentClientContextPayload,
  exportChatMarkdown,
  extractLayerCardsFromSteps,
  formatLocalDateKey,
  isAbortError,
  isTimeoutAbortError,
  isUserInitiatedStop,
  layerCardsFromActiveLayers,
  layerDisplayName,
  looksLikeInternalId,
  readableFrameLabel,
  resolveEffectiveFrame,
  sumSessionTokens,
  summarizeTimeRange,
} from "@/components/agent/agent-chat-helpers";

describe("agent-chat-helpers", () => {
  it("keeps overlay_layer_id in the client context (point sampling needs it)", () => {
    const ctx = buildAgentClientContextPayload({
      layers: [
        {
          catalogId: "imported-38993117b963",
          instanceId: "i1",
          name: "土壤水分（SMAP 平均）",
          overlayLayerId: "imported-38993117b963",
        },
        { catalogId: "admin-boundary", name: "边界", isAdminBoundary: true },
      ],
      timeline: { hour: 0, date: new Date(2025, 11, 3), playing: false },
      viewport: {},
      basemapId: "tianditu-img",
      dataRange: { start: "20251201", end: "20260201", frames: 63 },
    });
    expect(ctx.active_layers[0]?.overlay_layer_id).toBe(
      "imported-38993117b963",
    );
    expect(ctx.active_layers).toHaveLength(1);
    expect(ctx.timeline.date).toBe("2025-12-03");
    expect(ctx.timeline.data_range).toEqual({
      start: "20251201",
      end: "20260201",
      frames: 63,
    });
  });

  it("omits data_range when nothing to report", () => {
    const ctx = buildAgentClientContextPayload({
      layers: [],
      timeline: { hour: 0, date: new Date(2025, 11, 3), playing: false },
      viewport: {},
      basemapId: "tianditu-img",
      dataRange: null,
    });
    expect(ctx.timeline.data_range).toBeUndefined();
  });

  it("flags internal ids", () => {
    expect(looksLikeInternalId("imported-38993117b963")).toBe(true);
    expect(looksLikeInternalId("123456677")).toBe(true);
    expect(looksLikeInternalId("20251201")).toBe(true);
    expect(looksLikeInternalId("20251201_20260201")).toBe(true);
    expect(looksLikeInternalId("土壤水分（SMAP 平均）")).toBe(false);
  });

  it("falls back to 该图层 instead of the raw catalog id", () => {
    expect(layerDisplayName("imported-38993117b963", [])).toBe("该图层");
    expect(
      layerDisplayName("imported-38993117b963", [
        { catalogId: "imported-38993117b963", name: "土壤水分（SMAP 平均）" },
      ]),
    ).toBe("土壤水分（SMAP 平均）");
    // 名字本身是 id 形态时也不显示
    expect(
      layerDisplayName("imported-abc", [
        { catalogId: "imported-abc", name: "imported-abc" },
      ]),
    ).toBe("该图层");
  });

  it("renders frame keys as readable dates", () => {
    expect(readableFrameLabel("20251203")).toBe("2025-12-03");
    expect(readableFrameLabel("20251203_20251212")).toBe(
      "2025-12-03 至 2025-12-12",
    );
    expect(readableFrameLabel("weird")).toBe("weird");
  });

  it("resolves the frame that actually shows for a requested instant", () => {
    const list = ["20251201", "20251202", "20251203"];
    const hit = resolveEffectiveFrame(list, new Date(2025, 11, 2), 0);
    expect(hit?.key).toBe("20251202");
    expect(hit?.nativeMatch).toBe(true);

    // 该日没有帧 ⇒ 吸附到最近的可用帧，并标记非原生命中
    const miss = resolveEffectiveFrame(list, new Date(2025, 11, 20), 0);
    expect(miss?.key).toBe("20251203");
    expect(miss?.nativeMatch).toBe(false);

    expect(resolveEffectiveFrame([], new Date(2025, 11, 2), 0)).toBeNull();
  });

  it("summarizes the dominant time range", () => {
    expect(summarizeTimeRange(["20251201", "20251202", "20260201"])).toEqual({
      start: "20251201",
      end: "20260201",
      frames: 3,
    });
    expect(summarizeTimeRange(["20251201_20251210", "20260201"])).toEqual({
      start: "20251201",
      end: "20260201",
      frames: 2,
    });
    expect(summarizeTimeRange([])).toBeNull();
    expect(summarizeTimeRange(null)).toBeNull();
  });

  it("extracts layer cards from search_layers tool_result steps", () => {
    const cards = extractLayerCardsFromSteps([
      {
        type: "tool_result",
        summary: "search_layers",
        detail: JSON.stringify({
          ok: true,
          query: "降水",
          layers: [
            { layer_id: "cmfd-precip-cn", display_name: "CMFD 降水" },
            { layer_id: "cmfd-precip-cn", display_name: "dup" },
            { catalog_id: "dem-etopo", display_name: "DEM" },
          ],
        }),
      },
    ]);
    expect(cards).toEqual([
      { catalog_id: "cmfd-precip-cn", display_name: "CMFD 降水" },
      { catalog_id: "dem-etopo", display_name: "DEM" },
    ]);
  });

  it("builds cards from active layers and sums tokens", () => {
    expect(
      layerCardsFromActiveLayers([
        { catalogId: "a", name: "A" },
        { catalog_id: "b" },
      ]),
    ).toEqual([
      { catalog_id: "a", display_name: "A" },
      { catalog_id: "b", display_name: "b" },
    ]);
    expect(
      sumSessionTokens([
        { usage: { total_tokens: 10 } },
        { usage: { total_tokens: 5 } },
        { usage: null },
      ]),
    ).toBe(15);
  });

  it("detects abort errors and exports markdown", () => {
    expect(isAbortError(new DOMException("Aborted", "AbortError"))).toBe(true);
    expect(isAbortError(new Error("The user aborted a request."))).toBe(true);
    expect(isAbortError(new Error("boom"))).toBe(false);

    const md = exportChatMarkdown(
      [
        { role: "user", text: "打开降水" },
        {
          role: "assistant",
          text: "已打开",
          usage: { total_tokens: 12, estimated: true },
        },
      ],
      { sessionId: "abc", title: "测试会话" },
    );
    expect(md).toContain("# 测试会话");
    expect(md).toContain("session_id: `abc`");
    expect(md).toContain("## 用户");
    expect(md).toContain("打开降水");
    expect(md).toContain("tokens: 12（估）");
  });

  it("distinguishes user stop vs timeout abort", () => {
    const c = new AbortController();
    expect(isUserInitiatedStop(c.signal)).toBe(false);
    c.abort();
    expect(isUserInitiatedStop(c.signal)).toBe(true);

    expect(
      isTimeoutAbortError(new DOMException("请求超时", "AbortError")),
    ).toBe(true);
    expect(isTimeoutAbortError(new DOMException("Aborted", "AbortError"))).toBe(
      false,
    );
    expect(isTimeoutAbortError(new DOMException("timeout", "AbortError"))).toBe(
      true,
    );
    // Timeout-shaped error alone is not a user stop; only the user signal matters
    expect(isUserInitiatedStop(new AbortController().signal)).toBe(false);
  });

  it("builds client_context with timeline / viewport / basemap (local date)", () => {
    const localDate = new Date(2024, 5, 15); // June 15 local — not UTC ISO
    const payload = buildAgentClientContextPayload({
      layers: [
        { catalogId: "cmfd-precip-cn", instanceId: "i1", name: "降水" },
        { catalogId: "admin-cn", isAdminBoundary: true },
      ],
      mapPoint: { lng: 116.4, lat: 39.9 },
      timeline: { hour: 8, date: localDate, playing: true },
      viewport: {
        center: { lng: 105, lat: 35 },
        zoom: 4.5,
        bbox: [70, 15, 140, 55],
      },
      basemapId: "tianditu-vec",
    });
    expect(payload.active_catalog_ids).toEqual(["cmfd-precip-cn"]);
    expect(payload.timeline).toEqual({
      hour: 8,
      date: formatLocalDateKey(localDate),
      playing: true,
    });
    expect(payload.timeline.date).toBe("2024-06-15");
    expect(payload.viewport).toEqual({
      center: [105, 35],
      zoom: 4.5,
      bbox: [70, 15, 140, 55],
    });
    expect(payload.basemap_id).toBe("tianditu-vec");
    expect(payload.map_point).toEqual({ lng: 116.4, lat: 39.9 });
  });
});
