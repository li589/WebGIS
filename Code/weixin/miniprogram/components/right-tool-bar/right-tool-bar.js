/**
 * right-tool-bar —— 右侧竖向图层大类导航栏。
 *
 * 设计：竖向工具栏贴右边缘，每个图标代表一个图层大类；
 * 点击图标 → 紧贴工具栏左侧弹出标签面板，列出该大类下全部图层。
 *
 * 哑组件：categories / activeLayerId 由父级（map-shell）下发，
 * 选中图层通过 triggerEvent('select', { layerId }) 抛出，业务由 map-shell 处理。
 * 内部不发起任何 wx.request 网络请求。
 *
 * 演示模式（fallback）：当 properties.categories 为空（后端未接入或接口失败）
 * 时，自动加载 FALLBACK_CATEGORIES 占位数据用于验证 UI 骨架。后端接入后
 * properties.categories 有值，无缝切换为真实数据，零改动。
 */

/** 大类图标 SVG（base64 内联，避免外部字体/图片资源）。
 *  简约描边风格：fill=none，统一色 #3a3f4a（深灰描边），stroke-linecap round。
 *  key = category.id（小写），未命中时回落首字母圆形（由 wxml 处理）。
 *  扩展：新增大类只需在此映射表加一项即可。
 *  所有 SVG 画布 22×22 居中，stroke-width 1.6 以在 20px 显示尺寸下有精致描边感。 */
