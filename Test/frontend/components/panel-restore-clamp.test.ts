// @vitest-environment jsdom
import { describe, expect, it, beforeEach } from "vitest";

import {
  LAYOUT_SCHEMA_VERSION,
  usePanelDragResize,
} from "@/components/ui/usePanelDragResize";

describe("面板恢复路径的越界 offset clamp（2026-08-23 分析面板消失回归）", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("持久化的越界 offsetX/offsetY 恢复时被 clamp 回可视范围", () => {
    // 模拟异常写入/旧版本数据：面板被挪到屏幕外（巨大偏移）
    window.localStorage.setItem(
      "geo-panel:analysis",
      JSON.stringify({
        version: LAYOUT_SCHEMA_VERSION,
        visible: true,
        offsetX: 99999,
        offsetY: -99999,
      }),
    );

    const { frameStyle } = usePanelDragResize({
      panelKey: "analysis",
      maxOffsetX: 80,
      maxOffsetY: 110,
      defaultWidth: 400,
      defaultHeight: 600,
    });

    const transform = (frameStyle.value as { transform: string }).transform;
    expect(transform).toContain("translate(80px, -110px)");
  });

  it("合法范围内的小偏移保持原值（不误伤正常拖拽位置）", () => {
    window.localStorage.setItem(
      "geo-panel:analysis",
      JSON.stringify({
        version: LAYOUT_SCHEMA_VERSION,
        visible: true,
        offsetX: 30,
        offsetY: -50,
      }),
    );

    const { frameStyle } = usePanelDragResize({
      panelKey: "analysis",
      maxOffsetX: 80,
      maxOffsetY: 110,
      defaultWidth: 400,
      defaultHeight: 600,
    });

    const transform = (frameStyle.value as { transform: string }).transform;
    expect(transform).toContain("translate(30px, -50px)");
  });

  it("无持久化时默认 0 偏移", () => {
    const { frameStyle } = usePanelDragResize({
      panelKey: "analysis",
      maxOffsetX: 80,
      maxOffsetY: 110,
    });
    const transform = (frameStyle.value as { transform: string }).transform;
    expect(transform).toContain("translate(0px, 0px)");
  });

  it("隐藏态胶囊的越界 pillOffset 恢复时同样被 clamp", () => {
    window.localStorage.setItem(
      "geo-panel:analysis",
      JSON.stringify({
        version: LAYOUT_SCHEMA_VERSION,
        visible: false,
        pillOffsetX: 55555,
        pillOffsetY: 77777,
      }),
    );

    const { frameStyle } = usePanelDragResize({
      panelKey: "analysis",
      maxOffsetX: 80,
      maxOffsetY: 110,
    });
    const transform = (frameStyle.value as { transform: string }).transform;
    expect(transform).toContain("translate(80px, 110px)");
  });

  it("旧版布局（无版本号）整份作废：偏移归零且清掉旧键", () => {
    window.localStorage.setItem(
      "geo-panel:layers",
      JSON.stringify({
        visible: true,
        offsetX: 0,
        offsetY: -96,
        width: 326,
        height: 900,
      }),
    );

    const { frameStyle, panelSizeStyle } = usePanelDragResize({
      panelKey: "layers",
      maxOffsetX: 100,
      maxOffsetY: 110,
      defaultWidth: 326,
      defaultHeight: 450,
    });

    const transform = (frameStyle.value as { transform: string }).transform;
    expect(transform).toContain("translate(0px, 0px)");
    // 高度回到默认值，而不是沿用旧的 900
    expect((panelSizeStyle.value as Record<string, string>).height).toBe(
      "450px",
    );
    // 旧键被清掉，下次写入的会是带版本号的新格式
    expect(window.localStorage.getItem("geo-panel:layers")).toBeNull();
  });

  describe("autoHeight（2026-10-22 图层面板高度跟随内容）", () => {
    it("未手动缩放过时高度交给内容：fit-content", () => {
      const { panelSizeStyle } = usePanelDragResize({
        panelKey: "layers",
        autoHeight: true,
        defaultWidth: 326,
        defaultHeight: 450,
      });
      const style = panelSizeStyle.value as Record<string, string>;
      expect(style.height).toBe("fit-content");
      // fit-content 下不能再钉 min-height，否则矮内容也会被撑出空白
      expect(style.minHeight).toBeUndefined();
    });

    it("用户手动缩放过尺寸后固定成他的高度，不再跟随内容", () => {
      window.localStorage.setItem(
        "geo-panel:layers",
        JSON.stringify({
          version: LAYOUT_SCHEMA_VERSION,
          visible: true,
          offsetX: 0,
          offsetY: 0,
          width: 326,
          height: 620,
        }),
      );
      const { panelSizeStyle } = usePanelDragResize({
        panelKey: "layers",
        autoHeight: true,
        defaultWidth: 326,
        defaultHeight: 450,
        minHeight: 236,
      });
      const style = panelSizeStyle.value as Record<string, string>;
      expect(style.height).toBe("620px");
      expect(style.minHeight).toBe("236px");
    });
  });
});
