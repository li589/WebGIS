/**
 * 反演产物「稳定编号直探」——让「添加图层」不必依赖运行记录。
 *
 * ## 解决的痛点（2026-10-15）
 * 「+ 添加」原先只走 `autoAttachProductsForNewLayer`，它内部查的是
 * `GET /workflow-runs`：该接口**按账号隔离**（非 admin 只见本人的 run），
 * 且**只认 `succeeded`**。后果是——admin 跑过的动态散射产物，游客点「添加」
 * 拿不到 → 判定"无数据" → 自动重跑工作流 → 而重跑的时间窗＝时间轴当前帧
 * （常停在无数据的日子）＋ 需要联网抓原始数据（NSMC 会话过期 / NAS 不可达）
 * ⇒ **必然失败**。盘上明明有 8 片完整产物，用户却只能看到报错。
 *
 * ## 本模块的做法
 * 产物目录 id 由后端按 `sha1("<catalogId>|<变量>|<变量>")[:12]` 生成
 * （见 backend `app/data_io/services/raster_timeseries.py:stable_imported_layer_id`），
 * **与「谁跑的、什么时候跑的、成功还是失败」全都无关**；而读图接口
 * `GET /overlay-bounds/<id>` 不按账号隔离（默认 open 放行）。
 * 因此这里直接算出编号 → 问后端「有图吗」→ 有就挂到地图上。
 *
 * 与 `default-layers.ts` 的 `attachByStableOverlayIds` 是同一套思路，区别在于：
 * 那边服务「打开网页自动挂载的默认图层（名单写死）」，这边服务「用户点击添加
 * 的任意反演目录（按 catalogId 规则推导）」，因此**不需要维护硬编码编号表**。
 *
 * ## 编号复核（2026-10-15 与磁盘目录逐条比对，全部一致）
 *   sha1('method-smap-omega-doy-dynamic|SM|SM')[:12]       = a8940443fd6d
 *   sha1('method-smap-omega-doy-dynamic|VOD|VOD')[:12]     = 5427e1020d63
 *   sha1('method-smap-omega-doy-dynamic|OMEGA|OMEGA')[:12] = 94501b455dcd
 *   sha1('method-fy-omega-doy-dynamic|SM|SM')[:12]         = fa303afda71e
 *   sha1('method-fy-omega-doy-dynamic|VOD|VOD')[:12]       = 731b37b59c97
 *   sha1('method-fy-omega-doy-dynamic|OMEGA|OMEGA')[:12]   = c6c55b8a9f4e
 *
 * ## 降级策略
 * 任何异常（非安全上下文拿不到 `crypto.subtle`、网络失败、目录不存在）都返回空数组，
 * 由调用方回退到原有「查 run / 重跑」路径 —— **失败模式是"没帮上忙"，不是"页面报错"**。
 */
import { probeOverlay, type ProbedOverlay } from './default-layers'
import { resolveInversionCatalogId } from './inversion-catalog'

/** 反演产品的三个成员角色（与 backend 落盘时的 variable_id 同名）。 */
export type InversionRole = 'SM' | 'VOD' | 'OMEGA'

const ROLES: readonly InversionRole[] = ['SM', 'VOD', 'OMEGA'] as const

/** 角色 → 侧栏显示名（与 `DEFAULT_LAYERS` 名单口径一致）。 */
export const INVERSION_ROLE_LABELS: Record<InversionRole, string> = {
  SM: '土壤水分',
  VOD: '植被光学厚度',
  OMEGA: '等效散射 ω',
}

/**
 * 可直探的目录：`method-<平台>-omega-doy-<模式>`。
 * 平台 smap / fy；模式 dynamic（分段动态） / avg（逐日平均）。
 */
const INVERTIBLE_CATALOG_PATTERN = /^method-(smap|fy)-omega-doy-(dynamic|avg)$/

const PLATFORM_LABEL: Record<string, string> = { smap: 'SMAP', fy: '风云' }
const MODE_LABEL: Record<string, string> = { dynamic: '动态', avg: '平均' }

export interface InversionGroupMeta {
  /** 归一化后的目录 id（`method-*`，用于建组 / 日志） */
  catalogId: string
  /** 侧栏「数据名称」分组标题 */
  groupTitle: string
  /** 工作流 id（仅作分组元信息，不触发任何运行） */
  workflowId?: string
}

export interface StableInversionProduct {
  role: InversionRole
  /** 稳定产物目录 id（`imported-xxxxxxxxxxxx`） */
  overlayId: string
  /** 侧栏显示名 */
  label: string
  /** 探测到的产物元信息（bounds / time_list / default_time / native_step） */
  probed: ProbedOverlay
}

/**
 * 该目录是否属于"可按稳定编号直探"的反演产品；不是则返回 null。
 *
 * 入口传进来的 id 可能是目录成员（`method-*`）、也可能是英文 workflow id
 * （`omega_sf_fenkuai_smap_online` 等）⇒ 先过一遍 `resolveInversionCatalogId` 归一化。
 */
export function resolveInversionGroupMeta(catalogId: string): InversionGroupMeta | null {
  const targetId = resolveInversionCatalogId(String(catalogId || '').trim())
  const matched = INVERTIBLE_CATALOG_PATTERN.exec(targetId)
  if (!matched) return null
  const platform = PLATFORM_LABEL[matched[1]!] ?? matched[1]!
  const mode = MODE_LABEL[matched[2]!] ?? matched[2]!
  return {
    catalogId: targetId,
    groupTitle: `${platform} ${mode}散射约束产品反演（本地）`,
  }
}

/** SHA-1 前 12 位十六进制；非安全上下文 / 无 SubtleCrypto 时返回 null。 */
async function sha1Hex12(input: string): Promise<string | null> {
  try {
    const subtle = globalThis.crypto?.subtle
    if (!subtle) return null
    const digest = await subtle.digest('SHA-1', new TextEncoder().encode(input))
    const hex = Array.from(new Uint8Array(digest), (byte) =>
      byte.toString(16).padStart(2, '0'),
    ).join('')
    return hex.slice(0, 12)
  } catch {
    return null
  }
}

/** 按后端算法推算某目录某角色的产物 id；无法计算时返回 null。 */
export async function stableInversionOverlayId(
  catalogId: string,
  role: InversionRole,
): Promise<string | null> {
  const hash = await sha1Hex12(`${catalogId}|${role}|${role}`)
  return hash ? `imported-${hash}` : null
}

/**
 * 直探某反演目录在盘上的产物（最多 3 条：SM / VOD / OMEGA）。
 *
 * 只返回**探测成功**的成员；一条都没有（或目录不在支持范围 / 算不出编号）时返回 `[]`，
 * 调用方据此回退到原有路径。
 */
export async function resolveStableInversionProducts(
  catalogId: string,
): Promise<StableInversionProduct[]> {
  const groupMeta = resolveInversionGroupMeta(catalogId)
  if (!groupMeta) return []
  const probed = await Promise.all(
    ROLES.map(async (role): Promise<StableInversionProduct | null> => {
      const overlayId = await stableInversionOverlayId(groupMeta.catalogId, role)
      if (!overlayId) return null
      const found = await probeOverlay(overlayId)
      if (!found) return null
      return { role, overlayId, label: INVERSION_ROLE_LABELS[role], probed: found }
    }),
  )
  return probed.filter((item): item is StableInversionProduct => Boolean(item))
}