var ICON_SVG = {
  // 气候类（climate / c）— 太阳：圆 + 8 射线，纯描边
  c: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIyIDIyIiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxjaXJjbGUgY3g9IjExIiBjeT0iMTEiIHI9IjMuNSIgc3Ryb2tlPSIjM2EzZjRhIiBzdHJva2Utd2lkdGg9IjEuNiIvPjxnIHN0cm9rZT0iIzNhM2Y0YSIgc3Ryb2tlLXdpZHRoPSIxLjYiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCI+PGxpbmUgeDE9IjExIiB5MT0iMyIgeDI9IjExIiB5Mj0iNSIvPjxsaW5lIHgxPSIxMSIgeTE9IjE3IiB4Mj0iMTEiIHkyPSIxOSIvPjxsaW5lIHgxPSIzIiB5MT0iMTEiIHgyPSI1IiB5Mj0iMTEiLz48bGluZSB4MT0iMTciIHkxPSIxMSIgeDI9IjE5IiB5Mj0iMTEiLz48bGluZSB4MT0iNS4zIiB5MT0iNS4zIiB4Mj0iNi43IiB5Mj0iNi43Ii8+PGxpbmUgeDE9IjE1LjMiIHkxPSIxNS4zIiB4Mj0iMTYuNyIgeTI9IjE2LjciLz48bGluZSB4MT0iNS4zIiB5MT0iMTYuNyIgeDI9IjYuNyIgeTI9IjE1LjMiLz48bGluZSB4MT0iMTUuMyIgeTE9IjYuNyIgeDI9IjE2LjciIHkyPSI1LjMiLz48L2c+PC9zdmc+',
  // 土地利用/覆盖类（land / l）— 网格：2×2 方格，纯描边
  l: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIyIDIyIiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxyZWN0IHg9IjMiIHk9IjMiIHdpZHRoPSI3IiBoZWlnaHQ9IjciIHJ4PSIxIiBzdHJva2U9IiMzYTNmNGEiIHN0cm9rZS13aWR0aD0iMS42Ii8+PHJlY3QgeD0iMTIiIHk9IjMiIHdpZHRoPSI3IiBoZWlnaHQ9IjciIHJ4PSIxIiBzdHJva2U9IiMzYTNmNGEiIHN0cm9rZS13aWR0aD0iMS42Ii8+PHJlY3QgeD0iMyIgeT0iMTIiIHdpZHRoPSI3IiBoZWlnaHQ9IjciIHJ4PSIxIiBzdHJva2U9IiMzYTNmNGEiIHN0cm9rZS13aWR0aD0iMS42Ii8+PHJlY3QgeD0iMTIiIHk9IjEyIiB3aWR0aD0iNyIgaGVpZ2h0PSI3IiByeD0iMSIgc3Ryb2tlPSIjM2EzZjRhIiBzdHJva2Utd2lkdGg9IjEuNiIvPjwvc3ZnPg==',
  // 地形/高程类（terrain / t）— 山形：3 座山峰轮廓，纯描边
  t: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIyIDIyIiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxwYXRoIGQ9Ik0yIDE4TDcgMTBMMTEgMTRMMTUgN0wyMCAxOCIgc3Ryb2tlPSIjM2EzZjRhIiBzdHJva2Utd2lkdGg9IjEuNiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBmaWxsPSJub25lIi8+PC9zdmc+',
  // 海洋类（ocean / o）— 水波：3 条正弦波线，纯描边
  o: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIyIDIyIiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxwYXRoIGQ9Ik0yIDhDNCA4IDUgNiA4LjUgNkMxMiA2IDEzIDggMTYuNSA4QzE5IDggMjAgNiAyMiA2IiBzdHJva2U9IiMzYTNmNGEiIHN0cm9rZS13aWR0aD0iMS42IiBzdHJva2UtbGluZWNhcD0icm91bmQiIGZpbGw9Im5vbmUiLz48cGF0aCBkPSJNMiAxMkM0IDEyIDUgMTAgOC41IDEwQzEyIDEwIDEzIDEyIDE2LjUgMTJDMTkgMTIgMjAgMTAgMjIgMTAiIHN0cm9rZT0iIzNhM2Y0YSIgc3Ryb2tlLXdpZHRoPSIxLjYiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgZmlsbD0ibm9uZSIvPjxwYXRoIGQ9Ik0yIDE2QzQgMTYgNSAxNCA4LjUgMTRDMTIgMTQgMTMgMTYgMTYuNSAxNkMxOSAxNiAyMCAxNCAyMiAxNCIgc3Ryb2tlPSIjM2EzZjRhIiBzdHJva2Utd2lkdGg9IjEuNiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBmaWxsPSJub25lIi8+PC9zdmc+',
  // 大气类（atmosphere / a）— 云：外轮廓，纯描边
  a: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIyIDIyIiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxwYXRoIGQ9Ik03IDE3LjVoMTAuNWMxLjggMCAzLjItMS40IDMuMi0zLjJIMjBWMTRDMjAgMTIuMyAxOC43IDExIDE3IDExYzAtMi4yLTEuOC00LTQtNGMtMS43IDAtMy4xIDEuMS0zLjYgMi41OEM4LjkgOS4yIDcuNSA5LjkgNi42IDExLjJDNC42IDExLjcgMyAxMy40IDMgMTUuNUMzIDE2LjcgMy45IDE3LjUgNS4yIDE3LjVIN1oiIHN0cm9rZT0iIzNhM2Y0YSIgc3Ryb2tlLXdpZHRoPSIxLjYiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgZmlsbD0ibm9uZSIvPjwvc3ZnPg==',
  // 降水类（precipitation / p）— 雨：云 + 3 滴斜线，纯描边
  p: 'PD94bWwgdmVyc2lvbj0iMS4wIiBlbmNvZGluZz0idXRmLTgiPz48c3ZnIHdpZHRoPSIyMCIgaGVpZ2h0PSIyMCIgdmlld0JveD0iMCAwIDIyIDIyIiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPjxwYXRoIGQ9Ik03IDEyLjVoMTAuNWMxLjggMCAzLjItMS40IDMuMi0zLjJIMjBWOC41QzIwIDYuOCAxOC43IDUuNSAxNyA1LjVjMC0yLjItMS44LTQtNC00Yy0xLjcgMC0zLjEgMS4xLTMuNiAyLjU4QzguOSAzLjcgNy41IDQuNCA2LjYgNS43QzQuNiA2LjIgMyA3LjkgMyAxMEMzIDExLjIgMy45IDEyLjUgNS4yIDEyLjVIN1oiIHN0cm9rZT0iIzNhM2Y0YSIgc3Ryb2tlLXdpZHRoPSIxLjYiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIgZmlsbD0ibm9uZSIvPjxnIHN0cm9rZT0iIzNhM2Y0YSIgc3Ryb2tlLXdpZHRoPSIxLjYiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCI+PHBhdGggZD0iTTggMTVsLTIgNCIvPjxwYXRoIGQ9Ik0xMiAxNWwtMiA0Ii8+PHBhdGggZD0iTTE2IDE1bC0yIDQiLz48L2c+PC9zdmc+'
};

