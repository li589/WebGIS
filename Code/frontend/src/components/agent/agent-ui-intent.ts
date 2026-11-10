/**
 * 执行后端返回的 UI intent（地图状态仅在客户端）。
 */
import { nextTick } from 'vue'
import type { AgentUiIntent } from '../../services/agent-api'
import { useLayerWorkspace } from '../../stores/layers/selectors'
import { isDefaultLayerOverlayId } from '../../stores/layers/default-layer-ids'
import { useOnDemandFrameStore, toCompactDate } from '../../stores/layers/ondemand-frame'
import { useOverlaySymbologyStore } from '../../stores/overlay-symbology'
import { safeLog } from '../../stores/log'
import { useUiStore } from '../../stores/ui'
import {
  isMapLinkedPalette,
  resolveCanonicalPaletteIdStrict,
  WEATHER_PALETTE_OPTIONS,
} from '../map/layer-symbology'
import {
  formatLocalDateKey,
  layerDisplayName,
  readableFrameLabel,
  resolveEffectiveFrame,
} from './agent-chat-helpers'

export interface AgentUiIntentResult {
  ok: boolean
  message: string
  /** Optional structured cards for UI (list/search results) */
  cards?: Array<{ catalog_id: string; title: string }>
  /** 后端分配的命令编号，与对话里的同一条指令对应（R02 可追溯） */
  commandId?: string
}

export interface AgentUiIntentHandlers {
  fitToLayerExtent?: (instanceId: string) => boolean
  fitChina?: () => boolean
  locateCoordinate?: (lng: number, lat: number, zoom?: number) => boolean
  /** 返回 true=已切换；返回字符串=失败原因（直接展示给用户）；false=未知原因失败 */
  setBasemap?: (sourceId: string) => boolean | string
  /**
   * 图层来源中文标签（SMAP / 风云卫星…），拿不到返回空。
   *
   * 用途：报告优先4 要求日期提示写成「SMAP · 土壤水分已切到 2025-12-15」，
   * 同时让「有哪些活动图层」不出现两个无法区分的同名图层。
   */
  resolveSourceLabel?: (catalogId: string) => string | null | undefined
  /**
   * 按需补帧：给「图层 + 日期」就去 NAS 取那天的单日图（2026-11-02）。
   *
   * 为什么必须由前端注入：这条能力本来只挂在「用户拖日历」上（useOnDemandFrame），
   * 助手切日期只写页面状态，于是画面停在整段块上，而统计走的又是单日 —— 两边口径分叉。
   * 返回真实结果（applied/cached），回执才能说「真切到了那天」，而不是猜。
   */
  ensureOnDemandFrame?: (
    catalogId: string,
    date: Date,
  ) => Promise<{ ok: boolean; applied?: string; cached?: boolean; message?: string }>
}

const ACTIVE_JOB = new Set(['queued', 'running', 'retry_pending', 'accepted'])

/**
 * 单条意图的执行选项（不落进 intent 本身：它是执行上下文，不是模型给的指令）。
 */
export interface AgentUiIntentOptions {
  /**
   * 暂不报「时间轴停在/切到哪天」。
   *
   * 2026-11-09 用户复测：一条回复里同时排了「切图层 + 设日期 + 统计」，切层瞬间
   * 时间轴会先按图层记忆跳一次（SMAP 动态层的记忆日是 07-31），随后 set_timeline
   * 才切到 11-13。切层的回执如果在这时候报日期，就会把中途那张临时画面的日期
   * 留下来，最终页面停在 11-13、提示却写着 07-31。日期交给后面的 set_timeline
   * 按落定后的真实状态报。
   */
  suppressDateHint?: boolean
}

/** 等 NAS 取单日帧的上限：实测取一帧 4~6s，本地命中毫秒级；超了就如实说「正在取」 */
const ONDEMAND_AWAIT_MS = 20_000

/** 按需补帧的返回：`ok` 代表这一天的单日图真的落地了，不是「请求发出去过」。 */
export interface EnsureFrameResult {
  ok: boolean
  applied?: string
  cached?: boolean
  message?: string
  /** 这一帧的真实时间口径说明（ω 层不是当天观测时由后端给出，必须照说） */
  note?: string
}

export type OnDemandFrameProvider = (catalogId: string, date: Date) => Promise<EnsureFrameResult>

/**
 * 模块级兜底：`DashboardView` 挂载时把 `ensureFrameForLayer` 注册进来。
 *
 * 为什么不只靠 prop 链（DashboardView → AgentCompanion → AgentChatPanel → handlers）：
 * 这条链有四跳，任何一跳漏传，现象都只是「回执说该日落在时间块内」——
 * 与「这天本来就只有整段块」长得一模一样，根本分不出是没接上还是真没帧。
 * 2026-11-02 用户第二次实测就撞在这里。寄存器直连，props 只当可选覆盖。
 */
let onDemandFrameProvider: OnDemandFrameProvider | null = null

export function registerOnDemandFrameProvider(fn: OnDemandFrameProvider | null): void {
  onDemandFrameProvider = fn
}

function resolveOnDemandFrame(handlers: AgentUiIntentHandlers): OnDemandFrameProvider | null {
  return handlers.ensureOnDemandFrame ?? onDemandFrameProvider
}

/** 等一个异步结果，超时返回 null（不让回执无限期挂着） */
async function withTimeout<T>(p: Promise<T>, ms: number): Promise<T | null> {
  return await Promise.race<T | null>([
    p,
    new Promise<null>((resolve) => {
      setTimeout(() => resolve(null), ms)
    }),
  ])
}

function resolveInstanceId(
  catalogId: string | undefined,
  instanceId: string | undefined,
): { instanceId: string | null; catalogId: string | null; ambiguous?: string[] } {
  const workspace = useLayerWorkspace()
  const layers = workspace.activeLayers.value
  if (instanceId) {
    const byId = layers.find((l) => l.instanceId === instanceId)
    if (byId) return { instanceId: byId.instanceId, catalogId: byId.catalogId }
  }
  if (catalogId) {
    const byCat = layers.find((l) => l.catalogId === catalogId)
    if (byCat) return { instanceId: byCat.instanceId, catalogId: byCat.catalogId }
    // 2026-10-22：助手（大模型）常把「中文显示名」甚至「图层组名」当成 catalog_id 传过来，
    // 精确匹配必然落空，用户看到的就是「隐藏/改透明度没反应」。这里按显示名兜底：
    // 唯一命中才采纳；命中多个则回报候选，绝不猜。
    const raw = catalogId.trim()
    if (raw) {
      const hits = layers.filter((l) => {
        const name = String(l.name ?? '').trim()
        if (!name || l.isAdminBoundary) return false
        return name === raw || name.includes(raw) || raw.includes(name)
      })
      if (hits.length === 1) {
        return { instanceId: hits[0].instanceId, catalogId: hits[0].catalogId }
      }
      if (hits.length > 1) {
        return {
          instanceId: null,
          catalogId: null,
          ambiguous: hits.map((l) => String(l.name ?? l.catalogId)),
        }
      }
    }
  }
  return { instanceId: null, catalogId: catalogId ?? null }
}

