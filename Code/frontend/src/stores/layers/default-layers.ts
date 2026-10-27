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
import { useTimelineActionBannerStore } from '../timeline-action-banner'
import { forgetDismissedLayer } from './workspace-persist'
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
  /**
   * 每次打开是否把成员显隐**强制**对齐名单（缺省 true）。
   *
   * - true（风云那条）：每次打开都按名单纠正。这是 2026-10-14 用户明确要求
   *   「任何账号登录都要默认加载风云的土壤水分」——哪怕上次手动取消过，也要勾回来。
   * - false（SMAP 那条）：只在**首次挂载**时落一次初始值（全部不勾选），
   *   之后尊重用户自己的勾选，刷新不再抹掉。2026-10-21 用户口径：
   *   「不勾选任何图层，还是默认显示风云的，留着用户自己勾选」。
   */
  enforceVisibility?: boolean
  /**
   * 是否由本条目决定**时间轴落点**（缺省 true）。
   *
   * 为什么必须能关：`alignTimelineToDefaultFrame` 会对每个条目各跑一次，后跑的
   * 会把轴拽到自己的 `default_time`。风云是「整月合成」（20251201_20251231），
   * SMAP 是「逐日」（默认 20260102）——两个都落轴，最终轴落在 SMAP 那天，
   * 风云的月合成帧就再也匹配不上，表现为"风云层消失/日期对不上"。
   * ⇒ 只让风云决定轴（true），SMAP 只在用户自己勾选它的图层时由
   *   「吸附最新切片」自然接管（那时确实该跟着 SMAP 走）。
   */
  controlsTimeline?: boolean
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
 * 默认帧＝该图层的 default_time（现为整月合成 20251201_20251231，见 overlay meta）。
 *
 * 2026-10-21 变化：SMAP 三条目**恢复挂载**（老师要求侧栏多一行「SMAP卫星反演产品」），
 * 但三个成员默认全部不勾选 —— 默认画面仍是风云的土壤水分，SMAP 由用户自己勾。
 *
 * 默认显隐：风云只显示「土壤水分」（VOD / ω 不显示）；SMAP 三个都不显示。
 */
/**
 * 默认图层成员显示名（**唯一权威来源**，每次打开由 `applyDefaultNames` 对齐）。
 *
 * 2026-10-15 用户报障「换电脑后侧栏变成『土壤水分（风云 平均）』，不要有」：
 * 官方恢复路径（后端产物 title / 工作流定义 output_labels）给出的是
 * 「土壤水分 / 植被光学厚度 / 等效散射 ω」，后缀「（风云 平均）」是兜底名单里
 * 早期写死的冗余后缀；而图层名会随**工作区快照**持久化并跨设备同步 ⇒
 * 光把名单里的后缀删掉，旧设备上存下来的旧名还会一直在（用户二次报障的原因）。
 * 现做法：名单里不带后缀，且每次打开都按 `applyDefaultNames` 把成员名刷成这里的值。
 * 数据集名由分组头（`风云 平均散射约束产品反演（本地）`）表达，成员无需再带。
 *
 * 2026-10-21（老师反馈后）：新增**第二条 SMAP**。老师原话「默认这个图层再显示
 * 下面一行『SMAP卫星反演产品』，就多这一行」⇒ 侧栏在风云组下面并列出现第二组，
 * 但**三个成员一律不勾选**（`visible: false`），默认仍只显示风云的土壤水分，
 * 由用户自己按需勾选。
 *
 * ⚠ 两条的时间结构不同：风云是「整月合成」（1 帧 / native_step=1M），
 * SMAP 是「逐日」（69 帧，20251101_20251108 ~ 20260201）。
 * 因此 `controlsTimeline` 只给风云 = true —— SMAP 若也落轴，会把轴拽到
 * 20260102 导致风云的月合成帧匹配不上。
 */
