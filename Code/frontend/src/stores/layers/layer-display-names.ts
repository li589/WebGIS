/**
 * 图层显示名持久化。
 * 新写入优先 instanceId（+ 导入 backend/overlay id）；读路径仍兼容旧 catalogId 键。
 * 见 .ai/docs/specs/layer-naming.md
 */
const STORAGE_KEY = 'geo:layer-display-names:v1'

type NameMap = Record<string, string>

function loadMap(): NameMap {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return {}
    const out: NameMap = {}
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof k === 'string' && typeof v === 'string' && v.trim()) {
        out[k] = v.trim()
      }
    }
    return out
  } catch {
    return {}
  }
}

function saveMap(map: NameMap): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(map))
  } catch {
    /* ignore quota / private mode */
  }
}

export function getPersistedLayerDisplayName(key: string | null | undefined): string | null {
  if (!key) return null
  const map = loadMap()
  return map[key] ?? null
}

export function persistLayerDisplayName(key: string, name: string): void {
  const trimmed = name.trim()
  if (!key || !trimmed) return
  const map = loadMap()
  map[key] = trimmed
  saveMap(map)
}

export function clearPersistedLayerDisplayName(key: string): void {
  if (!key) return
  const map = loadMap()
  if (!(key in map)) return
  delete map[key]
  saveMap(map)
}

export function clearPersistedLayerDisplayNames(keys: Iterable<string>): void {
  const map = loadMap()
  let changed = false
  for (const key of keys) {
    if (!key || !(key in map)) continue
    delete map[key]
    changed = true
  }
  if (changed) saveMap(map)
}

/** 按多个候选 key 取第一个命中的持久化名 */
export function resolvePersistedDisplayName(
  ...keys: Array<string | null | undefined>
): string | null {
  for (const key of keys) {
    const hit = getPersistedLayerDisplayName(key)
    if (hit) return hit
  }
  return null
}
