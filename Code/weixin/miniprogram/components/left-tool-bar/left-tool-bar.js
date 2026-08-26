/**
 * left-tool-bar —— 左上角竖向地图操作工具栏。
 *
 * 设计：4 个按钮（放大/缩小/指南针/定位），贴左上角 logo-badge 正下方。
 * 哑组件：纯 UI 渲染，所有动作通过 triggerEvent 抛出，
 * 由父级（map-shell）接收后调微信 MapContext / wx.getLocation 处理。
 * 内部不写任何地图业务逻辑、不调任何 wx API。
 *
 * 视觉与 right-tool-bar 完全统一：玻璃半透明、圆角 22px、内联 SVG 描边单色图标。
 */

/** 按钮图标 SVG（base64 内联，描边 #3a3f4a，stroke-width 1.6，与 right-tool-bar 同风格） */
var ICON_SVG = {
  // 放大：圆 + 四角加号
  zoomin: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyNiIgaGVpZ2h0PSIyNiIgdmlld0JveD0iMCAwIDI2IDI2IiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxjaXJjbGUgY3g9IjEzIiBjeT0iMTMiIHI9IjguNSIgc3Ryb2tlPSIjM2EzZjRhIiBzdHJva2Utd2lkdGg9IjEuNiIvPjxsaW5lIHgxPSIxMyIgeTE9IjkiIHgyPSIxMyIgeTI9IjE3IiBzdHJva2U9IiMzYTNmNGEiIHN0cm9rZS13aWR0aD0iMS44IiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48bGluZSB4MT0iOSIgeTE9IjEzIiB4Mj0iMTciIHkyPSIxMyIgc3Ryb2tlPSIjM2EzZjRhIiBzdHJva2Utd2lkdGg9IjEuOCIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIi8+PC9zdmc+',
  // 缩小：圆 + 横线
  zoomout: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyNiIgaGVpZ2h0PSIyNiIgdmlld0JveD0iMCAwIDI2IDI2IiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxjaXJjbGUgY3g9IjEzIiBjeT0iMTMiIHI9IjguNSIgc3Ryb2tlPSIjM2EzZjRhIiBzdHJva2Utd2lkdGg9IjEuNiIvPjxsaW5lIHgxPSI5IiB5MT0iMTMiIHgyPSIxNyIgeTI9IjEzIiBzdHJva2U9IiMzYTNmNGEiIHN0cm9rZS13aWR0aD0iMS44IiBzdHJva2UtbGluZWNhcD0icm91bmQiLz48L3N2Zz4=',
  // 地图方向指示器：圆角方框（不动）+ 中间纸飞机（顶点朝上、底边 V 形向上收）
  compass: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyNiIgaGVpZ2h0PSIyNiIgdmlld0JveD0iMCAwIDI2IDI2IiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxyZWN0IHg9IjQiIHk9IjQiIHdpZHRoPSIxOCIgaGVpZ2h0PSIxOCIgcng9IjQiIHN0cm9rZT0iIzNhM2Y0YSIgc3Ryb2tlLXdpZHRoPSIxLjYiIGZpbGw9Im5vbmUiLz48cGF0aCBkPSJNMTMgNEwxOCAyMEwxMyAxNUw4IDIwWiIgZmlsbD0iIzNhM2Y0YSIvPjwvc3ZnPg==',
  // 定位：水滴图标
  locate: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyNiIgaGVpZ2h0PSIyNiIgdmlld0JveD0iMCAwIDI2IDI2IiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxwYXRoIGQ9Ik0xMyAzQzkuNyAzIDcgNS43IDcgOUM3IDEzLjUgMTMgMjEgMTMgMjFTMTkgMTMuNSAxOSA5QzE5IDUuNyAxNi4zIDMgMTMgM1oiIHN0cm9rZT0iIzNhM2Y0YSIgc3Ryb2tlLXdpZHRoPSIxLjYiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgZmlsbD0ibm9uZSIvPjxjaXJjbGUgY3g9IjEzIiBjeT0iOSIgcj0iMyIgc3Ryb2tlPSIjM2EzZjRhIiBzdHJva2Utd2lkdGg9IjEuNiIvPjwvc3ZnPg=='
};

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  data: {
    zoomInIcon: ICON_SVG.zoomin,
    zoomOutIcon: ICON_SVG.zoomout,
    compassIcon: ICON_SVG.compass,
    locateIcon: ICON_SVG.locate
  },

  methods: {
    onZoomIn: function () {
      this.triggerEvent('zoomin');
    },
    onZoomOut: function () {
      this.triggerEvent('zoomout');
    },
    onResetNorth: function () {
      this.triggerEvent('resetnorth');
    },
    onLocate: function () {
      this.triggerEvent('locate');
    }
  }
});
