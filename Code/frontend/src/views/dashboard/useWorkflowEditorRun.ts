/**
 * useWorkflowEditorRun — 从工作流编辑器提交运行。
 *
 * 从 DashboardView.vue 提取：handleRunWorkflowFromEditor（~200 行编译 + 提交逻辑）。
 */
import type { Ref } from 'vue'
import type { useLogStore } from '../../stores/log'
import {
  useWorkflowOutputLayersStore,
  WORKFLOW_OUTPUT_SUBCATEGORY,
} from '../../stores/workflow-output-layers'
import type { WorkflowRunTarget } from '../../components/workflow/WorkflowRunDialog.vue'
import { useLayerWorkspace, useLayerViewport, useWorkflowRun } from '../../stores/layers/selectors'

export function useWorkflowEditorRun(
  logStore: ReturnType<typeof useLogStore>,
  workflowOutputStore: ReturnType<typeof useWorkflowOutputLayersStore>,
  workflowEditorOpen: Ref<boolean>,
  workflowStatusOpen: Ref<boolean>,
  workflowEditorRef: Ref<{
    notifyRunOutcome?: (ok: boolean, message?: string) => void
  } | null>,
) {
  const workspace = useLayerWorkspace()
  const viewport = useLayerViewport()
  const workflowRun = useWorkflowRun()
  async function handleRunWorkflowFromEditor(
    workflowId: string,
    linkedLayerId: string | null,
    target: WorkflowRunTarget,
    canvasGraph?: {
      nodes: import('../../services/workflow-definition-api').WorkflowDefinitionNode[]
      links: import('../../services/workflow-definition-api').WorkflowDefinitionLink[]
    } | null,
  ) {
    logStore.logWorkflow(
      'workflow-editor-run',
      `从编辑器运行工作流: ${workflowId} (目标: ${target.mode})`,
    )
    const sourceLayerId = target.layerId ?? linkedLayerId
    if (!sourceLayerId) {
      const msg = `工作流 ${workflowId} 未关联图层，无法运行`
      logStore.logWorkflow('workflow-editor-error', msg)
      workflowEditorRef.value?.notifyRunOutcome?.(false, msg)
      return
    }

    const targets = target.targets?.length
      ? target.targets
      : [{ name: target.name ?? `产出`, productTag: 'result' }]
    // 组标题禁止落成 omega_sf_fenkuai_* 等机器 id
    const rawGroupTitle = target.groupTitle || (target.name ? `${target.name} · 计算中` : '')
    const groupTitle =
      rawGroupTitle && !/omega[-_]sf[-_]fenkuai|omega[-_]avg[-_]daily/i.test(rawGroupTitle)
        ? rawGroupTitle
        : '反演产物 · 计算中'

    let memberCatalogIds: string[] | undefined
    if (target.mode === 'new') {
      const engine =
        workspace.layerLibrary.value.find((l) => l.catalogId === sourceLayerId)?.engine ?? 'general'
      const entries = workflowOutputStore.createOutputLayers(
        targets.map((t) => ({ name: t.name, group: WORKFLOW_OUTPUT_SUBCATEGORY })),
        workflowId,
        sourceLayerId,
        engine,
      )
      memberCatalogIds = entries.map((e) => e.localId)
      logStore.logWorkflow(
        'workflow-output-create',
        `创建 ${entries.length} 个产出图层 → ${WORKFLOW_OUTPUT_SUBCATEGORY}`,
      )
    }

    const created = workflowRun.createRunLayerGroup({
      title: groupTitle,
      targets,
      sourceLayerId,
      workflowId,
      memberCatalogIds,
    })
    const catalogId = created.memberCatalogIds[0] || sourceLayerId

    workflowEditorOpen.value = false
    workflowStatusOpen.value = true

    try {
      let algorithmRequest: Record<string, unknown> | undefined
      let weatherRequest: Record<string, unknown> | undefined
      let topLevelTimeRange: Record<string, unknown> | undefined
      const nodes = canvasGraph?.nodes ?? []
      const links = canvasGraph?.links ?? []
      if (nodes.length > 0) {
        const { dryValidateWorkflowGraph } = await import('../../services/workflow-definition-api')
        const { WorkflowValidationError } = await import('../../services/_http')
        const { WORKFLOW_COPY } = await import('../../ui-copy/workflow')
        const { buildTimeRangeFromProps } =
          await import('../../components/workflow/dimension-model')
        const graphPayload = {
          workflow_id: workflowId,
          name: workflowId,
          nodes,
          links,
        }
        try {
          const validated = await dryValidateWorkflowGraph(graphPayload)
          const def = validated.workflow_definition as Record<string, unknown>
          if (!def) {
            throw new Error(WORKFLOW_COPY.dryValidateFailed)
          }
          const engine =
            ((def.metadata as Record<string, unknown> | undefined)?.engine as string | undefined) ??
            'python_provider'
          const canvasNodes = ((def.nodes as unknown) ?? nodes) as Array<Record<string, unknown>>
          for (const node of canvasNodes) {
            const props = (node.properties ?? node.params ?? {}) as Record<string, unknown>
            const ntype = String(node.type ?? node.node_type ?? '')
            const isTime =
              ntype === 'data/time_range' ||
              ntype.endsWith('/time_range') ||
              props.module_name === 'time_range'
            if (!isTime) continue
            const built = buildTimeRangeFromProps(props)
            if (built?.start_at && built?.end_at) {
              topLevelTimeRange = {
                start_at: built.start_at,
                end_at: built.end_at,
                granularity: built.granularity ?? 'day',
              }
              break
            }
          }
          if (engine === 'weather') {
            weatherRequest = {
              workflow_id: workflowId,
              layer_id: sourceLayerId,
              workflow: def,
              context: {
                latitude: viewport.currentMapCenter.value.lat,
                longitude: viewport.currentMapCenter.value.lng,
              },
              priority: 'viewport',
            }
          } else {
            const datasourceSelection: Record<string, unknown> = {}
            const algorithmParams: Record<string, unknown> = {}
            for (const node of canvasNodes) {
              const props = (node.properties ?? node.params ?? {}) as Record<string, unknown>
              const ntype = String(node.type ?? node.node_type ?? '')
              const moduleName = String(props.module_name ?? '')
              const isSource =
                ntype === 'data/source' ||
                ntype.endsWith('/source') ||
                moduleName === 'data_source' ||
                moduleName === 'source'
              if (isSource) {
                const key = String(props.dataset_key ?? props.key ?? '').trim()
                const path = String(props.path ?? props.value ?? '').trim()
                if (key && path) datasourceSelection[key] = path
              }
              const ap = props.algorithm_params
              if (ap && typeof ap === 'object' && !Array.isArray(ap)) {
                Object.assign(algorithmParams, ap as Record<string, unknown>)
              }
            }
            algorithmRequest = {
              workflow_definition: def,
              workflow_entry_name: workflowId,
              datasource_selection: datasourceSelection,
              algorithm_params: algorithmParams,
              output_spec: {},
              tags: { source: 'workflow_editor', workflow_id: workflowId },
            }
            if (topLevelTimeRange) {
              algorithmRequest.time_range = {
                start: topLevelTimeRange.start_at,
                end: topLevelTimeRange.end_at,
              }
            }
          }
          logStore.logWorkflow(
            'workflow-editor-compile',
            `${WORKFLOW_COPY.dryValidateOk}(${engine}): nodes=${(def.nodes as unknown[] | undefined)?.length ?? 0}`,
          )
        } catch (error) {
          if (error instanceof WorkflowValidationError) {
            const detail =
              error.issues
                .map((i) => i.message)
                .filter(Boolean)
                .join('；') ||
              error.message ||
              WORKFLOW_COPY.dryValidateFailed
            throw new Error(`${WORKFLOW_COPY.dryValidateFailed}：${detail}`, { cause: error })
          }
          throw error
        }
      }
      const runId = await workflowRun.runWorkflowForCatalog(catalogId, {
        algorithmRequest,
        weatherRequest,
        timeRange: topLevelTimeRange,
        commandLabel: `运行画布工作流 ${workflowId}`,
        resourceProfile: /omega_sf|omega_block|omega_avg/i.test(workflowId) ? 'heavy' : undefined,
      })
      if (typeof runId === 'string' && runId) {
        workflowRun.bindRunIdToGroup(created.groupId, runId)
      }
      workflowEditorRef.value?.notifyRunOutcome?.(true)
    } catch (error) {
      workflowRun.updateRunGroupFromJob('', {
        status: 'failed',
        progress: 0,
        message: String(error),
      })
      const g = workflowRun.findRunGroupById(created.groupId)
      if (g) {
        g.status = 'failed'
        g.dissolvable = true
        g.message = (error as Error)?.message ?? String(error)
      }
      const msg = (error as Error)?.message ?? String(error)
      workflowEditorRef.value?.notifyRunOutcome?.(false, msg)
      if (/天气引擎|瓦片/.test(msg)) {
        workflowStatusOpen.value = true
      }
    }
  }

  return { handleRunWorkflowFromEditor }
}
