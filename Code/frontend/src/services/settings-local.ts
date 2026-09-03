/**
 * Browser-local preferences for settings (not server secrets history).
 * Write API key: sessionStorage primary; localStorage only when persist opt-in.
 * Legacy local-only keys are treated as persist=true on first read (compat).
 */

import { readScopedItem, writeScopedItem } from './user-local-isolation'

const WRITE_KEY_LOCAL = 'cgda.backend_write_api_key'
const WRITE_KEY_SESSION = 'cgda.backend_write_api_key'
const WRITE_KEY_PERSIST = 'cgda.backend_write_api_key_persist'
const API_KEY_PREFS = 'cgda.api_key_prefs'
const SETTINGS_UI = 'cgda.settings_ui'

export interface ApiKeyLocalPref {
  lastRestoredHistoryId?: number | null
  collapsedHistory?: boolean
  lastLabel?: string
}

export type ApiKeyPrefsMap = Record<string, ApiKeyLocalPref>

export interface SettingsUiLocal {
  activeTab?: string
  /**
   * 地图分布淡底 / 氛围遮罩。默认开启；
   * 关闭或无可见数据图层时不盖雾/淡白层。
   */
  mapDistributionChrome?: boolean
  /** 设置侧栏宽度（px）；未设则用默认 38rem */
  panelWidthPx?: number
  /** 分析工具运行成功后是否在地图显示新图层（默认开启） */
  showAnalysisResultOnMap?: boolean
  /** 「远程与存储」二级 tab：storage（远程存储）| portals（开放门户） */
  remoteStorageTab?: string
  /** 「数据源」二级 tab：local（本地数据源）| remote（远程数据源） */
  dataSourceTab?: string
  /**
   * 实验性 3D 视图（默认关闭）。开启后顶栏切到 3D 时地图以
   * MapLibre globe 投影显示真实图层，不再显示「尚未实现」遮罩。
   */
  enable3DView?: boolean
  /**
   * 3D globe 背景模式（默认 auto）：
   * auto=跟随主题（暗色=星图 / 浅色=淡化微尘）；starfield=始终完整星图；
   * minimal=极简渐变；solar_system=相机联动太阳系深空（太阳盘+星辰）。
   */
  globeBackground?: 'auto' | 'starfield' | 'minimal' | 'solar_system'
  /**
   * 3D globe 昼夜光影档位（默认 natural）：
   * natural=真实夜半球；standard=固定明亮地球；off=关闭。
   */
  globeDaylight?: 'standard' | 'natural' | 'off'
  /**
   * 3D 渲染引擎（默认 maplibre）：
   * maplibre=现有 MapLibre globe；cesium=实验性 Cesium Viewer（天气叠加尚未接入）。
   */
  globeRenderEngine?: 'maplibre' | 'cesium'
  /**
   * Agent 伴侣挂件位置（地图舞台像素坐标 + 左右贴边态）。
   */
  agentCompanion?: {
    x: number
    y: number
    dock: 'left' | 'right' | 'none'
  }
  /** 是否在主前端显示 Agent 伴侣挂件（默认 true；仅 Web，不含小程序） */
  agentCompanionEnabled?: boolean
}

function safeGet(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key)
  } catch {
    return null
  }
}

function safeSet(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value)
  } catch {
    // private mode / quota
  }
}

function safeRemove(storage: Storage, key: string): void {
  try {
    storage.removeItem(key)
  } catch {
    // ignore
  }
}

export function isWriteApiKeyPersistEnabled(): boolean {
  return safeGet(localStorage, WRITE_KEY_PERSIST) === '1'
}

/** Opt-in: keep write key in localStorage across browser sessions (XSS surface). */
export function setWriteApiKeyPersistEnabled(on: boolean): void {
  if (on) {
    safeSet(localStorage, WRITE_KEY_PERSIST, '1')
    const current = getLocalWriteApiKey()
    if (current) safeSet(localStorage, WRITE_KEY_LOCAL, current)
    return
  }
  safeRemove(localStorage, WRITE_KEY_PERSIST)
  safeRemove(localStorage, WRITE_KEY_LOCAL)
}

/**
 * Prefer sessionStorage. Legacy localStorage keys without persist flag are
 * migrated and marked persist=true so existing operators keep the remembered key.
 */
