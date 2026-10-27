import { computed, ref, type Ref } from 'vue'
import type { ActiveLayerDisplay, ActiveRunLayerGroup } from '../../stores/layers/types'
import type { SidebarDragDeps } from './sidebar-layers-deps'
import { LAYERS_COPY } from '../../ui-copy'
import { inversionFamilyKey, runGroupMethodLabel } from '../../utils/layer-display-name'

export type ActiveTocRow =
  | {
      kind: 'group'
      groupId: string
      key: string
      collapsed: boolean
      /**
       * 组标题下的小字（2026-10-27）：`平均散射约束` / `动态散射约束`。
       * 空串＝该组不是反演产品组，不渲染这一行。
       */
      methodLabel: string
    }
  | {
      kind: 'layer'
      layer: ActiveLayerDisplay
      key: string
      indented: boolean
      /**
       * 2026-10-20：该行是否为所属组的最后一行。
       * 组头与成员在 DOM 里是平级的 `<li>`（没有包裹层），靠 CSS 边框拼接成
       * 一张卡片；加包裹层会牵连拖拽 / 折叠 / 右键三套逻辑，故改用标记位。
       */
      groupLast: boolean
    }

const EXPANDED_GROUPS_KEY = 'cgda.sidebar.expandedGroups'
/** 用户**显式折叠过**的预置组（2026-10-22） */
const COLLAPSED_DEFAULT_GROUPS_KEY = 'cgda.sidebar.collapsedDefaultGroups'

/**
 * 出厂预置组前缀：`default-layers.ts` 建的组统一叫 `run-group-default-<catalogId>`
 * （风云 / SMAP 两行就是 `run-group-default-method-fy-omega-doy-avg` 与
 * `run-group-default-method-smap-season-mean`）。
 */
const DEFAULT_GROUP_PREFIX = 'run-group-default-'

/**
 * **唯一默认展开**的预置组：风云平均散射约束（= `DEFAULT_LAYERS[0]`，
 * `default-layers.ts` 里 `catalogId: 'method-fy-omega-doy-avg'`）。
 *
 * 2026-10-27 用户定稿的四组形态（顺序见 `default-layers.ts::DEFAULT_GROUP_DISPLAY_ORDER`，
 * 由 `alignDefaultGroupOrder` 每次打开对齐）：
 *   ① 风云平均 —— 展开（一进页面看到的就是它的「土壤水分」）
 *   ② SMAP平均 —— 折叠
 *   ③ 风云动态 —— 折叠
 *   ④ SMAP动态 —— 折叠
 * 折叠的三个点开即展开，展开状态照常记忆；折叠状态也照常记忆，不会被这里重置。
 */
const PRIMARY_EXPANDED_GROUP_ID = `${DEFAULT_GROUP_PREFIX}method-fy-omega-doy-avg`

/**
 * 组展开记忆（2026-10-19）：默认折叠，只记住用户手动展开过的组。
 * 存「展开集合」而非「折叠集合」，这样从没见过的组（新跑完的工作流）天然是收起的。
 * 写入时剔除已消失的 groupId，避免 localStorage 无限增长。
 *
 * 2026-10-22（用户：要让风云与 SMAP 两个组都露出来）：**出厂预置组改为默认展开**。
 * 侧栏一进来就只看到两个组头、成员全收起，对演示是纯损失——预置组的内容是固定的，
 * 不存在「新跑完的组太多会糊屏」的问题。工作流跑出来的临时组仍保持默认收起。
 * 用户若手动折叠预置组，记到 `collapsedDefaultGroups` 里，下次刷新保持折叠。
 *
 * 2026-10-27 再改（用户：四个组只有风云平均那个不折叠）：默认图层从 2 组扩到 4 组
 * （风云平均 / 风云动态 / SMAP平均 / SMAP动态），若沿用「预置组全展开」，一进页面
 * 12 个成员铺满侧栏、四组区域互相挤压。现改为只展开 `PRIMARY_EXPANDED_GROUP_ID`。
 */
function loadStringSet(key: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return new Set()
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return new Set()
    return new Set(parsed.filter((v): v is string => typeof v === 'string'))
  } catch {
    // localStorage 不可用（隐私模式等）⇒ 退化为仅当前会话有效
    return new Set()
  }
}

function loadExpandedGroups(): Set<string> {
  return loadStringSet(EXPANDED_GROUPS_KEY)
}

