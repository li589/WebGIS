/** 在线计划会话（L1）只读文案 — 侧栏 / 分析框 / 面板同源 */
export const ONLINE_PLAN_COPY = {
  /** 图层侧栏 / 分析框：该 catalog 在计划会话 tabs 中 */
  pendingBadge: '待计划',
  pendingBadgeTitle: '缺数可恢复，已加入在线计划会话（确认前不改失败态）',
  /** parked 角标 */
  parkedDock: (n: number) => `待决策 ${n}`,
  parkedDockAria: '打开在线计划会话',
  /** 面板标题区 */
  panelTitle: '在线计划',
  panelSub: '确认前不改失败态 · 不排队',
  applyToActive: '套用到草稿',
  applyToAll: '套用到全部草稿',
  applyToAllHint: '统一时间锁开启：将时段写入本会话全部图层',
  invalidTimeKey: '请输入有效时段（如 2025-12-03 或 2025-12-03T00:00:00）',
  confirmNeedTime: '请先填写并套用有效时段再确认',
  confirmCta: '确认并在线重跑',
  parkCta: '收起',
  submittingCta: '提交中…',
} as const
