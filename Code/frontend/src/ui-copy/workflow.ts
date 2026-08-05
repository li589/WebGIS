/** 工作流入口与状态 */
export const WORKFLOW_COPY = {
  entry: '工作流',
  entryTitle: '工作流编辑器（含定时器）',
  editorTitle: '工作流',
  statusOverview: '工作流状态',
  statusDone: '已完成',
  openEditorLog: '打开工作流编辑器',

  // 提交 / 生命周期
  submitting: '正在提交工作流…',
  reconcilingSubmit: '提交超时，正在对账认领运行…',
  queued: '已入队',
  running: '运行中',
  cancelling: '取消中…',
  cancelled: '已取消',
  cancelledSubmit: '已取消提交',
  waitingCompute: '等待计算…',
  submitFailed: '提交工作流失败',
  capacityWaiting: '工作流并发数已达上限，正在等待空闲后自动重试…',
  capacityRetrying: '等待工作流容量，自动重试中…',
  capacityExhausted: '工作流容量不足，已达最大重试次数，请稍后手动重试',
  cancelFailed: '取消工作流失败',
  retryFailed: '重试工作流失败',
  retryOf: '重试自',

  // 预检 / 设置
  dryValidateOk: '图模式预检通过',
  dryValidateFailed: '图模式预检未通过，请修复后再提交',
  useSystemSettings: '使用系统设置',
  pipelineParamsOverrideTip: '启动器参数优先覆盖节点 algorithm_params 中的同名键',
  reuseBlockCache: '复用未完成块缓存',

  // incremental 物化
  progressiveSyncOk: '已同步 {count} 个时间片到地图',
  progressiveSyncFailed: '增量结果同步失败，将在下次重试',
  progressiveSyncPartial: '部分时间片已同步（{count}），同步仍在继续…',

  // 结果回显空态（审查 BUG-4）
  noMapLayers: '工作流已完成，但未生成可显示的地图图层。',

  // 状态面板
  copyRunTimeline: '复制运行时间线',
  filterByStage: '按阶段过滤',
  allStages: '全部阶段',
  emptyStatus: '暂无工作流任务',
  cancelAction: '取消',
  retryAction: '重试',
  staticLayerHint: '静态（无时间序列）',

  // 调度护栏
  runtimeCapacity: '运行容量',
  queueWorkers: '队列与 Worker',
  softLimit: '软超时',
  poolOccupancy: '池占用',
} as const
