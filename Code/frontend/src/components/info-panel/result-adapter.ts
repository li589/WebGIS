import type { WorkflowRunViewResponse, WorkflowRunViewSummaryRow } from '../../services/runtime-api'

export interface ResultDisplayModel {
  category: string
  title: string
  subtitle: string
  statusText: string
  progressText: string
  metricRows: WorkflowRunViewSummaryRow[]
  canShowResultLink: boolean
  resultUrl?: string | null
}

export function buildResultDisplayModel(view: WorkflowRunViewResponse | null | undefined): ResultDisplayModel | null {
  if (!view) return null

  return {
    category: view.category,
    title: view.title,
    subtitle: view.subtitle,
    statusText: view.status_text,
    progressText: view.progress_text,
    metricRows: view.metric_rows ?? [],
    canShowResultLink: view.can_show_link,
    resultUrl: view.result_url,
  }
}
