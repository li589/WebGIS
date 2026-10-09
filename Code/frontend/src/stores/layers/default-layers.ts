/**
 * 默认图层：打开网页（任意账号 / 任意电脑）自动挂载的反演产物。
 *
 * ## 为什么不能复用「最近成功运行」那套
 * 系统原有的「打开自动找回成果」走 `GET /workflow-runs`，而该接口**按账号隔离**
 * （非 admin 只能看到自己跑过的 run，见 backend
 * `app/api/routers/workflow_router.py` 的 user 过滤）⇒ 换账号 / 换电脑就恢复不了。
 *
 * ## 本模块的做法：走「稳定 overlay 编号」
 * 产物目录 id 由后端按 `sha1("<catalogId>|<变量>|<变量>")[:12]` 生成
 * （见 backend `app/data_io/services/raster_timeseries.py:stable_imported_layer_id`），
 * 与「谁跑的、什么时候跑的」无关；且读图接口不按账号隔离（默认 `open` 权限放行）。
 * 因此这里直接算出编号 → 问后端「有图吗」→ 有就挂到地图上。
 *
 * 执行时机：打开网页、原有恢复流程跑完之后（`DashboardView.vue` 启动 IIFE 末尾）。
 * 降级策略：任何失败都静默跳过——**失败模式是「没有图层」，不是「页面卡死」**。
 *
 * ## 要新增默认图层
 * 往 `DEFAULT_LAYERS` 里加一条即可；编号可用 Python 复核：
 *   `'imported-' + hashlib.sha1(f'{catalogId}|{role}|{role}'.encode()).hexdigest()[:12]`
 */
import { nextTick } from 'vue'
import { resolveInversionCatalogId } from './inversion-catalog'
import { useLayerWorkspace, useWorkflowRun } from './selectors'
import { useUiStore } from '../ui'
import type { ActiveLayer } from './types'

/** 总开关：改为 false 并重新构建前端即可整体停用（不碰其它逻辑）。 */
export const DEFAULT_LAYERS_ENABLED = true

type VariableRole = 'SM' | 'VOD' | 'OMEGA'

interface DefaultLayerMember {
  /** 变量角色（仅供人工核对编号用） */
  role: VariableRole
  /** 后端产物目录 id（稳定编号，与 run 无关） */
  overlayId: string
  /** 侧栏显示名 */
  label: string
  /** 打开时是否默认勾选显示 */
  visible: boolean
}

interface DefaultLayerEntry {
  /** 目录图层 id（catalog-seeds 里的 method-* 成员） */
  catalogId: string
  /**
   * 侧栏「数据名称」分组标题（与风云那条同构：
   * 「风云 平均散射约束产品反演（本地）」↔「SMAP 平均散射约束产品反演（本地）」）。
   * 走官方恢复路径时会由工作流定义同名生成，这里只为**跨账号/跨设备的兜底路径**补。
   */
  groupTitle: string
  /** 对应工作流 id（仅用于分组元信息，不触发任何运行） */
  workflowId?: string
  members: DefaultLayerMember[]
}

/**
 * 默认加载名单。
 *
 * 编号复核（2026-10-09 实测，三处与磁盘目录一致）：
 *   sha1('method-fy-omega-doy-avg|SM|SM')[:12]       = 55359b8ecd3d
 *   sha1('method-fy-omega-doy-avg|VOD|VOD')[:12]     = a94205dad5f9
 *   sha1('method-fy-omega-doy-avg|OMEGA|OMEGA')[:12] = 72aa577da95e
 *
 * 2026-10-09 用户调整：默认改为**风云（FY3D）平均散射约束产品反演（本地）**，
 * 默认帧＝该图层的 default_time（十天合成 2025-12-03 ~ 12-12，见 overlay meta）；
 * 原 SMAP 三条目移入 RETIRED_OVERLAY_IDS 退役（不再自动加载）。
 *
 * 默认显隐：**只显示「土壤水分」**（VOD / ω 不显示）。
 */
export const DEFAULT_LAYERS: DefaultLayerEntry[] = [
  {
    catalogId: 'method-fy-omega-doy-avg',
    groupTitle: '风云 平均散射约束产品反演（本地）',
    workflowId: 'omega_avg_daily_fy_single',
    members: [
      {
        role: 'SM',
        overlayId: 'imported-55359b8ecd3d',
        label: '土壤水分（风云 平均）',
        visible: true,
      },
      {
        role: 'VOD',
        overlayId: 'imported-a94205dad5f9',
        label: '植被光学厚度（风云 平均）',
        visible: false,
      },
      {
        role: 'OMEGA',
        overlayId: 'imported-72aa577da95e',
        label: '等效散射 ω（风云 平均）',
        visible: false,
      },
    ],
  },
]

