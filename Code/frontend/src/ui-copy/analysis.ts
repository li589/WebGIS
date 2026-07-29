/** 分析面板顶部摘要 / 角标 / 阶段文案 */

export const ANALYSIS_COPY = {
  panelTitle: '分析',
  subtitleEmpty: '开始分析',
  subtitleWeather: '天气图层',
  subtitleStatic: '图层摘要',
  subtitleWorkflow: '工作流',
  subtitleImportedVector: '导入矢量',
  subtitleImportedRaster: '导入栅格',
  subtitleBoundary: '行政区边界',

  stageEmpty: '待选图层',
  stageWeather: '天气图层',
  stageLocal: '本地图层',
  stageImportedVector: '导入矢量',
  stageImportedRaster: '导入栅格',
  stageBoundary: '边界图层',
  stageWorkflow: '分析工作流',
  stageStatic: '静态图层',

  emptyLead: '从左侧图层面板添加数据图层后，可在此查看摘要、点查与样式。',
  emptyHintInspect: '添加天气层后，可用工具栏「选择」点击地图点查。',
  emptyHintWind: '风场层支持粒子流 / 流量场显示切换。',

  overviewImportedVector: (geometry: string, count: number) =>
    `本地导入矢量 · ${geometry} · ${count} 个要素`,
  overviewImportedRaster: '本地导入栅格（TIF）已注册为 overlay，可在此控制透明度与查看元信息。',
  overviewBoundary: '行政区边界为静态矢量叠加，不参与分析工作流。',
  importedSectionKicker: '导入',
  importedSectionTitle: '本地数据',
  importedRasterType: '栅格 · TIF overlay',
  selectedLayerKicker: '当前对象',
  selectedLayerTitle: '选中图层',
  overviewKicker: '总览',
  overviewTitleCompact: '图层说明',
  overviewTitleFull: '全图态势',

  weatherAutoLoad: '瓦片按视口自动加载，无需手动运行工作流。',
  weatherTileLine: (cached: number, visible: number, pending: number) =>
    `瓦片：已缓存 ${cached} / 可视 ${visible} / 加载中 ${pending}`,
  weatherNoTilesYet: '尚未缓存瓦片，平移或缩放地图以加载当前视口。',
  weatherWindMode: (modeLabel: string) => `风场显示：${modeLabel}`,

  staticImported: '本地导入图层：可在此调节透明度与样式；不参与分析工作流。',
  staticImportedVector: '导入矢量：可调颜色 / 线宽 / 点半径 / 透明度，并打开属性表。',
  staticImportedRaster: '导入栅格：预渲染图例只读，可调透明度；CRS 与范围见下方指标。',
  staticBoundary: '行政区边界为静态矢量叠加，不参与分析工作流。',
  staticOverlay: '该图层为静态叠加，直接在地图查看即可。',

  styleTitle: '图层样式',
  styleHintLinked: '图例与配色与地图符号化联动。',
  styleHintReadonly: '预渲染图例仅作对照，改配色不会重涂已生成的 PNG。',
  styleSectionKicker: '符号',

  metaLayer: '图层',
  metaSource: '来源',
  metaTime: '时间',
  metaMode: '显示',
  metaCrs: '坐标系',
  metaBounds: '范围',
  metaFeatures: '要素数',
  metaGeometry: '几何类型',
  metaWorkflow: '工作流来源',
  metaFile: '源文件',

  stageIdleReady: '就绪',
  stageIdleNotRun: '尚未运行',
  stageDone: '完成',
  stageFailed: '失败',
  stageLoading: '加载中',
  stageCached: '已缓存',
} as const