/** 意图文案里的图层称呼：中文名优先，绝不把 catalog_id 甩给用户。 */
function nameOf(catalogId: string | null | undefined, explicit?: unknown): string {
  const workspace = useLayerWorkspace()
  return layerDisplayName(
    catalogId,
    workspace.activeLayers.value.map((l) => ({
      catalogId: l.catalogId,
      name: l.name,
    })),
    explicit == null ? null : String(explicit),
  )
}

/**
 * 「来源 · 图层名」的写法（报告优先4 的固定模板：SMAP · 土壤水分）。
 *
 * 拿不到来源就原样返回图层名——绝不编造，也不把内部 id 顶上去；
 * 图层名本身已含来源（如「风云卫星 土壤水分」）时不重复加前缀。
 */
function withSource(
  handlers: AgentUiIntentHandlers,
  catalogId: string | null | undefined,
  title: string,
): string {
  let source: string
  try {
    source = String(handlers.resolveSourceLabel?.(String(catalogId || '')) || '').trim()
  } catch {
    return title
  }
  if (!source || source === '未标注来源' || !title) return title
  if (title.includes(source)) return title
  return `${source} · ${title}`
}

/**
 * 图层不在面板里时的统一说法。
 *
 * 旧版一律回「未找到可定位的图层」，用户不知道是名字没对上、还是这层压根没添加。
 * 后者才是常见情况：助手只能操作「已添加」的层，用户得先去左侧图层库添加。
 */
function notOnPanelMessage(catalogId: string | undefined, action: string): string {
  const resolved = catalogId ? nameOf(catalogId) : ''
  const label = resolved && resolved !== '该图层' ? `「${resolved}」` : '这条指令指定的图层'
  return `${label}现在不在图层面板里，无法${action}。请先在左侧图层库把它添加出来，然后再说一次。`
}

/**
 * 严格布尔解析。
 *
 * 模型偶尔把布尔参数写成字符串，而 `Boolean("false") === true`——用户说
 * 「隐藏这一层」，实际执行成「显示」，还不报错，事后极难查。
 * 只认 true / "true" / "1" / 1，其余（含 "false"、缺省）一律 false。
 */
function strictBool(value: unknown): boolean {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value === 1
  const s = String(value ?? '')
    .trim()
    .toLowerCase()
  return s === 'true' || s === '1' || s === 'yes'
}

/**
 * 「同一变量」的归一化键：剥掉「来源 · 」前缀与括号备注，只留变量名本身
 * （土壤水分 / 植被光学厚度 / 等效散射 ω）。
 *
 * 2026-11-03 用户报障：他手动勾着「SMAP 平均·土壤水分」，助手下发「显示
 * SMAP 动态·土壤水分」后，两层同时亮着——上面那层把下面完全盖住，看上去
 * 跟没切换一模一样（其实切了，只是没撤旧的）。
 * 一个像素只能显示一个值，同变量两层同显没有任何观测价值 ⇒ 必须互斥。
 */
function variableKeyOf(displayName: string): string {
  return String(displayName || '')
    .replace(/^[\s\S]*?·\s*/, '') // 去掉「SMAP · 」这类来源前缀
    .replace(/（[^）]*）|\([^)]*\)/g, '') // 去掉括号里的补充说明
    .replace(/\s+/g, '')
    .trim()
}

/**
 * 图层当前生效的量程（用户覆盖值优先，其次 meta 里的原始量程）。
 *
 * 只用于回执说实话：「量程没动，还是 0 到 1.5」这种话里的数字不能编。
 * 拿不到就返回 null，调用方只说「量程没动」而不给数值。
 */
function currentRangeOf(
  catalogId: string | null | undefined,
): { vmin: number | null; vmax: number | null } | null {
  const id = String(catalogId || '').trim()
  if (!id) return null
  const workspace = useLayerWorkspace()
  const layer = workspace.activeLayers.value.find((l) => l.catalogId === id)
  let metaVmin: number | null = null
  let metaVmax: number | null = null
  try {
    const meta = useOverlaySymbologyStore().getMeta(id)
    metaVmin = typeof meta?.vmin === 'number' ? meta.vmin : null
    metaVmax = typeof meta?.vmax === 'number' ? meta.vmax : null
  } catch {
    /* store 未就绪时按「无 meta」处理，不编数字 */
  }
  const vmin = typeof layer?.vminOverride === 'number' ? layer.vminOverride : metaVmin
  const vmax = typeof layer?.vmaxOverride === 'number' ? layer.vmaxOverride : metaVmax
  if (vmin == null && vmax == null) return null
  return { vmin, vmax }
}

function formatRange(r: { vmin: number | null; vmax: number | null } | null): string {
  if (!r) return ''
  // 只有一端时不要输出「? 到 1」这种半截话 —— 回执里出现问号，用户只会更糊涂
  if (r.vmin == null && r.vmax == null) return ''
  if (r.vmin == null) return `上限 ${r.vmax}`
  if (r.vmax == null) return `下限 ${r.vmin}`
  return `${r.vmin} 到 ${r.vmax}`
}

/**
 * 收起要撤掉的图层，返回被收起的层（带来源，回执要用）。
 *
 * 两种口径：
 *   - 默认（solo=false）只动**同一变量**的其他可见层——VOD / ω 和别的产品组一律
 *     保持原样，用户可能正拿它们做对比，顺手关掉比不关更烦人。
 *   - solo=true 用户说了「只 / 仅 / 单独」，清场：除目标层外全部收起。
 *
 * 两种口径都跳过行政区边界（那是底图，关掉就没参照了）和锁在计算组里的层
 * （runGroupLocked，工作流占位，半路摘掉会把组的状态弄乱）。
 * 被跳过的层要一并返回：solo 回执若写死「省界保留」，而实际还有计算中的层
 * 亮着，那句「只显示」就是不准确的。
 */
