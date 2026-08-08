/**
 * 节点表单「使用系统设置」：从 effective / data-source 配置填充路径类字段。
 * 仅填充空字段或用户明确请求覆盖时写入，避免冲掉已改值。
 */
import { fetchDataSourceConfig, fetchGeneralConfig } from '../services/settings-api'

export type SystemPathDefaults = {
  dataRoot?: string
  outputRoot?: string
  cacheDir?: string
  /** 数据源配置中常见路径键的扁平快照 */
  paths: Record<string, string>
}

let cachedDefaults: SystemPathDefaults | null = null
let cacheAt = 0
const CACHE_TTL_MS = 30_000

export async function loadSystemPathDefaults(force = false): Promise<SystemPathDefaults> {
  const now = Date.now()
  if (!force && cachedDefaults && now - cacheAt < CACHE_TTL_MS) {
    return cachedDefaults
  }
  const [general, dataSource] = await Promise.all([
    fetchGeneralConfig().catch(() => null),
    fetchDataSourceConfig().catch(() => null),
  ])
  const paths: Record<string, string> = {}
  if (dataSource && typeof dataSource === 'object') {
    const walk = (obj: Record<string, unknown>, prefix = '') => {
      for (const [k, v] of Object.entries(obj)) {
        const key = prefix ? `${prefix}.${k}` : k
        if (typeof v === 'string' && /path|dir|folder|root/i.test(k) && v.trim()) {
          paths[k] = v
          paths[key] = v
        } else if (v && typeof v === 'object' && !Array.isArray(v)) {
          walk(v as Record<string, unknown>, key)
        }
      }
    }
    walk(dataSource as unknown as Record<string, unknown>)
  }
  cachedDefaults = {
    dataRoot: general?.data_root || undefined,
    outputRoot: general?.output_root || undefined,
    cacheDir: general?.cache_dir || undefined,
    paths,
  }
  cacheAt = now
  return cachedDefaults
}

/**
 * 将系统默认路径填入表单字段。
 * @param onlyEmpty 为 true 时跳过已有非空值（打开画布合并默认值）
 */
export function fillPathFieldsFromSystemSettings(
  form: Record<string, unknown>,
  defaults: SystemPathDefaults,
  fieldMap: Record<string, keyof SystemPathDefaults | string>,
  options?: { onlyEmpty?: boolean; overwrite?: boolean },
): string[] {
  const filled: string[] = []
  const onlyEmpty = options?.onlyEmpty !== false && !options?.overwrite
  for (const [formKey, sourceKey] of Object.entries(fieldMap)) {
    const current = form[formKey]
    if (onlyEmpty && current != null && String(current).trim() !== '') continue
    let value: string | undefined
    if (sourceKey === 'dataRoot') value = defaults.dataRoot
    else if (sourceKey === 'outputRoot') value = defaults.outputRoot
    else if (sourceKey === 'cacheDir') value = defaults.cacheDir
    else value = defaults.paths[String(sourceKey)]
    if (value) {
      form[formKey] = value
      filled.push(formKey)
    }
  }
  return filled
}