export function getLocalWriteApiKey(): string | null {
  const fromSession = safeGet(sessionStorage, WRITE_KEY_SESSION)?.trim()
  if (fromSession) return fromSession

  const fromLocal = safeGet(localStorage, WRITE_KEY_LOCAL)?.trim()
  if (!fromLocal) return null

  safeSet(sessionStorage, WRITE_KEY_SESSION, fromLocal)
  if (!isWriteApiKeyPersistEnabled()) {
    // Backward compat: prior versions always persisted to localStorage.
    safeSet(localStorage, WRITE_KEY_PERSIST, '1')
  }
  return fromLocal
}

export function setLocalWriteApiKey(key: string | null): void {
  if (!key || !key.trim()) {
    safeRemove(localStorage, WRITE_KEY_LOCAL)
    safeRemove(sessionStorage, WRITE_KEY_SESSION)
    return
  }
  const trimmed = key.trim()
  safeSet(sessionStorage, WRITE_KEY_SESSION, trimmed)
  if (isWriteApiKeyPersistEnabled()) {
    safeSet(localStorage, WRITE_KEY_LOCAL, trimmed)
  } else {
    safeRemove(localStorage, WRITE_KEY_LOCAL)
  }
}

export function clearLocalWriteApiKey(): void {
  setLocalWriteApiKey(null)
}

export function hasLocalWriteApiKey(): boolean {
  return Boolean(getLocalWriteApiKey())
}

export function loadApiKeyPrefs(): ApiKeyPrefsMap {
  const raw = safeGet(localStorage, API_KEY_PREFS)
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw) as ApiKeyPrefsMap
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function saveApiKeyPrefs(prefs: ApiKeyPrefsMap): void {
  safeSet(localStorage, API_KEY_PREFS, JSON.stringify(prefs))
}

export function getApiKeyPref(keyName: string): ApiKeyLocalPref {
  return loadApiKeyPrefs()[keyName] ?? {}
}

export function patchApiKeyPref(keyName: string, patch: Partial<ApiKeyLocalPref>): ApiKeyLocalPref {
  const all = loadApiKeyPrefs()
  const next = { ...(all[keyName] ?? {}), ...patch }
  all[keyName] = next
  saveApiKeyPrefs(all)
  return next
}

export function loadSettingsUiLocal(): SettingsUiLocal {
  const raw = readScopedItem(SETTINGS_UI) ?? safeGet(localStorage, SETTINGS_UI)
  if (!raw) return {}
  try {
    return (JSON.parse(raw) as SettingsUiLocal) ?? {}
  } catch {
    return {}
  }
}

/** 合并写入 settings UI 偏好，避免切 Tab 等场景冲掉其它字段（如 mapDistributionChrome）。 */
export function saveSettingsUiLocal(ui: SettingsUiLocal): void {
  const merged: SettingsUiLocal = { ...loadSettingsUiLocal(), ...ui }
  writeScopedItem(SETTINGS_UI, JSON.stringify(merged))
}

/** 地图分布淡底默认开启；显式 false 时关闭。 */
export function isMapDistributionChromeEnabled(): boolean {
  return loadSettingsUiLocal().mapDistributionChrome !== false
}

const mapChromeListeners = new Set<() => void>()

export function subscribeMapDistributionChrome(listener: () => void): () => void {
  mapChromeListeners.add(listener)
  return () => {
    mapChromeListeners.delete(listener)
  }
}

export function setMapDistributionChromeEnabled(on: boolean): void {
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), mapDistributionChrome: on })
  for (const listener of mapChromeListeners) {
    try {
      listener()
    } catch {
      // ignore listener errors
    }
  }
}

/** 分析结果地图显示默认开启；显式 false 时关闭。 */
export function isShowAnalysisResultOnMapEnabled(): boolean {
  return loadSettingsUiLocal().showAnalysisResultOnMap !== false
}

export function setShowAnalysisResultOnMapEnabled(on: boolean): void {
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), showAnalysisResultOnMap: on })
}

/** 实验性 3D 视图默认关闭；显式 true 时开启。 */
export function is3DViewExperimentalEnabled(): boolean {
  return loadSettingsUiLocal().enable3DView === true
}

const d3ViewListeners = new Set<() => void>()

export function subscribe3DViewExperimental(listener: () => void): () => void {
  d3ViewListeners.add(listener)
  return () => {
    d3ViewListeners.delete(listener)
  }
}

export function set3DViewExperimentalEnabled(on: boolean): void {
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), enable3DView: on })
  for (const listener of d3ViewListeners) {
    try {
      listener()
    } catch {
      // ignore listener errors
    }
  }
}

// ─── 3D globe 场景偏好（背景星图 / 昼夜光影）──────────────────────────────

