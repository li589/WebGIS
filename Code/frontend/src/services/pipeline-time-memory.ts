/**
 * 流水线时间参数记忆（按用户作用域持久化）。
 *
 * 记录每条流水线（workflow_id）最近一次提交的时间范围，下次打开参数配置时
 * 预填——用户不再需要重复手选同样的时段。种子默认值仅在没有记忆时兜底
 * （PipelineLauncher.handleLaunchClick 的既有逻辑）。
 *
 * 注意：记忆在「点击确认提交」时写入（此时 run 尚未完成，前端无成功回调），
 * 故语义是「最近一次提交」，而非「最近一次运行成功」。
 *
 * 存储：`geo:pipeline-last-time-range:v1` →
 *   Record<workflowId, { start_date: string; end_date: string; savedAt: string }>
 * （start/end 均为 YYYYMMDD 定长字符串，与提交参数一致。）
 */
import { readScopedItem, writeScopedItem } from '../services/user-local-isolation'

const STORAGE_KEY = 'geo:pipeline-last-time-range:v1'
const MAX_ENTRIES = 100

export interface PipelineLastTimeRange {
  start_date: string
  end_date: string
  savedAt: string
}

function readAll(): Record<string, PipelineLastTimeRange> {
  try {
    const raw = readScopedItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, PipelineLastTimeRange>
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeAll(map: Record<string, PipelineLastTimeRange>): void {
  // 容量上限：超出时淘汰最旧的 savedAt，防止长期膨胀
  const entries = Object.entries(map)
  if (entries.length > MAX_ENTRIES) {
    entries.sort((a, b) => (a[1].savedAt || '').localeCompare(b[1].savedAt || ''))
    for (const [key] of entries.slice(0, entries.length - MAX_ENTRIES)) {
      delete map[key]
    }
  }
  writeScopedItem(STORAGE_KEY, JSON.stringify(map))
}

/** 读取某条流水线最近一次提交的时间范围；无记忆返回 undefined。 */
export function getPipelineLastTimeRange(workflowId: string): PipelineLastTimeRange | undefined {
  if (!workflowId) return undefined
  return readAll()[workflowId]
}

/** 记录某条流水线最近一次成功提交的时间范围（YYYYMMDD 对）。 */
export function setPipelineLastTimeRange(
  workflowId: string,
  startDate: string,
  endDate: string,
): void {
  if (!workflowId || !startDate || !endDate) return
  const map = readAll()
  map[workflowId] = {
    start_date: startDate,
    end_date: endDate,
    savedAt: new Date().toISOString(),
  }
  writeAll(map)
}
