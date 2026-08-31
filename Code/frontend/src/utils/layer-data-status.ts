/**
 * 图层条目统一数据状态徽标（2026-08-25 UX 简化，用户报障「状态串冗余」）。
 *
 * 此前每条图层下方堆叠 3 枚状态徽标（availability「数据异常/完整数据」+
 * lifecycle「资产陈旧/更新中」+ job「失败/运行中」），术语混杂（"资产"
 * 对地理研究者无意义）。现归并为**单枚**数据状态徽标：
 *
 *   运行中 | 排队中 | 异常 | 完成 | 旧数据
 *
 * 「旧数据」语义：非系统错误导致的新数据无法加载（数据未发布/未更新，
 * 图层仍在用旧版数据）；静态数据层不显示「旧数据」（静态数据无新旧概念）。
 */

export type DataStatusState = 'running' | 'queued' | 'error' | 'done' | 'stale'

export interface DataStatusBadge {
  /** 统一五态（决定配色与文案） */
  state: DataStatusState
  /** 展示文案（含进度百分比等动态内容） */
  label: string
  /** 悬停提示（保留原 availability/lifecycle/job 的细节诊断） */
  title?: string
}

export interface DataStatusInput {
  /** 工作流作业状态（running/queued/retry_pending/succeeded/failed/cancelled） */
  jobStatus?: string | null
  /** 作业进度 0-100（running 态展示） */
  jobProgress?: number | null
  /** availability state（ready/partial/empty） */
  availabilityState?: string | null
  /** availability label（完整数据/运行中/排队中/数据异常/等待结果/待运行…） */
  availabilityLabel?: string | null
  /** availability description（悬停诊断） */
  availabilityDescription?: string | null
  /** 资产生命周期（fresh/stale/updating/missing/failed；null=无 lifecycle） */
  lifecycleState?: string | null
  /** lifecycle 诊断消息 */
  lifecycleMessage?: string | null
  /** 静态数据层（不显示「旧数据」） */
  isStaticLayer?: boolean
}

const STALE_TITLE = '数据可用但非最新：新数据尚未发布或未更新，非系统故障'

/**
 * 归并三源状态（job > lifecycle > availability）为单枚数据状态徽标。
 *
 * 优先级（高→低）：
 * 1. 作业运行/排队/失败/取消 → 运行中/排队中/异常/异常
 * 2. lifecycle updating/failed/missing → 运行中/异常/异常
 * 3. lifecycle stale 且非静态层 → 旧数据
 * 4. availability：partial(运行中/排队中类)→运行中/排队中；
 *    empty(异常类)→异常；ready→完成
 * 5. lifecycle fresh → 完成
 * 6. 无任何信号 → null（不渲染徽标）
 */
export function deriveDataStatus(input: DataStatusInput): DataStatusBadge | null {
  const {
    jobStatus,
    jobProgress,
    availabilityState,
    availabilityLabel,
    availabilityDescription,
    lifecycleState,
    lifecycleMessage,
    isStaticLayer,
  } = input

  // 1. 作业状态最具体，优先
  if (jobStatus === 'running') {
    const pct =
      typeof jobProgress === 'number' && jobProgress > 0
        ? ` ${Math.round(jobProgress)}%`
        : ''
    return { state: 'running', label: `运行中${pct}`, title: availabilityDescription ?? undefined }
  }
  if (jobStatus === 'queued' || jobStatus === 'retry_pending') {
    return { state: 'queued', label: '排队中', title: availabilityDescription ?? undefined }
  }
  if (jobStatus === 'failed') {
    return { state: 'error', label: '异常', title: availabilityDescription ?? undefined }
  }
  if (jobStatus === 'cancelled') {
    return {
      state: 'error',
      label: '异常',
      title: `运行已取消：${availabilityDescription ?? '数据未生成'}`,
    }
  }

  // 2. 资产生命周期（作业未运行时的后台更新状态）
  if (lifecycleState === 'updating') {
    return { state: 'running', label: '运行中', title: lifecycleMessage ?? undefined }
  }
  if (lifecycleState === 'failed' || lifecycleState === 'missing') {
    return {
      state: 'error',
      label: '异常',
      title: lifecycleMessage ?? '数据加载失败',
    }
  }

  // 3. 旧数据（静态层豁免：静态数据无新旧概念）
  if (lifecycleState === 'stale' && !isStaticLayer) {
    return { state: 'stale', label: '旧数据', title: lifecycleMessage ?? STALE_TITLE }
  }

  // 4. availability 归并
  if (availabilityState === 'ready') {
    return { state: 'done', label: '完成', title: availabilityDescription ?? undefined }
  }
  if (availabilityState === 'partial') {
    // 运行中/等待结果/可查看（天气瓦片）等 → 有内容但未完整
    if (availabilityLabel === '排队中' || availabilityLabel === '等待重试') {
      return { state: 'queued', label: '排队中', title: availabilityDescription ?? undefined }
    }
    if (availabilityLabel === '运行中' || availabilityLabel === '等待结果') {
      return { state: 'running', label: '运行中', title: availabilityDescription ?? undefined }
    }
    // 可查看（天气层）/实验可运行/占位图层：可显示即视为完成
    return { state: 'done', label: '完成', title: availabilityDescription ?? undefined }
  }
  if (availabilityState === 'empty') {
    if (availabilityLabel === '数据异常' || availabilityLabel === '已取消') {
      return { state: 'error', label: '异常', title: availabilityDescription ?? undefined }
    }
    // 数据未就绪/待运行：数据还没来 → 排队中
    return { state: 'queued', label: '排队中', title: availabilityDescription ?? undefined }
  }

  // 5. lifecycle fresh 且 availability 无信号（如资产刚就绪的静态层）
  if (lifecycleState === 'fresh') {
    return { state: 'done', label: '完成', title: lifecycleMessage ?? undefined }
  }

  // 6. 无信号
  return null
}