/**
 * 默认图层的「主成员」overlay 编号（首个 `visible: true` 的成员，退化为第一个）。
 *
 * 供启动流程把**初始视野**落到该图层的整体范围用（见 `DashboardView.vue`
 * 的 `focusDefaultLayerExtent`）——与侧栏右键「缩放到图层」是同一条路径。
 */
export function defaultPrimaryOverlayId(): string | null {
  const entry = DEFAULT_LAYERS[0]
  if (!entry) return null
  const primary = entry.members.find((member) => member.visible) ?? entry.members[0]
  return primary?.overlayId ?? null
}

/**
 * 已退役的默认图层（2026-10-09 起不再自动加载）。
 *
 * 处理方式（见 `retireDefaultLayers`）：
 * - 若工作区里还挂着这些产物（历史快照 / 跨设备同步带回），移除并登记；
 * - 只从前端工作区摘除，**不删后端数据目录**（`deleteBackendFile: false`）。
 * 想恢复 SMAP 默认加载：把 overlay 编号挪回 DEFAULT_LAYERS，并在浏览器控制台
 * 执行 `localStorage.removeItem('geo:dismissed-layers:v1')` 后强刷。
 */
const RETIRED_OVERLAY_IDS: readonly string[] = [
  'imported-136c60293bbf', // SMAP 土壤水分
  'imported-169f6402583c', // SMAP 植被光学厚度
  'imported-9a7cf36832cd', // SMAP 等效散射 ω
]

interface ProbedOverlay {
  bounds?: [number, number, number, number]
  timeList?: string[]
  defaultTime?: string
  nativeStep?: string | null
}

/** 探测某 overlay 是否已注册；无产物 / 网络异常一律返回 null（不写任何负缓存）。 */
async function probeOverlay(overlayId: string): Promise<ProbedOverlay | null> {
  try {
    const resp = await fetch(`/overlay-bounds/${encodeURIComponent(overlayId)}`)
    if (!resp.ok) return null
    const data = (await resp.json()) as { bounds?: unknown; meta?: Record<string, unknown> }
    const rawBounds = data.bounds
    const bounds =
      Array.isArray(rawBounds) &&
      rawBounds.length === 4 &&
      rawBounds.every((n) => typeof n === 'number')
        ? (rawBounds as [number, number, number, number])
        : undefined
    const meta = data.meta ?? {}
    const timeList = Array.isArray(meta.time_list)
      ? (meta.time_list as unknown[]).map((v) => String(v))
      : undefined
    return {
      bounds,
      timeList,
      defaultTime: typeof meta.default_time === 'string' ? meta.default_time : undefined,
      nativeStep: typeof meta.native_step === 'string' ? meta.native_step : null,
    }
  } catch {
    return null
  }
}

/** 该名单项是否已经存在于工作区（幂等：已加过 / 已由快照恢复 ⇒ 不再重复添加）。 */
function isEntryPresent(layers: ActiveLayer[], entry: DefaultLayerEntry): boolean {
  const memberIds = new Set(entry.members.map((m) => m.overlayId))
  return layers.some((l) => {
    if (l.catalogId === entry.catalogId) return true
    if (resolveInversionCatalogId(l.catalogId) === entry.catalogId) return true
    const overlayId = l.importedRaster?.overlayLayerId
    return overlayId ? memberIds.has(overlayId) : false
  })
}

type WorkspaceApi = ReturnType<typeof useLayerWorkspace>
type WorkflowRunApi = ReturnType<typeof useWorkflowRun>

/** 成员显隐策略只在策略版本变化时强制一次，之后尊重用户的手动开关。 */
const VISIBILITY_POLICY_KEY = 'cgda.default-layers.visibility-policy'
// 2026-10-09：默认名单由 SMAP 切换为风云，需要重新强制一次显隐（只显示土壤水分）
const VISIBILITY_POLICY_VERSION = '2026-10-09-fy-sm-visible'

function shouldForceVisibilityPolicy(): boolean {
  try {
    if (localStorage.getItem(VISIBILITY_POLICY_KEY) === VISIBILITY_POLICY_VERSION) return false
    localStorage.setItem(VISIBILITY_POLICY_KEY, VISIBILITY_POLICY_VERSION)
    return true
  } catch {
    // 隐私模式等 localStorage 不可用：退化为「每次都按名单对齐」（可接受）
    return true
  }
}