function loadCollapsedDefaultGroups(): Set<string> {
  return loadStringSet(COLLAPSED_DEFAULT_GROUPS_KEY)
}

/**
 * 展开形态的**版本号**（2026-10-27 新增）。
 *
 * 为什么需要它：`isGroupExpanded` 的默认值只在「本地没有任何记录」时生效。
 * 而这两个集合会被工作区快照、跨设备同步、以及用户以前的点击长期写满——
 * 已经打开过的浏览器里，`expandedGroups` 往往记着「四个组都展开」或
 * 「风云平均被折叠过」。光改默认值对这些浏览器**完全无效**，用户看到的仍然
 * 不是「只展开第一个」。
 *
 * 做法：本版本**首次**打开时清空两份记忆、只留默认形态（＝只有风云平均展开），
 * 然后写版本号；之后用户的每一次点开/收起都照常记忆，不再被重置。
 * 以后若再改默认形态，把版本号 +1 即可让所有设备再对齐一次。
 */
const EXPANSION_SCHEMA_KEY = 'cgda.sidebar.expansionSchema'
const EXPANSION_SCHEMA_VERSION = '2'

function loadExpansionState(): { expanded: Set<string>; collapsed: Set<string> } {
  let stored: string
  try {
    stored = window.localStorage.getItem(EXPANSION_SCHEMA_KEY) ?? ''
  } catch {
    // localStorage 不可用 ⇒ 本次会话用默认形态，不报错
    return { expanded: new Set(), collapsed: new Set() }
  }
  if (stored === EXPANSION_SCHEMA_VERSION) {
    return { expanded: loadExpandedGroups(), collapsed: loadCollapsedDefaultGroups() }
  }
  // 旧版本（含「从未写过版本号」的历史浏览器）：一次性对齐为默认形态。
  // 清空即可让 isGroupExpanded 走默认分支（只有 PRIMARY_EXPANDED_GROUP_ID 展开）。
  try {
    window.localStorage.removeItem(EXPANDED_GROUPS_KEY)
    window.localStorage.removeItem(COLLAPSED_DEFAULT_GROUPS_KEY)
    window.localStorage.setItem(EXPANSION_SCHEMA_KEY, EXPANSION_SCHEMA_VERSION)
  } catch {
    // 写不进去就只影响刷新后是否再次对齐，不影响本次会话
  }
  return { expanded: new Set(), collapsed: new Set() }
}

/**
 * Extracts drag/drop reordering logic from LayerSidebar.vue.
 *
 * Manages drag state for both individual layers and run groups, computes the
 * flat TOC row list (group headers + indented members), and handles reorder
 * operations via the layers store.
 *
 * @param activeLayersDisplay - ComputedRef of the display-ordered active layers
 * @param runLayerGroups - ComputedRef of the active run layer groups
 * @param layersDeps - Narrow layers dependencies (see sidebar-layers-deps.ts)
 */
