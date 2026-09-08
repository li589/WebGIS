/**
 * 工作流状态消息「人话化」：把底层算法/调度产生的英文或参数化 stage 消息
 * 翻译为面向地理研究员的表述。仅做展示层翻译，原始消息保留在 title/tooltip。
 *
 * 覆盖规则见下方；未命中时原样返回（不破坏未知/新增消息）。
 */
const ARTIFACT_LABELS: Record<string, string> = {
  fy_daily_tif: '逐日亮温（TIF）',
  fy_daily_mat: '逐日亮温（MAT）',
  smap_daily_mat: 'SMAP 逐日（MAT）',
  gldas_mat: 'GLDAS 温度（MAT）',
  fy_preprocessed_dir: '风云预处理产物',
  omega_avg_daily: '平均 ω 逐日产物',
}

function ymdToCn(value: string): string {
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`
}

const NODE_LABELS: Record<string, string> = {
  fy_plan: '风云作业规划',
  fy_execute: '风云产品执行',
  fy_download: '风云数据下载',
  fy_preprocess: '风云预处理',
  fy_daily: '风云逐日处理',
  smap_daily: 'SMAP 逐日处理',
  gldas_download: 'GLDAS 数据下载',
  gldas_nc4_to_mat: 'GLDAS nc4→mat',
  omega_avg_daily: '平均 ω 逐日反演',
  omega_sf_fenkuai: '动态 ω 反演',
  ndvi_daily: 'NDVI 逐日产品',
  ndvi_preprocess: 'NDVI 预处理',
}

/** 节点 id → 研究员可读名（如 fy_download:nsmc → 风云数据下载 · nsmc）。未知原样返回。 */
export function humanizeNodeLabel(label: string): string {
  if (!label) return label
  const base = label.split(':')[0]!.trim().toLowerCase()
  const cn = NODE_LABELS[base]
  if (!cn) return label
  const sub = label.includes(':') ? label.slice(label.indexOf(':') + 1).trim() : ''
  return sub ? `${cn} · ${sub}` : cn
}

export function humanizeStageMessage(raw: string): string {
  if (!raw) return raw
  const s = raw.trim()

  // Stage D: 361/365 (processed=0, resumed=25, skipped=336)
  const stage =
    /^Stage\s*([A-D])\s*:\s*(\d+)\/(\d+)\s*\(processed=(\d+),\s*resumed=(\d+),\s*skipped=(\d+)\)/i.exec(
      s,
    )
  if (stage) {
    const letter = stage[1]!
    const done = stage[2]!
    const total = stage[3]!
    const processed = stage[4]!
    const resumed = stage[5]!
    const skipped = stage[6]!
    const label =
      letter === 'D'
        ? '反演回代'
        : letter === 'A'
          ? '逐日缓存'
          : letter === 'B'
            ? '气候态'
            : '参数提取'
    return `反演阶段 ${letter}（${label}）：已完成 ${done}/${total} 天（新计算 ${processed}，复用缓存 ${resumed}，跳过 ${skipped}）`
  }

  // Build FY daily job plan from I:\...
  const plan = /^Build\s+FY\s+daily\s+job\s+plan\s+from\s+\S+/i.exec(s)
  if (plan) return '生成风云逐日作业计划'

  // Artifact ready: fy_daily_tif
  const artifact = /^\[([^\]]+)\]\s*Artifact ready:\s*([\w.-]+)/i.exec(s)
  if (artifact) {
    const label = ARTIFACT_LABELS[artifact[2]!] ?? `产物 ${artifact[2]}`
    return `已生成产物：${label}`
  }

  // Downloaded 0 file(s), skipped 2: FY3D_...
  const download = /^Downloaded\s+(\d+)\s+file\(s\),\s+skipped\s+(\d+):\s*(.*)$/i.exec(s)
  if (download) {
    const n = download[1]!
    const skipped = download[2]!
    const names = download[3]!.trim()
    const tail = names ? `：${names.slice(0, 60)}${names.length > 60 ? '…' : ''}` : ''
    return `已下载 ${n} 个文件，跳过 ${skipped} 个（已存在）${tail}`
  }

  // Skipped 20260101 (mat exists)
  const skipDay = /^Skipped\s+(\d{8})\s*\((?:mat\s+)?exists\)/i.exec(s)
  if (skipDay) return `${ymdToCn(skipDay[1]!)} 已有结果，跳过`

  return s
}