/** 演示模式占位数据（后端未接入时显示）。
 *  结构与 catalogSvc.loadCatalog() 返回的 railCategories 完全一致：
 *  { id, name, icon, accentColor, count, layers: [{layerId, displayName, description, supportsTime, timeGranularity}] }
 *  扩展：调整此数组即可调整演示分类与图层数量。 */
var FALLBACK_CATEGORIES = [
  {
    id: 'climate',
    name: '气候数据',
    icon: 'C',
    accentColor: '#ff8c1a',
    count: 3,
    layers: [
      { layerId: 'demo-temperature', displayName: '近地表气温 2m', description: 'ERA5 再分析近地表 2 米气温，逐小时', supportsTime: true, timeGranularity: 'hour' },
      { layerId: 'demo-pressure', displayName: '海平面气压', description: '海平面气压场（hPa）', supportsTime: true, timeGranularity: 'hour' },
      { layerId: 'demo-windspeed', displayName: '10 米风速', description: 'ERA5 10 米水平风速', supportsTime: true, timeGranularity: 'hour' }
    ]
  },
  {
    id: 'land',
    name: '土地覆盖',
    icon: 'L',
    accentColor: '#52b788',
    count: 2,
    layers: [
      { layerId: 'demo-lucc', displayName: '土地利用变化 LUCC', description: '逐年土地利用类型（30m）', supportsTime: true, timeGranularity: 'year' },
      { layerId: 'demo-clcd', displayName: 'CLCD 土地覆盖', description: '中国区域年度 30m 土地覆盖产品', supportsTime: false, timeGranularity: null }
    ]
  },
  {
    id: 'terrain',
    name: '地形高程',
    icon: 'T',
    accentColor: '#9b8f5e',
    count: 2,
    layers: [
      { layerId: 'demo-dem-etopo', displayName: 'ETOPO 全球高程', description: 'ETOPO1 全球 1 弧分地形', supportsTime: false, timeGranularity: null },
      { layerId: 'demo-srtm', displayName: 'SRTM 高程', description: 'SRTM 30m 高程 DEM', supportsTime: false, timeGranularity: null }
    ]
  },
  {
    id: 'ocean',
    name: '海洋要素',
    icon: 'O',
    accentColor: '#1ea0fc',
    count: 2,
    layers: [
      { layerId: 'demo-sst', displayName: '海表温度 SST', description: 'OISST 海表温度逐日产品', supportsTime: true, timeGranularity: 'day' },
      { layerId: 'demo-ssh', displayName: '海表面高度 SSH', description: 'AVISO 绝对动力地形', supportsTime: true, timeGranularity: 'day' }
    ]
  },
  {
    id: 'atmosphere',
    name: '大气成分',
    icon: 'A',
    accentColor: '#6a8ca3',
    count: 2,
    layers: [
      { layerId: 'demo-co2', displayName: 'CO₂ 柱浓度 XCO₂', description: 'OCO-2/3 卫星反演总柱 CO₂', supportsTime: true, timeGranularity: 'month' },
      { layerId: 'demo-pm25', displayName: '近地面 PM2.5', description: '中国区域 1km PM2.5 浓度估算', supportsTime: true, timeGranularity: 'day' }
    ]
  },
  {
    id: 'precipitation',
    name: '降水数据',
    icon: 'P',
    accentColor: '#5ea6f2',
    count: 3,
    layers: [
      { layerId: 'demo-gpcp', displayName: 'GPCP 月降水', description: '全球 1° 逐月降水量（GPCP v2.3）', supportsTime: true, timeGranularity: 'month' },
      { layerId: 'demo-cmorph', displayName: 'CMORPH 日降水', description: '0.25° 逐小时融合降水', supportsTime: true, timeGranularity: 'day' },
      { layerId: 'demo-cn05', displayName: 'CN05.1 日降水', description: '中国区域 0.25° 格点化观测', supportsTime: true, timeGranularity: 'day' }
    ]
  }
];

