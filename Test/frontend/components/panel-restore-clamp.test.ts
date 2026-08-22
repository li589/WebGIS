// @vitest-environment jsdom
import { describe, expect, it, beforeEach } from "vitest";

import { usePanelDragResize } from "@/components/ui/usePanelDragResize";

describe("面板恢复路径的越界 offset clamp（2026-08-23 分析面板消失回归）", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("持久化的越界 offsetX/offsetY 恢复时被 clamp 回可视范围", () => {
    // 模拟异常写入/旧版本数据：面板被挪到屏幕外（巨大偏移）
    window.localStorage.setItem(
      "geo-panel:analysis",
      JSON.stringify({
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
});
