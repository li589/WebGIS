/**
 * Display-only Chinese labels for workflow port names / common param keys.
 * Serialization still uses English `name` / `key`.
 */

const PORT_LABELS: Record<string, string> = {
  time_range: '时间范围',
  bbox: '空间范围',
  region: '区域',
  manifest: '清单',
  path: '路径',
  data: '数据',
  raster: '栅格',
  dem: 'DEM',
  vector: '矢量',
  points: '点',
  pour_points: '出水点',
  zones: '分区',
  mask: '掩膜',
  primary: '主数据',
  secondary: '次数据',
  x: '序列 X',
  y: '序列 Y',
  timeseries: '时间序列',
  coefficient: '相关系数',
  summary: '摘要',
  filepath: '文件路径',
  watershed: '流域',
  buffer: '缓冲区',
  slope: '坡度',
  aspect: '坡向',
  contour: '等高线',
  merged: '融合结果',
  a: '输入 A',
  b: '输入 B',
}

const PARAM_LABELS: Record<string, string> = {
  start_date: '开始日期',
  end_date: '结束日期',
  target_crs: '目标坐标系',
  resampling: '重采样',
  target_resolution: '目标分辨率',
  method: '方法',
  band: '波段',
  bins: '分箱数',
  format: '格式',
  title: '标题',
  chart_type: '图表类型',
  x_label: 'X 轴标签',
  y_label: 'Y 轴标签',
  write_png: '写出 PNG',
  flow_direction: '流向算法',
  fill_threshold: '填洼阈值',
  lag_days: '滞后天数',
  distance: '缓冲距离',
  distance_unit: '距离单位',
  statistic: '统计量',
  interval: '等高距',
  local_path: '本地路径',
  dataset_key: '数据集键',
  pattern: '匹配模式',
  path: '路径',
  main_layers: '主产出图层',
}

/** Short Chinese label for a port `name`; falls back to name. */
export function portDisplayLabel(name: string, description?: string): string {
  if (PORT_LABELS[name]) return PORT_LABELS[name]
  // Prefer a short first clause from Chinese description when available
  const desc = (description || '').trim()
  if (desc && /[\u4e00-\u9fff]/.test(desc)) {
    const short = desc.split(/[。；;，,]/)[0]?.trim() ?? ''
    if (short.length > 0 && short.length <= 12) return short
  }
  return name
}

/** Short Chinese label for a param `key`; prefer explicit map, then short description. */
export function paramDisplayLabel(key: string, description?: string): string {
  if (PARAM_LABELS[key]) return PARAM_LABELS[key]
  const desc = (description || '').trim()
  if (desc && /[\u4e00-\u9fff]/.test(desc)) {
    const short = desc.split(/[。；;，,]/)[0]?.trim() ?? ''
    if (short.length > 0 && short.length <= 16) return short
  }
  return key
}