function hideConflictingLayers(
  workspace: ReturnType<typeof useLayerWorkspace>,
  handlers: AgentUiIntentHandlers,
  target: { instanceId: string; catalogId: string; name?: string },
  solo: boolean,
): { closed: string[]; kept: string[] } {
  const targetKey = solo ? '' : variableKeyOf(nameOf(target.catalogId, target.name))
  if (!solo && !targetKey) return { closed: [], kept: [] }
  const closed: string[] = []
  const kept: string[] = []
  for (const other of workspace.activeLayers.value) {
    if (other.instanceId === target.instanceId) continue
    if (!other.visible) continue
    if (other.isAdminBoundary) continue
    const otherName = nameOf(other.catalogId, other.name)
    if (other.runGroupLocked) {
      // solo 时这些层本来要收，但计算中的层不能动 ⇒ 如实记下「保留」
      if (solo) kept.push(withSource(handlers, other.catalogId, otherName))
      continue
    }
    if (!solo && variableKeyOf(otherName) !== targetKey) continue
    workspace.toggleLayerVisibility(other.instanceId)
    closed.push(withSource(handlers, other.catalogId, otherName))
  }
  return { closed, kept }
}

/**
 * 挑一个「用来核对日期的时间序列图层」。
 *
 * 顺序（报告第二轮 A06：回执说切到 12-15、页面却停在 01-31，就是因为
 * 回执拿「帧数最多的可见图层」算，而页面按「选中/目标图层」渲染）：
 *   ① 指令里点名的目标图层 → ② 当前选中图层 → ③ 唯一可见带帧图层 → ④ 帧数最多
 * 时间轴本身不做吸附，吸附发生在渲染层，必须拿真实 time_list 才能算准。
 */
function pickDominantTimeseries(target?: {
  catalogId?: string | null
  instanceId?: string | null
}): {
  catalogId: string
  name: string
  list: string[]
} | null {
  const workspace = useLayerWorkspace()
  const layers = workspace.activeLayers.value
  const asSeries = (layer: (typeof layers)[number]) => {
    const list = layer.importedRaster?.timeList
    if (!Array.isArray(list) || !list.length) return null
    return {
      catalogId: layer.catalogId,
      name: layerDisplayName(layer.catalogId, [{ catalogId: layer.catalogId, name: layer.name }]),
      list: list.map((t) => String(t)),
    }
  }

  const wantCatalog = String(target?.catalogId ?? '').trim()
  const wantInstance = String(target?.instanceId ?? '').trim()
  if (wantCatalog || wantInstance) {
    const hit = layers.find(
      (l) =>
        (wantInstance && l.instanceId === wantInstance) ||
        (wantCatalog && l.catalogId === wantCatalog),
    )
    if (hit) {
      const series = asSeries(hit)
      if (series) return series
    }
  }

  const selectedId = String(workspace.selectedInstanceId.value ?? '').trim()
  if (selectedId) {
    const hit = layers.find((l) => l.instanceId === selectedId)
    if (hit) {
      const series = asSeries(hit)
      if (series) return series
    }
  }

  let best: ReturnType<typeof asSeries> = null
  let visibleCount = 0
  for (const layer of layers) {
    if (layer.visible === false) continue
    if (layer.isAdminBoundary) continue
    const series = asSeries(layer)
    if (!series) continue
    visibleCount += 1
    if (!best || series.list.length > best.list.length) best = series
  }
  // 只有一个可见带帧图层时直接用；多个才退化成「帧数最多」的近似
  if (best && visibleCount >= 1) return best
  return null
}

/**
 * 切层之后等时间轴落定，再把「页面真实停在哪天」读回来（2026-11-04）。
 *
 * 为什么必须等：切层改日期这段逻辑挂在 `useTimelineSync` 的 watcher 上
 * （先按 `cgda.timeline.layer-memory` 恢复记忆日期，记忆日无覆盖时再 snap 到最新切片），
 * 是「选中某个层之后才发生」的异步动作。意图函数如果立刻 return，读到的还是切换前的
 * 旧日期 —— 这正是「页面已跳到 2026-02-02、助手却回『仍停在 2025-12-15』」的根因。
 *
 * 只轮询「日期是否还在变」，不用固定 sleep：静态图层（无 time_list）约 40ms 就返回。
 */
async function waitForTimelineSettle(maxMs = 900): Promise<void> {
  const ui = useUiStore()
  // 至少放过两轮 Vue 更新：watcher 本身要跑，跑完才会改 currentDate
  await nextTick()
  await nextTick()
  const started = Date.now()
  let last = ui.currentDate.getTime()
  let steady = 0
  while (Date.now() - started < maxMs) {
    await new Promise((resolve) => setTimeout(resolve, 40))
    const now = ui.currentDate.getTime()
    if (now === last) {
      steady += 1
      if (steady >= 3) return
    } else {
      steady = 0
      last = now
    }
  }
}

/**
 * 切完层后的「日期尾巴」：页面实际停在哪个日期 / 哪一帧。
 *
 * 算不出来（该层没有时间序列、或该日无任何可用帧）就返回空串 —— 宁可不提日期，
 * 也不能再猜一个写进回执。措辞区分「日期确实变了」和「本来就停在这天」，
 * 避免把没发生的事说成刚发生。
 */
function describeSettledTimeline(catalogId: string, moved: boolean): string {
  const ui = useUiStore()
  const workspace = useLayerWorkspace()
  const day = formatLocalDateKey(ui.currentDate)
  const head = moved ? `，时间轴跟着切到 ${day}` : `，时间轴仍停在 ${day}`
  /**
   * 只认**这一层自己**的 time_list。
   * 不能借用 pickDominantTimeseries 的兜底（它会退到「帧数最多的可见图层」）：
   * 目标层的时间序列还在异步加载、尚未就绪时，那会把别的层的帧结构套进来，
   * 于是「该日落在时间块 X 内」这类补充说明会张冠李戴。拿不到就只说日期。
   */
  const layer = workspace.activeLayers.value.find((l) => l.catalogId === catalogId)
  const list = (layer?.importedRaster?.timeList ?? []).map((t) => String(t))
  if (!list.length) return head
  /**
   * ★ 2026-11-05 修（外部测试报告第 2 条的现场）：
   * 「按需补出的单日帧」**不在** `importedRaster.timeList` 里（补帧刻意不写 meta），
   * 所以下面按 time_list 判块时，明明画面已经换成 12-15 的单日图，
   * 回执仍然补一句「该日落在时间块 20251211_20251218 内」——
   * 用户看到的就是「说切了单日，又说是块」，自相矛盾。
   * 判块之前先问补帧登记表：这一层这天到底有没有单日帧。
   */
  const ondemand = useOnDemandFrameStore()
  const ondemandKey = layer?.importedRasterOverlayLayerId || catalogId
  const dayTag = ondemand.displayedDayTag(ondemandKey, toCompactDate(ui.currentDate))
  if (dayTag) return `${head}，显示的是这一天的单日图`
  const eff = resolveEffectiveFrame(list, ui.currentDate, ui.currentHour)
  if (!eff) return head
  // 时间块 key 形如 20251211_20251218：落在块内 ≠ 真切到了那一天
  if (String(eff.key ?? '').includes('_')) {
    return `${head}（该日落在时间块 ${eff.label} 内）`
  }
  if (!eff.nativeMatch && eff.label && eff.label !== day) {
    return `${head}，实际显示的是 ${eff.label}`
  }
  return head
}

