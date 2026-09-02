/**
 * 绘制模式离开守卫：空草稿丢弃、未闭合草图弹窗、编辑基线回滚。
 */
import { ref } from 'vue'
import type { DrawFeature } from '../stores/draw-store'
import { useDrawStore } from '../stores/draw-store'
import { useLayerWorkspace } from '../stores/layers/selectors'
import { useUiStore, type InteractionMode } from '../stores/ui'

export type DrawExitChoice = 'keep' | 'discard'

export interface DrawSessionState {
  isEmptySession: boolean
  hasUnclosedSketch: boolean
  hasClosedFeatures: boolean
}

export function getDrawSessionState(
  features: DrawFeature[],
  activeVertices: unknown[],
): DrawSessionState {
  const hasClosedFeatures = features.length > 0
  const hasUnclosedSketch = activeVertices.length > 0
  const isEmptySession = !hasClosedFeatures && !hasUnclosedSketch
  return { isEmptySession, hasUnclosedSketch, hasClosedFeatures }
}

const exitModalOpen = ref(false)
let exitModalResolver: ((choice: DrawExitChoice | null) => void) | null = null

export function useDrawSessionExitModal() {
  return {
    exitModalOpen,
    confirmExit(choice: DrawExitChoice) {
      exitModalOpen.value = false
      exitModalResolver?.(choice)
      exitModalResolver = null
    },
    cancelExit() {
      exitModalOpen.value = false
      exitModalResolver?.(null)
      exitModalResolver = null
    },
  }
}

function promptExitModal(): Promise<DrawExitChoice | null> {
  if (exitModalPromptOverride) return exitModalPromptOverride()
  return new Promise((resolve) => {
    exitModalResolver = resolve
    exitModalOpen.value = true
  })
}

let exitModalPromptOverride: (() => Promise<DrawExitChoice | null>) | null = null

/** 单测注入：绕过 UI 弹窗 */
export function __testSetExitModalPrompt(fn: (() => Promise<DrawExitChoice | null>) | null) {
  exitModalPromptOverride = fn
}

export function useDrawSessionTransition() {
  const drawStore = useDrawStore()
  const layersStore = useLayerWorkspace()
  const uiStore = useUiStore()

  function discardDraftLayerOnly() {
    const draftInstanceId = drawStore.draftLayerId
    if (draftInstanceId) {
      layersStore.removeLayer(draftInstanceId)
    }
    drawStore.clearDraft()
  }

  function finalizeEmptySession() {
    if (drawStore.draftLayerId) {
      discardDraftLayerOnly()
      return
    }
    if (drawStore.editingLayerId) {
      drawStore.revertToEditBaseline()
      drawStore.endEditSession()
      drawStore.features = []
      return
    }
    drawStore.clearDraft()
  }

  function discardModifications() {
    if (drawStore.editingLayerId) {
      drawStore.revertToEditBaseline()
    } else {
      drawStore.features = []
    }
    drawStore.clearActiveVertices()
    const state = getDrawSessionState(drawStore.features, drawStore.activeVertices)
    if (state.isEmptySession) {
      finalizeEmptySession()
    }
  }

  async function leaveDrawMode(): Promise<boolean> {
    const state = getDrawSessionState(drawStore.features, drawStore.activeVertices)

    if (state.isEmptySession) {
      finalizeEmptySession()
      return true
    }

    if (state.hasUnclosedSketch) {
      const choice = await promptExitModal()
      if (choice === null) return false
      if (choice === 'keep') {
        drawStore.clearActiveVertices()
        return true
      }
      discardModifications()
      return true
    }

    drawStore.clearActiveVertices()
    if (drawStore.editingLayerId) {
      drawStore.endEditSession()
      drawStore.features = []
    }
    return true
  }

  async function requestInteractionMode(next: InteractionMode): Promise<boolean> {
    const current = uiStore.interactionMode
    if (current === 'draw' && next !== 'draw') {
      const ok = await leaveDrawMode()
      if (!ok) return false
    }
    if (next !== 'measure' && current === 'measure') {
      uiStore.clearMeasure()
    }
    if (next === 'draw' && current !== 'draw') {
      uiStore.clearMeasure()
    }
    uiStore.setInteractionMode(next)
    return true
  }

  return {
    leaveDrawMode,
    requestInteractionMode,
    discardDraftLayerOnly,
    finalizeEmptySession,
    getDrawSessionState: () => getDrawSessionState(drawStore.features, drawStore.activeVertices),
  }
}
