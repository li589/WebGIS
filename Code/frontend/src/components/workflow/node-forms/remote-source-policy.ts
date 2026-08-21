/**
 * remote-source-policy.ts — 已注册远程数据源按数据集授权策略过滤（#57）。
 *
 * 过滤语义与后端运行时校验（shared/remote_sources/access_control.py 的
 * check_remote_access + build_policy_context_from_uri）对齐：
 *
 * - access_mode === 'site_compatible' → 放行（源级全放行）；
 * - access_mode === 'legacy' → 用 policy 全门户授权前缀并集判断
 *   （后端 grants 查询不过滤门户，故前端同样取全门户并集）：
 *   - 并集为空 = 无任何白名单 = 未管控 → 放行；
 *   - remote_path 与任一授权前缀有双向子树交集（前缀是 remote_path
 *     的祖先，或 remote_path 是前缀的祖先）→ 可选；
 *   - 无交集 → 过滤掉（提交期 #56 / 下载期会拒绝）。
 * - policy === null（拉取失败）→ fail-open 放行（前端仅 UX 引导，
 *   强制约束由后端兜底）。
 */

import type { RemoteDatasetPolicy, RemoteSourceEntry } from '../../../types/api-reexports'

/** 归一化路径：去首尾空白、去首尾斜杠、小写比较（大小写不敏感对齐后端 startswith 语义）。 */
function normalizePath(p: string): string {
  return p.trim().replace(/^\/+|\/+$/g, '').toLowerCase()
}

/** 判断 a 与 b 是否有双向子树交集（互为祖先或相等）。 */
function subtreeIntersects(a: string, b: string): boolean {
  if (!a || !b) return false
  return a === b || a.startsWith(`${b}/`) || b.startsWith(`${a}/`)
}

/** 汇总所有管控中（managed 且非 compatible）门户的授权前缀并集。 */
export function collectManagedPrefixes(policy: RemoteDatasetPolicy[]): string[] {
  const prefixes: string[] = []
  for (const portal of policy) {
    if (!portal.managed || portal.compatible) continue
    for (const dataset of portal.datasets ?? []) {
      for (const prefix of dataset.path_prefix ?? []) {
        const normalized = normalizePath(prefix)
        if (normalized) prefixes.push(normalized)
      }
    }
  }
  return prefixes
}

/**
 * 按数据集授权策略过滤已注册远程数据源列表。
 *
 * @param entries 已按 kind/ref_exists/enabled/protocol 预过滤的注册源列表
 * @param policy 门户级策略投影；null = 拉取失败 → fail-open 放行
 */
export function filterSourcesByDatasetPolicy(
  entries: RemoteSourceEntry[],
  policy: RemoteDatasetPolicy[] | null,
): RemoteSourceEntry[] {
  if (policy === null) return entries

  const prefixes = collectManagedPrefixes(policy)
  if (prefixes.length === 0) return entries // 无任何白名单 = 未管控 → 放行

  return entries.filter((entry) => {
    if (entry.access_mode === 'site_compatible') return true
    const remotePath = normalizePath(entry.remote_path || '')
    if (!remotePath) return true // 整源注册无路径：放行（后端按前缀逐 URI 判断）
    return prefixes.some((prefix) => subtreeIntersects(remotePath, prefix))
  })
}

/** 取某注册源可用的授权前缀提示（legacy 模式下供表单提示文案用）。 */
export function authorizedPrefixesForSource(
  entry: RemoteSourceEntry,
  policy: RemoteDatasetPolicy[] | null,
): string[] {
  if (policy === null || entry.access_mode === 'site_compatible') return []
  const prefixes = collectManagedPrefixes(policy)
  if (prefixes.length === 0) return []
  const remotePath = normalizePath(entry.remote_path || '')
  if (!remotePath) return prefixes
  return prefixes.filter((prefix) => subtreeIntersects(remotePath, prefix))
}