function parseDateArg(raw: unknown): Date | null {
  if (raw == null) return null
  const s = String(raw).trim()
  if (!s) return null
  /**
   * 只认「年月日」三段的写法。
   *
   * 旧实现失败后会把字符串丢给 `new Date(s)`，而它对 `2025-12`、`2025` 这种
   * 残缺输入是宽松解析的：前者补成 12-01、后者补成 01-01。用户说「切到 12 月」，
   * 助手却真的切到了某一天，还不解释 —— 属于静默改日期，必须拒掉让他说清哪天。
   */
  const m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$/.exec(s)
  if (!m) return null
  {
    const y = Number(m[1])
    const mo = Number(m[2])
    const day = Number(m[3])
    const d = new Date(y, mo - 1, day)
    /**
     * 回检：JS 的 Date 会把越界值自动进位 —— `2025-02-30` 变成 3 月 1 日、
     * `2025-13-01` 变成 12 月 31 日。旧实现直接返回这个 Date，于是助手会
     * 一本正经地回「已切到 2025-03-01」，用户以为在看自己说的那天。
     * 构造后必须逐项对回去，不一致就当无效输入拒掉。
     */
    if (
      Number.isNaN(d.getTime()) ||
      d.getFullYear() !== y ||
      d.getMonth() !== mo - 1 ||
      d.getDate() !== day
    ) {
      return null
    }
    return d
  }
}

export async function executeAgentUiIntent(
  intent: AgentUiIntent,
  handlers: AgentUiIntentHandlers = {},
  options: AgentUiIntentOptions = {},
): Promise<AgentUiIntentResult> {
  const result = await executeAgentUiIntentCore(intent, handlers, options)
  const commandId = String(intent.command_id ?? '').trim()
  const enriched: AgentUiIntentResult = commandId ? { ...result, commandId } : result
  // R02：命令与其「实际执行结果」用同一个编号串起来，失败也要记
  safeLog(
    'agent-cmd',
    `${commandId || 'cmd-?'} ${intent.name} → ${enriched.ok ? '成功' : '失败'}`,
    JSON.stringify({
      target: describeIntentTarget(intent),
      message: enriched.message,
    }).slice(0, 400),
    enriched.ok ? 'info' : 'warn',
  )
  return enriched
}

/** 指令目标的可读摘要（只用于日志，不参与执行） */
function describeIntentTarget(intent: AgentUiIntent): string {
  const args = intent.args ?? {}
  const pick = (keys: string[]): string => {
    for (const k of keys) {
      const v = args[k]
      if (v != null && String(v).trim() !== '') return String(v).trim()
    }
    return ''
  }
  const hit = pick([
    'lng',
    'lon',
    'longitude',
    'latitude',
    'lat',
    'catalog_id',
    'layer_id',
    'name',
    'date',
    'time',
    'source_id',
  ])
  if (hit) return hit
  const raw = JSON.stringify(args)
  return raw && raw !== '{}' ? raw.slice(0, 80) : '-'
}