export function useSidebarDragReorder(
  activeLayersDisplay: Ref<ActiveLayerDisplay[]>,
  runLayerGroups: Ref<ActiveRunLayerGroup[]>,
  layersDeps: SidebarDragDeps,
) {
  const draggedInstanceId = ref<string | null>(null)
  const draggedGroupId = ref<string | null>(null)
  const dragOverInstanceId = ref<string | null>(null)
  const dragOverGroupId = ref<string | null>(null)

  const initialExpansion = loadExpansionState()

  /** 用户手动展开过的组（未命中的组一律按折叠渲染） */
  const expandedGroups = ref<Set<string>>(initialExpansion.expanded)
  /** 用户显式折叠过的预置组（其余预置组默认展开） */
  const collapsedDefaultGroups = ref<Set<string>>(initialExpansion.collapsed)

  function isGroupExpanded(groupId: string): boolean {
    if (expandedGroups.value.has(groupId)) return true
    if (collapsedDefaultGroups.value.has(groupId)) return false
    // 2026-10-27：**只有风云平均组**默认展开；其余三个预置组（风云动态 / SMAP平均 /
    // SMAP动态）与工作流跑出来的临时组一律默认折叠。四个组标题共占约 200px，
    // 折叠后侧栏一屏放得下、互不遮挡。
    // 注意：这条默认值只在「本地没有显式记录」时生效——用户点开过的仍然展开、
    // 折叠过的仍然折叠，不需要清 localStorage。
    return groupId === PRIMARY_EXPANDED_GROUP_ID
  }

  function toggleGroupCollapsed(groupId: string) {
    const willExpand = !isGroupExpanded(groupId)
    const next = new Set(expandedGroups.value)
    const nextCollapsed = new Set(collapsedDefaultGroups.value)
    if (willExpand) {
      next.add(groupId)
      nextCollapsed.delete(groupId)
    } else {
      next.delete(groupId)
      // 预置组「默认就是展开的」，所以折叠要单独记一笔，否则刷新又自动展开
      if (groupId.startsWith(DEFAULT_GROUP_PREFIX)) nextCollapsed.add(groupId)
    }
    expandedGroups.value = next
    collapsedDefaultGroups.value = nextCollapsed
    try {
      const alive = new Set(runLayerGroups.value.map((g) => g.groupId))
      window.localStorage.setItem(
        EXPANDED_GROUPS_KEY,
        JSON.stringify([...next].filter((id) => alive.has(id))),
      )
      window.localStorage.setItem(
        COLLAPSED_DEFAULT_GROUPS_KEY,
        JSON.stringify([...nextCollapsed].filter((id) => alive.has(id))),
      )
    } catch {
      // 写入失败不影响本次会话的展开状态
    }
  }

  /** 组头 + 缩进成员的 Active TOC 行 */
  const activeTocRows = computed<ActiveTocRow[]>(() => {
    const rows: ActiveTocRow[] = []
    const seen = new Set<string>()
    /**
     * 2026-10-20：屏蔽「组 + 同名空占位行」这类重复（纯展示层，不动 store）。
     *
     * 来源：点「添加」先建一条空壳层（名字＝目录名，徽标「排队中」），随后工作流
     * 产物回来另建一个组，组员是 `wf-run-*` 新层 ⇒ 那条空壳层成了与组并排的
     * 重复行。store 侧已有两条 prune（按 id / 按快照），但它们的判据是
     * 「源目录 id 归一化后相等」，而实际两边字符串常常对不上（一边是目录名
     * 「SMAP 动态散射约束产品」，一边是归一后的组名「SMAP卫星反演产品」），
     * 所以总会有漏网的。这里按**产品族**（平台）再兜一层，只要满足：
     *   ① 不在组内；② 没挂真实栅格；③ 族与某个已有的组相同（组里得真有数据）
     * 就不渲染。它们本来也点不开、没有色带，隐藏不丢信息。
     */
    const groupFamilies = new Set<string>()
    for (const g of runLayerGroups.value) {
      const hasRealMember = g.memberInstanceIds.some((id) => {
        const member = activeLayersDisplay.value.find((l) => l.instanceId === id)
        return Boolean(member?.importedRasterOverlayLayerId)
      })
      if (!hasRealMember) continue
      const fam = inversionFamilyKey(g.title) || inversionFamilyKey(g.sourceLayerId || '')
      if (fam) groupFamilies.add(fam)
    }
    const suppressed = new Set<string>()
    if (groupFamilies.size) {
      for (const layer of activeLayersDisplay.value) {
        if (layer.runGroupId) continue
        if (layer.isImportedRaster || layer.importedRasterOverlayLayerId) continue
        const fam = inversionFamilyKey(layer.name) || inversionFamilyKey(layer.catalogId)
        if (fam && groupFamilies.has(fam)) suppressed.add(layer.instanceId)
      }
    }
    for (const layer of activeLayersDisplay.value) {
      if (suppressed.has(layer.instanceId)) continue
      if (layer.runGroupId) {
        const collapsed = !isGroupExpanded(layer.runGroupId)
        if (!seen.has(layer.runGroupId)) {
          seen.add(layer.runGroupId)
          const group = runGroupOf(layer.runGroupId)
          rows.push({
            kind: 'group',
            groupId: layer.runGroupId,
            key: `g-${layer.runGroupId}`,
            collapsed,
            methodLabel: group ? runGroupMethodLabel(group) : '',
          })
        }
        // 折叠组的成员行不渲染；activeLayersDisplay 本身不动，拖拽落点仍按完整列表计算
        if (collapsed) continue
      }
      rows.push({
        kind: 'layer',
        layer,
        key: layer.instanceId,
        indented: Boolean(layer.runGroupId),
        groupLast: false,
      })
    }
    // 2026-10-20：标注组内最后一个成员——组块卡片的下圆角与底边框只画在它身上。
    // 判据：下一行不存在 / 是组头 / 是不缩进的独立图层。
    for (let i = 0; i < rows.length; i += 1) {
      const row = rows[i]
      if (row.kind !== 'layer' || !row.indented) continue
      const next = rows[i + 1]
      row.groupLast = !next || next.kind === 'group' || (next.kind === 'layer' && !next.indented)
    }
    return rows
  })

  function runGroupOf(groupId: string) {
    return runLayerGroups.value.find((g) => g.groupId === groupId) ?? null
  }

  function groupStatusLabel(groupId: string): string {
    const g = runGroupOf(groupId)
    if (!g) return ''
    if (g.status === 'computing') {
      if (g.message) return g.message
      return LAYERS_COPY.computingGroupBusy
    }
    // 2026-10-15 用户要求：组头不再显示「可拆分」（ready 态本身无需提示）——
    // 返回空串，模板据此不渲染状态胶囊；computing / failed / cancelled 照旧。
    if (g.status === 'ready') return ''
    if (g.status === 'failed') return '失败'
    if (g.status === 'cancelled') return '已取消'
    return g.status
  }

  function onDragStart(instanceId: string) {
    draggedInstanceId.value = instanceId
    draggedGroupId.value = null
  }

  function onGroupDragStart(groupId: string, event: DragEvent) {
    event.stopPropagation()
    draggedGroupId.value = groupId
    draggedInstanceId.value = null
  }

  function onDragOver(instanceId: string, event: DragEvent) {
    event.preventDefault()
    dragOverInstanceId.value = instanceId
    dragOverGroupId.value = null
  }

  function onGroupDragOver(groupId: string, event: DragEvent) {
    event.preventDefault()
    dragOverGroupId.value = groupId
    dragOverInstanceId.value = null
  }

  function onDrop(targetInstanceId: string) {
    if (draggedGroupId.value) {
      const group = runGroupOf(draggedGroupId.value)
      const target = activeLayersDisplay.value.find((l) => l.instanceId === targetInstanceId)
      if (group && target && target.runGroupId !== draggedGroupId.value) {
        const sorted = activeLayersDisplay.value
        const groupMembers = new Set(group.memberInstanceIds)
        const firstMember = sorted.find((l) => groupMembers.has(l.instanceId))
        const targetIdx = sorted.findIndex((l) => l.instanceId === targetInstanceId)
        const firstIdx = firstMember
          ? sorted.findIndex((l) => l.instanceId === firstMember.instanceId)
          : -1
        // 2026-10-13：「已添加图层」显示顺序为 order 升序（列表越靠上 order 越小）。
        // 落点在组块上方（索引更小）时插到锚点之前，否则插到锚点之后。
        const placeAfter = firstIdx >= 0 ? targetIdx > firstIdx : false
        layersDeps.moveRunGroupBlock(draggedGroupId.value, targetInstanceId, placeAfter)
      }
      onDragEnd()
      return
    }
    if (!draggedInstanceId.value || draggedInstanceId.value === targetInstanceId) {
      onDragEnd()
      return
    }
    const sorted = activeLayersDisplay.value
    const fromIndex = sorted.findIndex((d) => d.instanceId === draggedInstanceId.value)
    const toIndex = sorted.findIndex((d) => d.instanceId === targetInstanceId)
    if (fromIndex === -1 || toIndex === -1) {
      onDragEnd()
      return
    }
    layersDeps.reorderLayers(fromIndex, toIndex)
    onDragEnd()
  }

  function onGroupDrop(groupId: string) {
    if (draggedGroupId.value && draggedGroupId.value !== groupId) {
      const targetGroup = runGroupOf(groupId)
      const anchor = targetGroup?.memberInstanceIds[0] ?? null
      if (anchor) {
        layersDeps.moveRunGroupBlock(draggedGroupId.value, anchor, false)
      }
    }
    onDragEnd()
  }

  function onDragEnd() {
    draggedInstanceId.value = null
    draggedGroupId.value = null
    dragOverInstanceId.value = null
    dragOverGroupId.value = null
  }

  return {
    draggedInstanceId,
    draggedGroupId,
    dragOverInstanceId,
    dragOverGroupId,
    activeTocRows,
    expandedGroups,
    isGroupExpanded,
    toggleGroupCollapsed,
    runGroupOf,
    groupStatusLabel,
    onDragStart,
    onGroupDragStart,
    onDragOver,
    onGroupDragOver,
    onDrop,
    onGroupDrop,
    onDragEnd,
  }
}
