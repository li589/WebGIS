/** 统一结果图层显示名：`{工作流短名} · {PRODUCT} · {time_label|静态}` */

/**
 * 数据文件扩展名清单（显示名剥离用）。
 * 与后端 `python_provider_result_builder._resolve_product_display_label`
 * 的正则保持一致——跨语言共享同一清单，改须两处同步（P2-C 收敛，
 * 2026-08-24：此前 run-layers/expected-outputs/后端三处各自维护）。
 */
const DATA_EXTENSION_RE = /\.(tif|tiff|png|jpe?g|mat|nc|hdf5?|he5|zip|shp|csv|tar|gz)$/i

/** 剥数据文件扩展名（显示名不得泄漏 xxx.tif 等技术后缀）。 */
export function stripDataExtension(name: string): string {
  return name.replace(DATA_EXTENSION_RE, '')
}

/**
 * 产物显示名统一清洗：剥 materialize 标题前缀（map_layer/file 产物两类）
 * + 路径段（只留文件名）+ 数据扩展名。
 * 替代此前 run-layers 两处内联正则（今日三联报障 A 逐处打补丁的代价）。
 */
export function cleanProductDisplayName(title: string): string {
  return stripDataExtension(
    (title || '')
      .trim()
      .replace(/^Algorithm (?:Map Layer|Output):\s*/i, '')
      .replace(/\s*[/\\][^/\\]*$/, ''),
  ).trim()
}

export function shortWorkflowName(name: string | null | undefined, maxLen = 24): string {
  const raw = (name || '').trim()
  if (!raw) return '工作流'
  if (raw.length <= maxLen) return raw
  return `${raw.slice(0, Math.max(1, maxLen - 1))}…`
}

export function formatRunResultLayerName(input: {
  workflowName?: string | null
  productTag?: string | null
  timeLabel?: string | null
  staticLabel?: string
}): string {
  const wf = shortWorkflowName(input.workflowName)
  const product = (input.productTag || '结果').trim().toUpperCase()
  const time =
    (input.timeLabel || '').trim() || (input.staticLabel != null ? input.staticLabel : '静态')
  return `${wf} · ${product} · ${time}`
}