async function executeAgentUiIntentCore(
  intent: AgentUiIntent,
  handlers: AgentUiIntentHandlers = {},
  options: AgentUiIntentOptions = {},
): Promise<AgentUiIntentResult> {
  const workspace = useLayerWorkspace()
  const ui = useUiStore()
  const name = intent.name
  const args = intent.args ?? {}

  if (name === 'set_layer_visibility') {
    const catalogId = String(args.catalog_id ?? '').trim()
    const visible = strictBool(args.visible)
    if (!catalogId) return { ok: false, message: '缺少 catalog_id' }

    let resolved = resolveInstanceId(catalogId, undefined)
    if (resolved.ambiguous?.length) {
      return {
        ok: false,
        message: `「${catalogId}」匹配到多个图层（${resolved.ambiguous.join('、')}），请说得更具体一点`,
      }
    }
    if (!resolved.instanceId) {
      // 2026-10-22 修正：隐藏一个当前不在地图上的图层时，绝不能「顺手把它加上」——
      // 用户看到的是「已隐藏」，实际地图上反而多出一层。只有「显示」才允许自动添加。
      if (!visible) {
        return {
          ok: false,
          message: `当前地图上没有「${nameOf(catalogId, args.display_name)}」，无需隐藏`,
        }
      }
      const block = workspace.getCatalogAddBlockReason?.(catalogId) ?? null
      if (block) {
        return { ok: false, message: block }
      }
      workspace.addLayer(catalogId)
      resolved = resolveInstanceId(catalogId, undefined)
    }
    if (!resolved.instanceId) {
      // 不再回「无法添加「该图层」」——名字都没解析出来，说这句等于没说
      const known = nameOf(catalogId, args.display_name)
      return {
        ok: false,
        message:
          known && known !== '该图层'
            ? `没能把「${known}」加到地图上，请从左侧图层库手动添加后再试`
            : '没有在图层库里找到这一层，可能名字对不上。请从左侧图层库点选后再告诉我。',
      }
    }
    const layer = workspace.activeLayers.value.find((l) => l.instanceId === resolved.instanceId)
    if (!layer) {
      return {
        ok: false,
        message: '这一层没能在图层面板里建起来（可能刚被移除），请刷新后再试',
      }
    }
    // 记下切换前的日期：用来区分「这次真的跳了」和「本来就停在这天」
    const dateBefore = ui.currentDate.getTime()
    if (layer.visible !== visible) {
      workspace.toggleLayerVisibility(resolved.instanceId)
    }
    workspace.selectLayer(resolved.instanceId)
    workspace.setSidebarView('active')
    /**
     * ★ 2026-11-04 修：切层会触发时间轴按图层记忆跳转，而那是**异步**的
     * （useTimelineSync 的 watcher）。不等它落定就读日期，读到的是切换前的旧值，
     * 回执必然说错日期 —— 用户看到「页面已跳到 2026-02-02，助手却说仍停在 2025-12-15」。
     * 先等时间轴稳住，再用页面真实日期拼回执。
     */
    await waitForTimelineSettle()
    /**
     * ★ 2026-11-09 修（用户复测：切层 + 设日期 + 统计，提示残留中途的 7 月 31 日）：
     * 同一条回复里如果后面还排着 `set_timeline`，这次切层的日期就**不报**。
     * 切层瞬间时间轴会先按图层记忆跳一次（SMAP 动态层的记忆日是 07-31），随后
     * `set_timeline` 才把它切到用户要的 11-13；这时候报日期，等于把中途那张
     * 临时画面的日期写进回执，最终页面明明停在 11-13，提示却留着 07-31。
     * 日期由后面那条 `set_timeline` 的回执按落定后的真实状态来报。
     */
    const nowHint = options.suppressDateHint
      ? ''
      : describeSettledTimeline(catalogId, ui.currentDate.getTime() !== dateBefore)
    const label = nameOf(catalogId, args.display_name || layer.name)
    if (!visible) {
      return { ok: true, message: `已隐藏「${label}」${nowHint}` }
    }
    // 2026-11-03：显示某层时把要撤的层收掉。旧版只加不减，两个「土壤水分」叠在
    // 一起、上层遮住下层，用户会以为「切换没生效」——实际是叠加了。
    // solo（用户说了「只 / 仅 / 单独」）时清场，除目标层外全收。
    const solo = strictBool(args.solo)
    const { closed, kept } = hideConflictingLayers(
      workspace,
      handlers,
      {
        instanceId: resolved.instanceId,
        catalogId,
        name: args.display_name ? String(args.display_name) : layer.name,
      },
      solo,
    )
    const shown = withSource(handlers, catalogId, label)
    const brief = (names: string[]): string =>
      names.length <= 3
        ? names.map((n) => `「${n}」`).join('')
        : `${names
            .slice(0, 3)
            .map((n) => `「${n}」`)
            .join('')} 等 ${names.length} 个`
    if (solo) {
      if (!closed.length) {
        return {
          ok: true,
          message: `已显示「${shown}」，地图上本来就只有这一层${nowHint}`,
        }
      }
      // 被跳过的层要照实说：边界是底图性质，「只显示」仍留着它；
      // 计算中的层不能摘，也要让用户知道地图上不止一层。
      // 目标自身就是边界层时要排除，否则会出现「已只显示「省界」……省界保留」这种自我矛盾。
      const hasBoundary = workspace.activeLayers.value.some(
        (l) => l.isAdminBoundary && l.visible !== false && l.instanceId !== resolved.instanceId,
      )
      const notes: string[] = []
      if (hasBoundary) notes.push('省界保留')
      if (kept.length) notes.push(`正在计算的 ${kept.length} 层保留未动`)
      const tail = notes.length ? `，${notes.join('，')}` : ''
      return {
        ok: true,
        message: `已只显示「${shown}」，关掉了另外 ${closed.length} 层（${brief(closed)}）${tail}${nowHint}`,
      }
    }
    if (closed.length) {
      return {
        ok: true,
        message: `已显示「${shown}」，同时收起了同一变量的${brief(closed)}——地图上只留这一层${nowHint}`,
      }
    }
    return { ok: true, message: `已显示「${shown}」${nowHint}` }
  }

  if (name === 'set_layer_opacity') {
    const catalogId = String(args.catalog_id ?? '').trim()
    const raw = Number(args.opacity)
    if (!catalogId || Number.isNaN(raw)) {
      return { ok: false, message: '缺少 catalog_id 或 opacity' }
    }
    /**
     * 模型可能把「透明度调到 50%」直接传成 50。旧实现走 clamp(0,1) 静默截成 1，
     * 用户要的是半透明、结果是完全不透明，还以为自己没说清。
     * 这里按百分数折算并明确回报；超过 100 直接拒绝，不猜。
     */
    if (raw < 0 || raw > 100) {
      return {
        ok: false,
        message: `透明度 ${raw} 超出范围：请用 0~1，或用 0~100 表示百分比`,
      }
    }
    const asPercent = raw > 1
    const opacity = asPercent ? raw / 100 : raw
    const resolved = resolveInstanceId(catalogId, undefined)
    if (resolved.ambiguous?.length) {
      return {
        ok: false,
        message: `「${catalogId}」匹配到多个图层（${resolved.ambiguous.join('、')}），请说得更具体一点`,
      }
    }
    if (!resolved.instanceId) {
      const opLabel = nameOf(catalogId, args.display_name)
      return {
        ok: false,
        message:
          opLabel && opLabel !== '该图层'
            ? `「${opLabel}」还没在图层列表里`
            : '没找到你说的这一层，它可能还没添加到图层面板',
      }
    }
    const clamped = Math.max(0, Math.min(1, opacity))
    workspace.setLayerOpacity(resolved.instanceId, clamped)
    return {
      ok: true,
      message: `已把「${nameOf(catalogId, args.display_name)}」的透明度调为 ${Math.round(
        clamped * 100,
      )}%${asPercent ? '（按百分数换算）' : ''}`,
    }
  }

  if (name === 'fit_layer') {
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: notOnPanelMessage(catalogId ?? instanceIdArg, '缩放') }
    }
    const ok = handlers.fitToLayerExtent?.(resolved.instanceId) ?? false
    const fitLabel = nameOf(resolved.catalogId, args.display_name)
    return ok
      ? { ok: true, message: `已缩放到「${fitLabel}」` }
      : { ok: false, message: `「${fitLabel}」暂无可用显示范围` }
  }

  if (name === 'list_active_layers') {
    const layers = workspace.activeLayers.value.filter((l) => !l.isAdminBoundary)
    if (!layers.length) {
      // 只有边界时不能说「没有活动图层」——用户侧栏明明有东西，会觉得助手眼瞎
      const onlyBoundary = workspace.activeLayers.value.some((l) => l.isAdminBoundary)
      return {
        ok: true,
        message: onlyBoundary
          ? '当前只有行政区边界，没有数据图层。可先在左侧图层库添加图层。'
          : '当前没有活动图层。可先在左侧图层库添加图层。',
        cards: [],
      }
    }
    const cards = layers.map((l) => ({
      catalog_id: l.catalogId,
      title: (l.name || l.catalogId || '').trim() || l.catalogId,
    }))
    // 正文只列中文名 + 显示状态；catalog_id 只留在 cards 里供点击复用
    // 来源前缀用于区分同名图层（两个「土壤水分」分属 SMAP 与风云卫星）。
    const lines = layers.map((l) => {
      const title = layerDisplayName(l.catalogId, [{ catalogId: l.catalogId, name: l.name }])
      const vis = l.visible === false ? '已隐藏' : '显示中'
      return `- ${withSource(handlers, l.catalogId, title)}（${vis}）`
    })
    return {
      ok: true,
      message: `当前有 ${layers.length} 个活动图层：\n${lines.join('\n')}`,
      cards,
    }
  }

  if (name === 'fit_china' || name === 'zoom_to_china') {
    const ok = handlers.fitChina?.() ?? false
    return ok
      ? { ok: true, message: '已缩放到中国全境范围' }
      : { ok: false, message: '无法缩放到中国范围（地图未就绪）' }
  }

  if (name === 'locate_coordinate' || name === 'fly_to_location' || name === 'fly_to') {
    const rawLng = args.lng ?? args.longitude ?? args.lon
    const rawLat = args.lat ?? args.latitude
    const lng = Number(rawLng)
    const lat = Number(rawLat)
    const zoom = args.zoom != null ? Number(args.zoom) : undefined

    if (Number.isNaN(lng) || Number.isNaN(lat)) {
      return { ok: false, message: '缺少有效的经纬度坐标 (lng, lat)' }
    }
    if (lng < -180 || lng > 180 || lat < -90 || lat > 90) {
      return { ok: false, message: '经纬度超出有效范围 (lng∈[-180,180], lat∈[-90,90])' }
    }

    const ok = handlers.locateCoordinate?.(lng, lat, zoom) ?? false
    return ok
      ? { ok: true, message: `已定位到经纬度 (${lng.toFixed(4)}, ${lat.toFixed(4)})` }
      : { ok: false, message: '无法定位到指定坐标（地图未就绪）' }
  }

  if (name === 'switch_basemap' || name === 'set_basemap') {
    const sourceId = String(args.basemap_id ?? args.source_id ?? args.id ?? args.style ?? '').trim()
    if (!sourceId) {
      return { ok: false, message: '缺少底图标识 (basemap_id / source_id)' }
    }
    const result = handlers.setBasemap?.(sourceId)
    // 底图 source id 是内部标识，正文不点名，后端回复会给出中文底图名。
    // 2026-10-22：切换失败要说明原因（缺密钥 / 无此底图），不再一律回「切换失败」。
    if (result === true) return { ok: true, message: '底图已切换' }
    if (typeof result === 'string') return { ok: false, message: result }
    // 只说「切换失败」用户没法自救；也不列 source id（内部标识不进正文）
    return {
      ok: false,
      message:
        '没有切换底图：这个底图名我这边对不上。可以换个说法，比如「换成卫星影像」「换成矢量地图」「换成路网地图」',
    }
  }

  if (name === 'set_timeline') {
    const hasHour = args.hour != null && args.hour !== ''
    const hasDate = args.date != null && String(args.date).trim() !== ''
    if (!hasHour && !hasDate) {
      return { ok: false, message: '请提供 hour（0–23）和/或 date（YYYY-MM-DD）' }
    }
    let hour = ui.currentHour
    if (hasHour) {
      hour = Number(args.hour)
      if (!Number.isInteger(hour) || hour < 0 || hour > 23) {
        return { ok: false, message: 'hour 须为 0–23 的整数' }
      }
    }
    let targetDate = new Date(ui.currentDate)
    if (hasDate) {
      const d = parseDateArg(args.date)
      if (!d) return { ok: false, message: 'date 格式无效，请用 YYYY-MM-DD' }
      targetDate = d
    }

    // ★ 2026-10-28 修：写入页面状态必须推迟到「所有校验都通过之后」。
    // 旧实现在这里就先 applyDateHour/setHour 再往下判定，一旦命中
    // `!eff`（目标日没有任何时间帧）就返回 ok:false —— 但日期已经改掉了，
    // 于是界面同时出现「✗ 执行失败」和「时间轴确实变了」两种相反的信号。
    // 现在改成 commit()：只有确定能落帧（或确知没有时序图层可校验）才落盘，
    // 失败分支保持页面原状，零副作用（不写 localStorage、不触发重绘）。
    const commit = (): void => {
      if (hasDate) ui.applyDateHour(targetDate, hour)
      else ui.setHour(hour)
      /**
       * ★ 2026-11-07：落「时刻钉子」。切层常常是**新加图层**，它的 timeList 要等
       * overlay meta 回来才补到；那一刻 useTimelineSync 会按「新加图层 → 跳最新帧」
       * 把时间轴拽回该层默认帧（SMAP 动态层是 20250701_20250731，界面显示 7 月 31 日），
       * 这里刚设好的日期就被顶掉了。组合指令「切层 + 切日期 + 统计」正是这么失败的：
       * 图层与统计都对，页面却停在 7-31。
       *
       * 钉子只在保护窗内有效（见 stores/ui.ts TimelinePin），过期自动失效，
       * 不写 localStorage，不影响用户随后手动拖时间轴。
       */
      if (hasDate) {
        const pinId = String(args.catalog_id ?? args.layer_id ?? '').trim()
        if (pinId) ui.pinTimelineAt(pinId, targetDate, hour)
      }
    }

    // 时间轴只负责「选中某个时刻」，真正的帧是渲染层按切片挑的。
    // 这里提前算出会落到哪一帧，如实回报，避免「切到 12-15」实际放的是 12-03。
    // 目标是哪个图层：指令点名 → 当前选中 → 唯一可见（报告第二轮 A06）。
    const dominant = pickDominantTimeseries({
      catalogId: String(args.catalog_id ?? args.layer_id ?? '').trim() || null,
      instanceId: String(args.instance_id ?? '').trim() || null,
    })
    if (!dominant) {
      // 没有任何带时间序列的图层可校验 ⇒ 没有「会失败」的依据，照旧落下
      commit()
      return {
        ok: true,
        message: `时间轴已设为 ${formatLocalDateKey(targetDate)}（当前没有带时间序列的可见图层，无法核对该日是否有数据）`,
      }
    }
    const eff = resolveEffectiveFrame(dominant.list, targetDate, hour)
    if (!eff) {
      // 目标日确实没有可用帧 ⇒ 不写任何状态，页面保持原样
      return {
        ok: false,
        message: `${formatLocalDateKey(targetDate)} 没有可用数据：${dominant.name} 还没有任何时间帧（时间轴未改动）`,
      }
    }
    commit()
    const requested = formatLocalDateKey(targetDate)
    const span = `${readableFrameLabel(dominant.list[0])} 至 ${readableFrameLabel(
      dominant.list[dominant.list.length - 1],
    )}`
    // 报告优先4：成功提示用固定模板「来源 · 图层名已切到 YYYY-MM-DD」，
    // 有来源就写成 `SMAP · 土壤水分已切到 2025-12-15`，没来源退回「土壤水分」。
    const dominantLabel = withSource(handlers, dominant.catalogId, dominant.name)
    const shownName = dominantLabel === dominant.name ? `「${dominant.name}」` : dominantLabel
    const isBlock = String(eff.key ?? '').includes('_')
    /**
     * 2026-11-02：这里原来直接回「该日落在时间块内（无独立逐日帧）」。
     * 但用户手动拖到同一天是能出单日图的 —— 因为拖日历会走 useOnDemandFrame 去 NAS 取那一帧，
     * 而助手切日期只写页面状态。用户把「让助手切日期」理解成「替他点日历」，
     * 那两条路就必须共用同一条取帧链路，否则统计（按单日算）和画面（按整段块显示）永远对不上。
     * 所以：没有独立单日帧可落时，先按同一入口去取；取到就报单日，取不到才回落旧说法并说原因。
     */
    if (!eff.nativeMatch || isBlock) {
      const ensureFrame = resolveOnDemandFrame(handlers)
      if (ensureFrame) {
        const fetched = await withTimeout(
          ensureFrame(dominant.catalogId, targetDate),
          ONDEMAND_AWAIT_MS,
        )
        const fallback = isBlock ? `画面仍是时间块 ${eff.label}` : `实际显示的是 ${eff.label}`
        if (fetched?.ok) {
          /**
           * ω 层「按天取」拿到的不是当天观测（平均组是日序气候态、动态组是 8 天块）。
           * 后端把口径写在 `note` 里，这里必须原样带上，且**不能再说「单日图」**
           * —— 说成单日图就是口径欺骗（2026-11-05）。
           */
          const basisNote = String(fetched.note || '').trim()
          if (basisNote) {
            return {
              ok: true,
              message: `${shownName}已切到 ${requested}（${
                fetched.cached ? '本地已有' : '刚从 NAS 取回'
              }）。${basisNote}`,
            }
          }
          return {
            ok: true,
            message: `${shownName}已切到 ${requested}，显示的是这一天的单日图（${
              fetched.cached ? '本地已有' : '刚从 NAS 取回'
            }）`,
          }
        }
        if (fetched && !fetched.ok) {
          // 时间轴确实跳了，但画面没换 —— 两件事分开说，别用「已切到」把没做到的也包进去
          return {
            ok: true,
            message: `时间轴已跳到 ${requested}，但${shownName}这一天的单日图没取到：${
              fetched.message || '原因未知'
            }。${fallback}`,
          }
        }
        // 超过 20s 还没回来：别装作已经切好，说清正在取
        return {
          ok: true,
          message: `${shownName}已切到 ${requested}，正在从 NAS 取这一天的单日图（约 4~6 秒），取回后地图会换成单日`,
        }
      }
      /**
       * 没有取帧入口。以前这里会落到下面「该日落在时间块内（无独立逐日帧）」，
       * 把「功能没接上」说成「这天本来就只有块」——用户没法分辨，只能反复反馈同一件事。
       * 现在直接说清是页面没接上，并给出唯一的自救动作。
       */
      return {
        ok: false,
        message: `时间轴已跳到 ${requested}，但画面没换：这一页没接上「按天取数」入口（页面可能是旧版本），请按 Ctrl+Shift+R 强制刷新后再试。地图目前仍是 ${eff.label}`,
      }
    }
    if (eff.nativeMatch) {
      // 报告第二轮 P2：时间块 ≠ 逐日帧，回执必须说清是「落在块内」还是「真切到了那一天」。
      if (isBlock) {
        return {
          ok: true,
          message: `${shownName}已切到 ${requested}，该日落在时间块 ${eff.label} 内（无独立逐日帧）`,
        }
      }
      // 报告优先4：动作成功也要给「图层 + 具体日期」的确定说法，
      // 不能只丢一个笼统的覆盖区间（否则用户不知道到底切到哪天）。
      const frameHint = eff.label && eff.label !== requested ? `（实际命中帧 ${eff.label}）` : ''
      return {
        ok: true,
        message: `${shownName}已切到 ${requested}${frameHint}`,
      }
    }
    return {
      ok: true,
      message: `${shownName}已设为 ${requested}，但该日没有数据，实际显示的是 ${eff.label}\n（可用范围是 ${span}，已自动对齐到最近可用帧）`,
    }
  }

  if (name === 'set_timeline_playing') {
    // 与其他布尔参数统一口径：模型偶尔把 true 写成字符串 "true"，
    // 旧实现对非布尔直接报「缺少 playing: boolean」，「开始播放」这种简单指令
    // 就莫名其妙失败。但仍要保留「真没传」的判定，否则缺省会被当成暂停。
    const given = args.playing != null && String(args.playing).trim() !== ''
    if (!given) {
      return { ok: false, message: '缺少 playing（true 表示开始播放，false 表示暂停）' }
    }
    const playing = strictBool(args.playing)
    if (playing) ui.play()
    else ui.pause()
    return {
      ok: true,
      message: playing ? '已开始时间轴播放' : '已暂停时间轴播放',
    }
  }

  if (name === 'remove_layer') {
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: notOnPanelMessage(catalogId ?? instanceIdArg, '移除') }
    }
    const layer = workspace.activeLayers.value.find((l) => l.instanceId === resolved.instanceId)
    if (!layer) return { ok: false, message: '未找到可移除的图层' }
    const removeLabel = nameOf(resolved.catalogId, args.display_name || layer.name)
    const status = layer.jobLayer?.status
    if (status && ACTIVE_JOB.has(status)) {
      return {
        ok: false,
        message: `「${removeLabel}」还有进行中的任务（${status}），请先取消再移除`,
      }
    }
    // 只从面板移除，不删后端产物（与侧栏 × 行为一致）。
    // 默认四组的「移除」是否写持久化名单，已统一在 removeLayer 内部按 overlay 判定；
    // 这里只负责提示语：默认图层刷新后会自动加载回来。
    const isDefaultMember = isDefaultLayerOverlayId(layer.importedRaster?.overlayLayerId)
    workspace.removeLayer(resolved.instanceId, { deleteBackendFile: false })
    if (isDefaultMember) {
      return {
        ok: true,
        message: `已从图层面板移除「${removeLabel}」（默认图层，刷新后会随默认四组自动加载回来）`,
      }
    }
    return { ok: true, message: `已从图层面板移除「${removeLabel}」（数据文件保留）` }
  }

  if (name === 'reorder_layer') {
    const action = String(args.action ?? '')
      .trim()
      .toLowerCase()
    if (action !== 'front' && action !== 'back') {
      return { ok: false, message: 'action 须为 front 或 back' }
    }
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: notOnPanelMessage(catalogId ?? instanceIdArg, '调整层级') }
    }
    if (action === 'front') workspace.bringLayerToFront(resolved.instanceId)
    else workspace.sendLayerToBack(resolved.instanceId)
    const reorderLabel = nameOf(resolved.catalogId, args.display_name)
    return {
      ok: true,
      message:
        action === 'front'
          ? `已把「${reorderLabel}」移到最上层`
          : `已把「${reorderLabel}」移到最下层`,
    }
  }

  if (name === 'set_layer_symbology') {
    const catalogId = args.catalog_id != null ? String(args.catalog_id).trim() : undefined
    const instanceIdArg = args.instance_id != null ? String(args.instance_id).trim() : undefined
    const resolved = resolveInstanceId(catalogId, instanceIdArg)
    if (!resolved.instanceId) {
      return { ok: false, message: notOnPanelMessage(catalogId ?? instanceIdArg, '改配色') }
    }
    const display = workspace.activeLayersDisplay.value.find(
      (l) => l.instanceId === resolved.instanceId,
    )
    const layer = workspace.activeLayers.value.find((l) => l.instanceId === resolved.instanceId)
    const hasRenderHint = Boolean(display?.renderHint?.palette || display?.jobLayer)
    const supportsRecolor = Boolean(
      (layer as { supportsRecolor?: boolean } | undefined)?.supportsRecolor ||
      (display as { supportsRecolor?: boolean } | undefined)?.supportsRecolor ||
      layer?.importedRaster,
    )
    if (
      !isMapLinkedPalette({
        hasRenderHint,
        supportsRecolor,
        isImportedRaster: Boolean(layer?.importedRaster),
      })
    ) {
      return { ok: false, message: '该图层不支持前端调色板/拉伸（可能为烘焙 PNG）' }
    }
    const hasPalette = args.palette != null && String(args.palette).trim() !== ''
    const hasVmin = args.vmin != null && args.vmin !== ''
    const hasVmax = args.vmax != null && args.vmax !== ''
    if (!hasPalette && !hasVmin && !hasVmax) {
      return { ok: false, message: '请提供 palette 和/或 vmin/vmax' }
    }
    // ── 先全部校验、再落库：避免「配色改了、量程被判无效」这种半成品状态 ──
    const before = currentRangeOf(resolved.catalogId ?? catalogId)
    const patch: { vmin?: number; vmax?: number } = {}
    if (hasVmin) {
      const v = Number(args.vmin)
      if (Number.isNaN(v)) return { ok: false, message: 'vmin 无效' }
      patch.vmin = v
    }
    if (hasVmax) {
      const v = Number(args.vmax)
      if (Number.isNaN(v)) return { ok: false, message: 'vmax 无效' }
      patch.vmax = v
    }
    /**
     * 量程填反会渲染成全黑或全白，而且不会报错——用户只会觉得「图坏了」。
     * 两端都给了就互相比；只给一端就跟现有另一端比。
     */
    const badOrder =
      patch.vmin != null && patch.vmax != null
        ? patch.vmin >= patch.vmax
        : patch.vmin != null && before?.vmax != null
          ? patch.vmin >= before.vmax
          : patch.vmax != null && before?.vmin != null
            ? patch.vmax <= before.vmin
            : false
    if (badOrder) {
      const now = before ? `（当前量程 ${formatRange(before)}）` : ''
      return {
        ok: false,
        message:
          `量程不合法：最小值必须小于最大值，本次没有修改${now}。` + '请确认下限和上限各设成多少。',
      }
    }
    /**
     * 配色名可能根本不存在（模型会编 `rainbow-ultra` 这类名字）。旧实现照样落库，
     * 渲染时又被兜底成默认色带 ⇒ 回执说「已换配色」，用户却看不出任何变化。
     * 先校验，认不出来就拒掉并给出真实可选的名字。
     */
    let paletteId: string | null = null
    if (hasPalette) {
      const raw = String(args.palette).trim()
      const canon = resolveCanonicalPaletteIdStrict(raw) || raw
      const known = WEATHER_PALETTE_OPTIONS.some(
        (o) => o.id === canon || o.id === raw || resolveCanonicalPaletteIdStrict(o.id) === canon,
      )
      if (!known) {
        const names = WEATHER_PALETTE_OPTIONS.slice(0, 6)
          .map((o) => `${o.id}（${o.label}）`)
          .join('、')
        return {
          ok: false,
          message: `没有「${raw}」这个配色，这次什么都没改。可用的有：${names}。说其中一个我再换。`,
        }
      }
      paletteId = canon
    }
    if (paletteId) workspace.setLayerPaletteOverride(resolved.instanceId, paletteId)
    const changedRange = patch.vmin != null || patch.vmax != null
    if (changedRange) workspace.setLayerRangeOverride(resolved.instanceId, patch)
    const symLabel = nameOf(resolved.catalogId, args.display_name || layer?.name)
    /**
     * 回执必须分清「只换色」和「真改了量程」。
     * 旧版两种都回「已更新配色与拉伸」⇒ 用户没有任何途径判断量程被没被动，
     * 而这正是 10-20 那次（只授权换色、vmax 却被改）的核心问题。
     */
    if (!changedRange) {
      const known = formatRange(before)
      const keep = known ? `，量程没动（还是 ${known}）` : '，量程没动'
      return { ok: true, message: `已给「${symLabel}」换了配色${keep}` }
    }
    /**
     * 只描述「这次改成了什么」。旧实现拼成「从 原来的量程 改为 ? 到 1」——
     * 拿不到旧量程时会出现「原来的量程」和问号，用户读不懂到底改成了多少。
     */
    const parts: string[] = []
    if (patch.vmin != null) parts.push(`下限 ${patch.vmin}`)
    if (patch.vmax != null) parts.push(`上限 ${patch.vmax}`)
    const changedTxt = parts.join('、')
    const old = formatRange(before)
    const fromTxt = old ? `（原 ${old}）` : ''
    if (paletteId) {
      return { ok: true, message: `已给「${symLabel}」换了配色，量程改为 ${changedTxt}${fromTxt}` }
    }
    return { ok: true, message: `已把「${symLabel}」的量程改为 ${changedTxt}${fromTxt}` }
  }

  // 不把内部意图名播报给用户（他看不懂 do_something_magic 是什么）
  return {
    ok: false,
    message:
      '这个操作我这边还做不了。能帮你做的是：显示/隐藏图层、切日期、改配色、调透明度、定位与缩放、换底图、跑工作流。',
  }
}

/**
 * 逐条执行助手下发的界面意图。
 *
 * 2026-11-02 起改为 async：`set_timeline` 要真去 NAS 取那天的单日帧（约 4~6 秒），
 * 结果必须等回来才能写回执。调用方只有 AgentChatPanel（`applyChatResult` 本来即 async），
 * 用 `await` 取结果即可；其它意图内部同步，行为不变。
 */
export async function executeAgentUiIntents(
  intents: AgentUiIntent[],
  handlers: AgentUiIntentHandlers = {},
): Promise<AgentUiIntentResult[]> {
  const results: AgentUiIntentResult[] = []
  for (let i = 0; i < intents.length; i += 1) {
    const intent = intents[i]
    /**
     * 同一批里后面还排着「切日期」⇒ 这条切层的回执先别报日期（见
     * AgentUiIntentOptions.suppressDateHint 的说明）。只影响显示文案，
     * 不改任何页面状态。
     */
    const laterSetsDate = intents.slice(i + 1).some((item) => item.name === 'set_timeline')
    results.push(await executeAgentUiIntent(intent, handlers, { suppressDateHint: laterSetsDate }))
  }
  return results
}
