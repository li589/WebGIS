<script setup lang="ts">
/**
 * BasemapMenu.vue — 顶栏「底图」下拉
 *
 * 2026-10-20：原来右侧有一排来源胶囊（高德 / Bing / Esri / OSM / 热点 / 天地…）
 * 加一个风格分段控件，两者合起来占掉大半行。现在合并成一个下拉：
 *   ┌ 来源（在上）
 *   ├ 淡灰实线
 *   └ 风格（在下）
 *
 * 「来源在上、风格在下」是用户明确要求的顺序：先决定谁出图，再决定出什么风格。
 * 选中同一来源时自动保留当前风格；该来源没有当前风格时，自动切到它有的一种。
 */
import { computed, toRef, watch } from 'vue'
import { Check, Globe, Layers, Map as MapIcon, Moon, Mountain, Satellite } from '../ui/icons'
import ToolbarMenu from './ToolbarMenu.vue'
import {
  TILE_SOURCES,
  TILE_SOURCES_BY_STYLE,
  getDefaultTileSource,
  isTileSourceUsable,
  type BasemapStyle,
  type TileSourceConfig,
  type TileSourceId,
} from '../../services/api-config'
import { basemapProviderShort, basemapStyleLabel, BASEMAP_COPY } from '../../ui-copy'
import { useSettingsStore } from '../../stores/settings'
import { useLogStore } from '../../stores/log'

const props = defineProps<{ tileSourceId: TileSourceId }>()
const emit = defineEmits<{
  changeTileSource: [sourceId: TileSourceId]
  openSettings: []
}>()

const settingsStore = useSettingsStore()
const logStore = useLogStore()
const apiKeys = toRef(settingsStore, 'apiKeys')

function sourceUsable(source: TileSourceConfig): boolean {
  void apiKeys.value
  return isTileSourceUsable(source, (key) => settingsStore.isBasemapApiKeyAvailable(key))
}

/** 来源分组键：取 sourceId 的前缀（gaode-street → gaode） */
function providerKeyOf(source: TileSourceConfig): string {
  return source.id.split('-')[0]?.toLowerCase() ?? source.id
}

const currentTileConfig = computed(() => TILE_SOURCES.find((s) => s.id === props.tileSourceId))
const activeStyle = computed<BasemapStyle>(() => currentTileConfig.value?.style ?? 'street')
const currentProviderKey = computed(() =>
  currentTileConfig.value ? providerKeyOf(currentTileConfig.value) : '',
)

const currentSourceLabel = computed(() => {
  const cfg = currentTileConfig.value
  if (!cfg) return BASEMAP_COPY.noLayers
  return `${basemapProviderShort(cfg.id, cfg.provider)} · ${basemapStyleLabel(cfg.style)}`
})

/** 来源固定展示顺序：常用的在前 */
const PROVIDER_ORDER = ['gaode', 'bing', 'esri', 'osm', 'tianditu', 'baidu', 'opentopo', 'carto']

interface ProviderRow {
  key: string
  label: string
  desc: string
  sources: TileSourceConfig[]
}