function resolveIcon(catId) {
  if (!catId) return '';
  var key = String(catId).toLowerCase();
  // 取首字母兜底匹配（catalog id 一般为单字母前缀或小写全名）
  var first = key.charAt(0);
  return ICON_SVG[first] || ICON_SVG[key] || '';
}

function buildIcons(cats) {
  return (cats || []).map(function (c) {
    return resolveIcon(c.id);
  });
}

Component({
  options: {
    styleIsolation: 'apply-shared'
  },

  properties: {
    /** 大类列表（真实数据来自 map-shell / catalogSvc），结构同 FALLBACK_CATEGORIES 元素 */
    categories: {
      type: Array,
      value: []
    },
    /** 当前激活的图层 id（用于高亮 + 清除 loading 状态） */
    activeLayerId: {
      type: String,
      value: ''
    }
  },

  data: {
    /** 实际用于渲染的分类列表：properties.categories 非空时用它，否则回落 FALLBACK_CATEGORIES */
    displayCategories: [],
    /** 是否处于演示模式（回落时为 true，可用于 WXML 显示"演示"标记） */
    isFallback: false,
    expandedCatId: '',
    expandedCatName: '',
    expandedCatLayers: [],
    /** 每个大类的 SVG base64 */
    displayCatIcons: [],
    loadingLayerId: '',
    /** 面板 top 偏移：对齐被点击图标的 top（单位 px） */
    panelTop: 0
  },

  observers: {
    'categories': function (cats) {
      // 真实数据有值 → 用真实的；空 → 回落演示数据
      var useReal = Array.isArray(cats) && cats.length > 0;
      var display = useReal ? cats : FALLBACK_CATEGORIES;
      this.setData({
        displayCategories: display,
        displayCatIcons: buildIcons(display),
        isFallback: !useReal,
        // 数据源切换时收起面板，避免索引错位
        expandedCatId: '',
        expandedCatName: '',
        expandedCatLayers: []
      });
    },
    'activeLayerId': function () {
      if (this.data.loadingLayerId) {
        this.setData({ loadingLayerId: '' });
      }
    }
  },

  methods: {
    onIconTap: function (e) {
      var id = e.currentTarget.dataset.id;
      var name = e.currentTarget.dataset.name;
      var idx = e.currentTarget.dataset.index;
      // 从渲染用的 displayCategories 取分类（含 fallback 模式）
      var cats = this.data.displayCategories || [];
      // 同一图标再次点击 → 收起（保留 panelTop，避免收回时面板先跳回顶部）
      if (this.data.expandedCatId === id) {
        this.setData({
          expandedCatId: '',
          expandedCatName: '',
          expandedCatLayers: []
        });
        return;
      }
      var cat = cats[idx] || {};
      var layers = cat.layers || [];
      // 面板 top 对齐被点击图标的 top：
      // 工具栏顶部内边距 4px + 每个图标高 46px × idx
      var panelTop = 4 + idx * 46;
      this.setData({
        expandedCatId: id,
        expandedCatName: name || cat.name,
        expandedCatLayers: layers,
        panelTop: panelTop
      });
    },

    onLayerTap: function (e) {
      var layerId = e.currentTarget.dataset.id;
      if (!layerId) {
        return;
      }
      // 再点已选中图层 → 取消叠加（父级 selectLayer('') → teardown）
      if (layerId === this.properties.activeLayerId) {
        this.setData({ loadingLayerId: '' });
        this.triggerEvent('select', { layerId: '' });
        return;
      }
      this.setData({ loadingLayerId: layerId });
      this.triggerEvent('select', { layerId: layerId });
    },

    /** 点击遮罩收起面板（保留 panelTop，避免收回时面板先跳回顶部） */
    onMaskTap: function () {
      this.setData({
        expandedCatId: '',
        expandedCatName: '',
        expandedCatLayers: []
      });
    },

    noop: function () {
      // 阻止面板内滚动穿透
    }
  }
});