export type GlobeBackgroundMode = 'auto' | 'starfield' | 'minimal' | 'solar_system'
/** 3D晨昏样式：标准=固定明亮地球（无晨昏线）；自然=真实夜半球；无=不加亮暗。 */
export type GlobeDaylightMode = 'standard' | 'natural' | 'off'
/** 3D 渲染引擎：maplibre 默认主链；cesium 实验空壳。 */
export type GlobeRenderEngine = 'maplibre' | 'cesium'

/** 3D 背景默认 auto（跟随主题：暗色=星图 / 浅色=淡化微尘）。 */
export function getGlobeBackgroundMode(): GlobeBackgroundMode {
  const value = loadSettingsUiLocal().globeBackground
  if (value === 'starfield' || value === 'minimal' || value === 'solar_system' || value === 'auto') {
    return value
  }
  return 'auto'
}

/** 3D 昼夜光影默认 natural（真实夜半球晨昏线）。 */
export function getGlobeDaylightMode(): GlobeDaylightMode {
  const value = loadSettingsUiLocal().globeDaylight as string | undefined
  if (value === 'off') return 'off'
  if (value === 'standard') return 'standard'
  if (value === 'natural') return 'natural'
  // 未设置或 legacy auto/soft → natural
  return 'natural'
}

/** 3D 渲染引擎默认 maplibre；非法值回退。 */
export function getGlobeRenderEngine(): GlobeRenderEngine {
  const value = loadSettingsUiLocal().globeRenderEngine
  if (value === 'cesium' || value === 'maplibre') return value
  return 'maplibre'
}

const globeSceneListeners = new Set<() => void>()

/** 订阅 3D 背景 / 光影 / 渲染引擎偏好变化（返回取消订阅函数）。 */
export function subscribeGlobeScene(listener: () => void): () => void {
  globeSceneListeners.add(listener)
  return () => {
    globeSceneListeners.delete(listener)
  }
}

function notifyGlobeSceneListeners(): void {
  for (const listener of globeSceneListeners) {
    try {
      listener()
    } catch {
      // ignore listener errors
    }
  }
}

export function setGlobeBackgroundMode(mode: GlobeBackgroundMode): void {
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), globeBackground: mode })
  notifyGlobeSceneListeners()
}

export function setGlobeDaylightMode(mode: GlobeDaylightMode): void {
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), globeDaylight: mode })
  notifyGlobeSceneListeners()
}

export function setGlobeRenderEngine(engine: GlobeRenderEngine): void {
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), globeRenderEngine: engine })
  notifyGlobeSceneListeners()
}

export type AgentCompanionDock = 'left' | 'right' | 'none'

export interface AgentCompanionPosition {
  x: number
  y: number
  dock: AgentCompanionDock
}

export function getAgentCompanionPosition(): AgentCompanionPosition | null {
  const raw = loadSettingsUiLocal().agentCompanion
  if (
    raw &&
    typeof raw.x === 'number' &&
    typeof raw.y === 'number' &&
    (raw.dock === 'left' || raw.dock === 'right' || raw.dock === 'none')
  ) {
    return { x: raw.x, y: raw.y, dock: raw.dock }
  }
  return null
}

export function setAgentCompanionPosition(pos: AgentCompanionPosition): void {
  saveSettingsUiLocal({
    ...loadSettingsUiLocal(),
    agentCompanion: { x: pos.x, y: pos.y, dock: pos.dock },
  })
}

/** 主前端 Agent 伴侣默认开启；显式 false 时隐藏。 */
export function isAgentCompanionEnabled(): boolean {
  return loadSettingsUiLocal().agentCompanionEnabled !== false
}

const agentCompanionListeners = new Set<() => void>()

export function subscribeAgentCompanion(listener: () => void): () => void {
  agentCompanionListeners.add(listener)
  return () => {
    agentCompanionListeners.delete(listener)
  }
}

function notifyAgentCompanionListeners(): void {
  for (const listener of agentCompanionListeners) {
    try {
      listener()
    } catch {
      /* ignore */
    }
  }
}

export function setAgentCompanionEnabled(enabled: boolean): void {
  saveSettingsUiLocal({ ...loadSettingsUiLocal(), agentCompanionEnabled: enabled })
  notifyAgentCompanionListeners()
}

/** Clear local preferences only — does not touch server-side key history. */
export function clearAllSettingsLocalPrefs(): void {
  safeRemove(localStorage, API_KEY_PREFS)
  safeRemove(localStorage, SETTINGS_UI)
  // Keep write key unless caller also clears it
}