/**
 * 确保默认图层成组显示（侧栏顶部出现「数据名称」分组头）。
 *
 * 为什么需要：官方恢复路径（`autoAttachProductsForNewLayer`）按**账号**返回 run，
 * 换账号/换电脑时常拿不到 ⇒ 走稳定编号兜底挂成**三个游离层**，侧栏就只剩三个
 * 变量名、看不到它们属于哪个数据集（风云那条有 `…平均散射约束产品反演（本地）`
 * 分组头，SMAP 这条没有，观感不一致）。
 *
 * 做法：把兜底挂上的成员标记进一个 `status:'ready'` 的计算组，组名即数据集名。
 * 幂等：任一成员已在某个组里（官方路径建的）或本组已存在 ⇒ 直接跳过。
 */
function ensureDefaultGroup(
  workspace: WorkspaceApi,
  workflowRun: WorkflowRunApi,
  entry: DefaultLayerEntry,
): void {
  const memberLayers = entry.members
    .map((member) =>
      workspace.activeLayers.value.find(
        (layer) => layer.importedRaster?.overlayLayerId === member.overlayId,
      ),
    )
    .filter((layer): layer is ActiveLayer => Boolean(layer))
  if (!memberLayers.length) return
  // 官方恢复路径已经建过组（成员带 runGroupId）⇒ 不重复建
  if (memberLayers.some((layer) => Boolean(layer.runGroupId))) return

  const groupId = `run-group-default-${entry.catalogId}`
  if (workflowRun.runLayerGroups.value.some((group) => group.groupId === groupId)) return

  workflowRun.runLayerGroups.value.push({
    groupId,
    runId: '',
    title: entry.groupTitle,
    status: 'ready',
    memberInstanceIds: memberLayers.map((layer) => layer.instanceId),
    dissolvable: true,
    sourceLayerId: entry.catalogId,
    workflowId: entry.workflowId,
    message: '',
  })
  for (const layer of memberLayers) {
    const role = entry.members.find(
      (member) => member.overlayId === layer.importedRaster?.overlayLayerId,
    )?.role
    layer.runGroupId = groupId
    layer.runGroupLocked = false
    layer.runGroupProductTag = role
  }
  workspace.scheduleWorkspacePersist()
}

/** 按名单把成员显隐对齐（只对名单内的产物生效，不碰其它图层）。 */
function applyVisibilityStrategy(workspace: WorkspaceApi, entry: DefaultLayerEntry): void {
  const desired = new Map(entry.members.map((m) => [m.overlayId, m.visible]))
  let changed = false
  for (const layer of workspace.activeLayers.value) {
    const overlayId = layer.importedRaster?.overlayLayerId
    if (!overlayId) continue
    const want = desired.get(overlayId)
    if (want === undefined || layer.visible === want) continue
    layer.visible = want
    changed = true
  }
  if (changed) workspace.scheduleWorkspacePersist()
}

/** 兜底路径：按稳定编号探测后直接用产物挂载（不依赖任何 run 记录）。 */
async function attachByStableOverlayIds(
  workspace: WorkspaceApi,
  entry: DefaultLayerEntry,
): Promise<void> {
  let added = 0
  for (const member of entry.members) {
    // 二次幂等：水合可能仍在飞行中，逐成员再确认一次，避免重复挂载
    const present = workspace.activeLayers.value.some(
      (l) => l.importedRaster?.overlayLayerId === member.overlayId,
    )
    if (present) continue
    const probed = await probeOverlay(member.overlayId)
    if (!probed) continue // 该成员尚无产物：跳过
    const layer = workspace.addImportedRasterLayer(member.label, member.overlayId, probed.bounds, {
      timeList: probed.timeList,
      defaultTime: probed.defaultTime,
      nativeStep: probed.nativeStep,
    })
    if (!member.visible) layer.visible = false
    added += 1
  }
  if (added > 0) workspace.scheduleWorkspacePersist()
}

/**
 * 摘除已退役的默认图层（幂等）。
 *
 * 只对**本地导入栅格**且 overlay 编号命中名单的图层生效：
 * - `dismiss: true` ⇒ 登记到 dismissed，刷新 / 跨设备同步都不会再自动恢复；
 * - `deleteBackendFile: false` ⇒ **不删除** `Data\ProjectOutput\imports\<id>` 产物目录，
 *   随时可手动从「数据管理器」重新加回。
 */
function retireDefaultLayers(workspace: WorkspaceApi): void {
  if (!RETIRED_OVERLAY_IDS.length) return
  const retired = new Set<string>(RETIRED_OVERLAY_IDS)
  const hits = workspace.activeLayers.value.filter((layer) => {
    const overlayId = layer.importedRaster?.overlayLayerId
    return Boolean(overlayId && retired.has(overlayId))
  })
  for (const layer of hits) {
    workspace.removeLayer(layer.instanceId, { dismiss: true, deleteBackendFile: false })
  }
  if (hits.length) {
    console.warn(
      '[default-layers] 已退役 %d 个默认图层（仅从工作区移除，未删后端数据）',
      hits.length,
    )
  }
}