const providerRows = computed<ProviderRow[]>(() => {
  const buckets = new Map<string, TileSourceConfig[]>()
  for (const source of TILE_SOURCES) {
    // 'none' 属于「不加载底图」这个风格，不作为来源出现
    if (source.id === 'none') continue
    const key = providerKeyOf(source)
    const list = buckets.get(key)
    if (list) list.push(source)
    else buckets.set(key, [source])
  }
  const keys = [...buckets.keys()].sort((a, b) => {
    const ia = PROVIDER_ORDER.indexOf(a)
    const ib = PROVIDER_ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
  return keys.map((key) => {
    const sources = buckets.get(key) ?? []
    const first = sources[0]
    const styles = [...new Set(sources.map((s) => basemapStyleLabel(s.style)))]
    const allLocked = sources.every((s) => !sourceUsable(s))
    return {
      key,
      label: basemapProviderShort(first.id, first.provider),
      desc: `${styles.join(' · ')}${allLocked ? ' · 需配置 Key' : ''}`,
      sources,
    }
  })
})

interface StyleRow {
  style: BasemapStyle
  label: string
  desc: string
  icon: typeof MapIcon
}

const STYLE_META: Record<BasemapStyle, { icon: typeof MapIcon }> = {
  none: { icon: Globe },
  satellite: { icon: Satellite },
  street: { icon: MapIcon },
  dark: { icon: Moon },
  terrain: { icon: Mountain },
}

/** 风格顺序：常用在上，「空白（不加载底图）」放最后 */
const STYLE_ORDER: BasemapStyle[] = ['street', 'satellite', 'terrain', 'dark', 'none']

const styleRows = computed<StyleRow[]>(() => {
  const rows: StyleRow[] = []
  for (const style of STYLE_ORDER) {
    const sources = (TILE_SOURCES_BY_STYLE.get(style) ?? []).filter((s) => s.isStandard)
    if (!sources.length) continue
    const usableCount = sources.filter((s) => sourceUsable(s)).length
    rows.push({
      style,
      label: basemapStyleLabel(style),
      desc: style === 'none' ? '不加载底图瓦片' : `${usableCount} 个来源可选`,
      icon: STYLE_META[style]?.icon ?? MapIcon,
    })
  }
  return rows
})

function selectSource(source: TileSourceConfig, close: () => void) {
  if (!sourceUsable(source)) {
    logStore.logOperation(
      'basemap-locked',
      `${source.label} 需要在设置中配置并启用 ${source.secretRef?.key ?? 'API Key'}`,
    )
    close()
    emit('openSettings')
    return
  }
  close()
  if (source.id !== props.tileSourceId) emit('changeTileSource', source.id)
}

/** 选来源：优先保留当前风格，该来源没有当前风格时退到它第一个可用/第一个来源 */
function selectProvider(row: ProviderRow, close: () => void) {
  const usable = row.sources.filter((s) => sourceUsable(s))
  const sameStyle = usable.find((s) => s.style === activeStyle.value)
  const target = sameStyle ?? usable[0] ?? row.sources[0]
  if (!target) return
  selectSource(target, close)
}

/** 选风格：优先保留当前来源，该来源不支持这个风格时取第一个可用来源 */
function selectStyle(style: BasemapStyle, close: () => void) {
  const sources = (TILE_SOURCES_BY_STYLE.get(style) ?? []).filter((s) => s.isStandard)
  if (!sources.length) {
    close()
    return
  }
  const sameProvider = sources.find(
    (s) => providerKeyOf(s) === currentProviderKey.value && sourceUsable(s),
  )
  const target = sameProvider ?? sources.find((s) => sourceUsable(s)) ?? sources[0]
  selectSource(target, close)
}

// 当前来源需要 Key 但没配（例如换了账号 / 清了 Key）⇒ 回退到默认底图
watch(
  () => [props.tileSourceId, apiKeys.value] as const,
  () => {
    const cfg = currentTileConfig.value
    if (cfg && !sourceUsable(cfg)) emit('changeTileSource', getDefaultTileSource())
  },
)
</script>

<template>
  <ToolbarMenu
    label="底图"
    :icon="Layers"
    :title="`底图 · 当前：${currentSourceLabel}`"
    wide
    scrollable
  >
    <template #default="{ close }">
      <p class="tm-group-label">来源</p>
      <button
        v-for="row in providerRows"
        :key="row.key"
        class="tm-item"
        :class="{ 'is-current': currentProviderKey === row.key }"
        type="button"
        @click="selectProvider(row, close)"
      >
        <Layers :size="14" class="tm-item-icon" aria-hidden="true" />
        <span class="tm-item-body">
          <span class="tm-item-title">{{ row.label }}</span>
          <span class="tm-item-desc">{{ row.desc }}</span>
        </span>
        <Check
          v-if="currentProviderKey === row.key"
          :size="14"
          class="tm-item-check"
          aria-hidden="true"
        />
      </button>

      <div class="tm-sep" role="separator" />

      <p class="tm-group-label">风格</p>
      <button
        v-for="row in styleRows"
        :key="row.style"
        class="tm-item"
        :class="{ 'is-current': activeStyle === row.style }"
        type="button"
        @click="selectStyle(row.style, close)"
      >
        <component :is="row.icon" :size="14" class="tm-item-icon" aria-hidden="true" />
        <span class="tm-item-body">
          <span class="tm-item-title">{{ row.label }}</span>
          <span class="tm-item-desc">{{ row.desc }}</span>
        </span>
        <Check
          v-if="activeStyle === row.style"
          :size="14"
          class="tm-item-check"
          aria-hidden="true"
        />
      </button>

      <p class="tm-hint">提示：切换来源会尽量保留当前风格；没配 Key 的来源会跳到设置页</p>
    </template>
  </ToolbarMenu>
</template>