export const DEFAULT_LAYERS: DefaultLayerEntry[] = [
  {
    catalogId: 'method-fy-omega-doy-avg',
    groupTitle: '风云 平均散射约束产品反演（本地）',
    workflowId: 'omega_avg_daily_fy_single',
    enforceVisibility: true,
    controlsTimeline: true,
    members: [
      {
        role: 'SM',
        overlayId: 'imported-55359b8ecd3d',
        label: '土壤水分',
        visible: true,
      },
      {
        role: 'VOD',
        overlayId: 'imported-a94205dad5f9',
        label: '植被光学厚度',
        visible: false,
      },
      {
        role: 'OMEGA',
        overlayId: 'imported-72aa577da95e',
        label: '等效散射 ω',
        visible: false,
      },
    ],
  },
  {
    /**
     * 风云**动态**散射约束（2026-10-27 用户要求：老师希望动态的也默认加载）。
     *
     * 产物早就跑出来了，只是从来没进过这份名单——编号按后端规则复算，并与
     * `Data\ProjectOutput\imports` 里的实际目录逐一核对：
     *   sha1('method-fy-omega-doy-dynamic|SM|SM')[:12]       = fa303afda71e
     *   sha1('method-fy-omega-doy-dynamic|VOD|VOD')[:12]     = 731b37b59c97
     *   sha1('method-fy-omega-doy-dynamic|OMEGA|OMEGA')[:12] = c6c55b8a9f4e
     * 时间结构：8 天块，`20251101_20251108` ~ `20251227_20251231`（8 片），
     * default_time = `20251227_20251231`。
     *
     * 三处刻意的设定：
     * - 成员**全部不勾选**：四个组盖的是同一片区域，叠在一起只看得到最上面一层；
     * - `controlsTimeline: false`：动态帧也是「包含 12-31 的区间片」，若它也落轴，
     *   会把轴从整月合成帧拽到动态块的收尾日，风云平均那层匹配范围变窄；
     * - `enforceVisibility: true`：保证"一进页面仍然是风云平均的土壤水分"这个口径
     *   在任何浏览器上都成立（否则历史快照里勾过的动态层会把平均层盖住）。
     */
    catalogId: 'method-fy-omega-doy-dynamic',
    groupTitle: '风云 动态散射约束产品反演（本地）',
    workflowId: 'omega_sf_fenkuai_fy_single',
    enforceVisibility: true,
    controlsTimeline: false,
    members: [
      {
        role: 'SM',
        overlayId: 'imported-fa303afda71e',
        label: '土壤水分',
        visible: false,
      },
      {
        role: 'VOD',
        overlayId: 'imported-731b37b59c97',
        label: '植被光学厚度',
        visible: false,
      },
      {
        role: 'OMEGA',
        overlayId: 'imported-c6c55b8a9f4e',
        label: '等效散射 ω',
        visible: false,
      },
    ],
  },
  {
    // 编号复核：sha1('method-smap-omega-doy-avg|SM|SM')[:12]       = 136c60293bbf
    //           sha1('method-smap-omega-doy-avg|VOD|VOD')[:12]     = 169f6402583c
    //           sha1('method-smap-omega-doy-avg|OMEGA|OMEGA')[:12] = 9a7cf36832cd
    // ── 2026-10-21（第二次调整）：改为指向「整段季均」图层 ──────────────────
    //
    // 为什么换编号：原先挂的是 70 片逐日/8 天块目录（`136c60293bbf` 等），
    // 里面**已经加进了** `20251203_20260201` 这一块 12 月—2 月的整段合成。
    // 但前端的切片解析（`resolveSliceForInstant`，`utils/temporal-interval.ts:307`）
    // 在同一时刻命中多个切片时**取区间最短的那一片**，为的是让卡片显示"这一天"
    // 而不是被窗口块盖住 ⇒ 12-03 到 02-01 每一天都被单日帧命中，整段合成
    // **永远选不中**（用户实测反馈「你并没有弄上啊」）。
    //
    // 所以给季均单独开目录（每层只放 1 片）：
    //   `imported-38993117b963`（SM）  `imported-bce85323670f`（VOD）
    //   `imported-49101c3674f8`（ω），编号规则同后端：
    //   sha1('method-smap-season-mean|<V>|<V>')[:12]
    // 只有一片 ⇒ 无论时间轴停在哪，解析都只能返回它 ⇒ 勾上就是整段平均图。
    catalogId: 'method-smap-season-mean',
    groupTitle: 'SMAP卫星反演产品',
    // 工作流 id 仅作分组元信息；季均目录不是某次 run 的产物（沿用原 run_id 便于追溯）
    workflowId: 'omega_avg_daily_smap_single',
    // 成员一律不勾选，且**每次打开都强制对齐**（2026-10-21 用户口径：
    // 「smap的图层组你加载进来但是不要勾选」）。原先设 false 会让历史快照里
    // 遗留的 visible=true 一直生效，表现为一进页面 SMAP 土壤水分自己亮着。
    enforceVisibility: true,
    // 不参与时间轴落点，避免覆盖风云的月合成帧（20251201_20251231）
    controlsTimeline: false,
    members: [
      {
        role: 'SM',
        overlayId: 'imported-38993117b963',
        label: '土壤水分',
        visible: false,
      },
      {
        role: 'VOD',
        overlayId: 'imported-bce85323670f',
        label: '植被光学厚度',
        visible: false,
      },
      {
        role: 'OMEGA',
        overlayId: 'imported-49101c3674f8',
        label: '等效散射 ω',
        visible: false,
      },
    ],
  },
  {
    /**
     * SMAP **动态**散射约束（2026-10-27 用户要求）。
     *
     * 编号复核（与盘上目录一致）：
     *   sha1('method-smap-omega-doy-dynamic|SM|SM')[:12]       = a8940443fd6d
     *   sha1('method-smap-omega-doy-dynamic|VOD|VOD')[:12]     = 5427e1020d63
     *   sha1('method-smap-omega-doy-dynamic|OMEGA|OMEGA')[:12] = 94501b455dcd
     * 时间结构：8 天块共 11 片（多出 `20251227_20251231` 之后的 `20260101`、
     * `20260125_20260201`、`20260202_20260208` 三个零散块），default_time =
     * `20260125_20260201`。同风云动态：不勾选、不落轴、每次打开对齐成不勾。
     */
    catalogId: 'method-smap-omega-doy-dynamic',
    groupTitle: 'SMAP 动态散射约束产品反演（本地）',
    workflowId: 'omega_sf_fenkuai_smap_single',
    enforceVisibility: true,
    controlsTimeline: false,
    members: [
      {
        role: 'SM',
        overlayId: 'imported-a8940443fd6d',
        label: '土壤水分',
        visible: false,
      },
      {
        role: 'VOD',
        overlayId: 'imported-5427e1020d63',
        label: '植被光学厚度',
        visible: false,
      },
      {
        role: 'OMEGA',
        overlayId: 'imported-94501b455dcd',
        label: '等效散射 ω',
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
 *
 * ⚠ 2026-10-21（第二次）：SMAP 的**逐日目录**三条目
 * （`136c60293bbf` / `169f6402583c` / `9a7cf36832cd`，各 70 片）退役，
 * 改用「整段季均」目录（`38993117b963` / `bce85323670f` / `49101c3674f8`）。
 * 原因是逐日目录里加进去的整段合成块被"取最短区间"规则永久屏蔽，选不中。
 * 退役只摘前端工作区，**目录与 70 片日帧全部留在盘上**，需要时可从「数据管理器」
 * 按编号加回；本数组里现在是旧编号，新编号在 `DEFAULT_LAYERS` 中，二者不重叠，
 * 不会触发「退役→挂载」互踢（那条坑见下）。
 *
 * 本机制保留（空数组时 `retireDefaultLayers` 直接 return），供以后再退役用。
 */
const RETIRED_OVERLAY_IDS: readonly string[] = [
  // 2026-10-21 退役：SMAP 逐日（70 片）——改由季均目录承载
  'imported-136c60293bbf',
  'imported-169f6402583c',
  'imported-9a7cf36832cd',
]

export interface ProbedOverlay {
  bounds?: [number, number, number, number]
  timeList?: string[]
  defaultTime?: string
  nativeStep?: string | null
}

/** 探测某 overlay 是否已注册；无产物 / 网络异常一律返回 null（不写任何负缓存）。 */
export async function probeOverlay(overlayId: string): Promise<ProbedOverlay | null> {
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

/**
 * 成员显隐**每次打开都按名单对齐一次**（2026-10-14 用户要求）。
 *
 * 历史实现用 `VISIBILITY_POLICY_VERSION` 做「只强制一次」的门控，之后尊重用户手动开关；
 * 实测后果（用户复现）：侧栏把风云三条都自动挂上了，但**土壤水分的勾选状态没被纠正**，
 * 必须手动点一下才显示。原因是版本号在 2026-10-09 那次打开就已写入 localStorage，
 * 此后 `applyVisibilityStrategy` 永不执行。
 *
 * 用户口径：「任何账号登录都要默认加载风云的土壤水分」⇒ 取消门控，每次打开都对齐。
 * 对齐范围仅限 `DEFAULT_LAYERS` 名单内的成员（按 overlayId 匹配），不会碰其它图层。
 */

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

/**
 * 按名单把成员**显示名**对齐（只对名单内的产物生效，不碰其它图层）。
 *
 * 2026-10-15 用户报障「另一台电脑侧栏仍显示『土壤水分（风云 平均）』」：
 * 图层名是**随工作区快照持久化**的（还会跨设备同步），改代码不会改写已经存下来的
 * 名字 ⇒ 旧设备（快照里存着带后缀的名字）怎么刷新都还是旧的。
 *
 * 处理方式比照 `applyVisibilityStrategy`：每次打开都把名单内成员的名字刷成权威值
 * `member.label`（数据集名已由分组头表达，成员再带后缀属冗余）。名单不在其中的
 * 图层一律不动。
 */
function applyDefaultNames(workspace: WorkspaceApi, entry: DefaultLayerEntry): void {
  const desired = new Map(entry.members.map((m) => [m.overlayId, m.label]))
  let changed = false
  for (const layer of workspace.activeLayers.value) {
    const overlayId = layer.importedRaster?.overlayLayerId
    if (!overlayId) continue
    const want = desired.get(overlayId)
    if (!want || layer.name === want) continue
    layer.name = want
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
 * 写在 `meta.json` 里的 `default_time`（现在是整月合成帧 20251201_20251231）盖掉
 * ⇒ 一进去仍显示一天。
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
  // 默认图层对齐是程序化改轴：抑制顶栏「改轴确认卡」，避免一进页面就问「要不要重跑」
  useTimelineActionBannerStore().suppressConfirm(4_000)
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
 *   4. 最后统一 `ensureDefaultGroup`（补「数据名称」分组头）+ 按名单对齐显隐（每次打开都做）。
 */
export async function ensureDefaultLayers(): Promise<void> {
  if (!DEFAULT_LAYERS_ENABLED) return
  try {
    const workspace = useLayerWorkspace()
    const workflowRun = useWorkflowRun()

    // 先卸下已退役的默认图层（如 SMAP），再挂新的默认图层
    try {
      retireDefaultLayers(workspace)
    } catch (err) {
      console.warn('[default-layers] 退役清理失败', err)
    }

    // 默认图层必须「每次打开都在」：先解除历史「移除」留下的 dismissed 登记，
    // 否则用户移除过默认层后刷新就再也不回来了（2026-10-11 用户明确要求）。
    // 只解除本名单内的编号，不影响其它图层的移除记录。
    for (const entry of DEFAULT_LAYERS) {
      for (const member of entry.members) {
        forgetDismissedLayer({ overlayLayerId: member.overlayId, catalogId: entry.catalogId })
      }
    }

    for (const entry of DEFAULT_LAYERS) {
      try {
        // 是否「本次才挂上」：决定了显隐要不要落初始值（已有图层尊重用户当前状态）
        const present = isEntryPresent(workspace.activeLayers.value, entry)
        if (!present) {
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
        // 显示名对齐（盖掉快照里遗留的旧名，如「土壤水分（风云 平均）」）
        applyDefaultNames(workspace, entry)
        // 显隐：
        // - 首次挂载 ⇒ 按名单落一次初始值。必须做，因为官方恢复路径
        //   （autoAttachProductsForNewLayer）默认把成员全勾上，SMAP 那组
        //   若不压回 list 里的 false，一进页面就三个全亮。
        // - 之后 ⇒ 只有 enforceVisibility 的条目才每次打开重新对齐
        //   （风云维持"永远只显示土壤水分"；SMAP 尊重用户自己勾的）。
        if (!present || entry.enforceVisibility !== false) {
          applyVisibilityStrategy(workspace, entry)
        }
      } catch (err) {
        console.warn('[default-layers] 跳过', entry.catalogId, err)
      }
    }

    /**
     * 时间轴落点：**所有条目挂载完之后**再统一执行，不放在上面的循环里。
     *
     * 原因（2026-10-21 加 SMAP 时踩到）：新加图层会触发 `useTimelineSync` 的
     * 「吸附最新切片」watcher，它按 instanceId 新增来判断，**不看显隐**。
     * 若边挂边落轴：风云落轴 → SMAP 三个图层接着被加进来 → 它们的 snap 后跑，
     * 把轴拽到 SMAP 的 default（20260102），风云的月合成帧再也匹配不上。
     * 连 `nextTick()` 都挡不住（watcher 是每个 tick 各自排队的）。
     * ⇒ 把落轴挪到最后统一做，且只让 `controlsTimeline` 的条目（风云）落轴。
     */
    for (const entry of DEFAULT_LAYERS) {
      if (entry.controlsTimeline === false) continue
      try {
        await nextTick()
        await alignTimelineToDefaultFrame(workspace, entry)
      } catch (err) {
        console.warn('[default-layers] 时间轴落点失败', entry.catalogId, err)
      }
    }
  } catch (err) {
    // 静默降级：默认图层失败不影响页面其它任何功能
    console.warn('[default-layers] ensureDefaultLayers failed', err)
  }
}