/**
 * 把时间轴定位到默认图层的 `default_time` 帧（「打开即显示默认帧」）。
 *
 * 为什么需要：前端约定「新加图层 → 吸附到最新切片」（`useTimelineSync` →
 * `snapTargetFromLayer` → `latestSlice`），而最新切片通常是**单日帧**，会把后端
 * 写在 `meta.json` 里的 `default_time`（这里是十天合成帧）盖掉 ⇒ 一进去仍显示一天。
 *
 * 做法：在挂载 + 吸附都跑完之后，把时间轴日期落到默认帧**内部**，让
 * `resolveSliceForInstant` 解析回该帧。区间帧取**结束日**，因为 `time_list` 按字典序
 * 排列时 `20251203_20251212` 排在 `20251212` 之前，`find` 会先命中它。
 *
 * 只对区间帧（`YYYYMMDD_YYYYMMDD`）生效：单日 `default_time` 与「最新切片」本就一致。
 */
async function alignTimelineToDefaultFrame(
  workspace: WorkspaceApi,
  entry: DefaultLayerEntry,
): Promise<void> {
  const primary = entry.members.find((member) => member.visible) ?? entry.members[0]
  if (!primary) return
  const probed = await probeOverlay(primary.overlayId)
  const defaultTime = probed?.defaultTime
  const matched = defaultTime ? /^(\d{8})_(\d{8})$/.exec(defaultTime) : null
  if (!matched) return
  const end = matched[2]!
  const date = new Date(
    Number(end.slice(0, 4)),
    Number(end.slice(4, 6)) - 1,
    Number(end.slice(6, 8)),
    0,
    0,
    0,
    0,
  )
  const uiStore = useUiStore()
  uiStore.applyDateHour(date, 0)
  uiStore.applyTimelineFromLayerGranularity('day')
  uiStore.rememberLayerTime(entry.catalogId, { force: true })
  // 反演 / 导入栅格层的 catalogId 可能被改写成 imported-<instanceId>，再按真实
  // catalogId 各记一次时刻，避免切层时命中「记忆日无覆盖 → 吸附最新切片」把默认帧顶掉。
  for (const member of entry.members) {
    const layer = workspace.activeLayers.value.find(
      (item) => item.importedRaster?.overlayLayerId === member.overlayId,
    )
    if (layer) uiStore.rememberLayerTime(layer.catalogId, { force: true })
  }
}

/**
 * 确保默认图层已挂载（幂等、静默降级）。
 *
 * 单项流程：
 *   1. 工作区已有 ⇒ 不重复挂载（但仍会补分组头 / 对齐一次显隐策略）；
 *   2. 优先走官方自动挂载 `autoAttachProductsForNewLayer`（有成功 run 时最完整：
 *      成组 + 时间轴对齐）；该接口按账号返回，非 admin 通常拿不到别人的 run；
 *   3. 上一步挂载数为 0 ⇒ 走稳定编号兜底（跨账号 / 跨设备可用）；
 *   4. 最后统一 `ensureDefaultGroup`（补「数据名称」分组头）+ 一次性显隐策略。
 */
export async function ensureDefaultLayers(): Promise<void> {
  if (!DEFAULT_LAYERS_ENABLED) return
  try {
    const workspace = useLayerWorkspace()
    const workflowRun = useWorkflowRun()
    const forceVisibility = shouldForceVisibilityPolicy()

    // 先卸下已退役的默认图层（如 SMAP），再挂新的默认图层
    try {
      retireDefaultLayers(workspace)
    } catch (err) {
      console.warn('[default-layers] 退役清理失败', err)
    }

    for (const entry of DEFAULT_LAYERS) {
      try {
        if (!isEntryPresent(workspace.activeLayers.value, entry)) {
          let attached = 0
          try {
            attached = await workflowRun.autoAttachProductsForNewLayer(entry.catalogId)
          } catch {
            attached = 0
          }
          if (attached <= 0) await attachByStableOverlayIds(workspace, entry)
        }
        // 分组头：无论图层是刚挂的还是历史快照里已有的，都要保证有数据集名
        ensureDefaultGroup(workspace, workflowRun, entry)
        if (forceVisibility) applyVisibilityStrategy(workspace, entry)
        // 等「吸附最新切片」那批 watcher 跑完，再把时间轴定位到默认帧（十天合成）
        await nextTick()
        await alignTimelineToDefaultFrame(workspace, entry)
      } catch (err) {
        console.warn('[default-layers] 跳过', entry.catalogId, err)
      }
    }
  } catch (err) {
    // 静默降级：默认图层失败不影响页面其它任何功能
    console.warn('[default-layers] ensureDefaultLayers failed', err)
  }
}
