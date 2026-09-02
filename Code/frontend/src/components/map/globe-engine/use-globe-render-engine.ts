/**
 * 订阅本地「3D 渲染引擎」偏好，供 Dashboard / 设置共用。
 */
import { onUnmounted, ref, type Ref } from 'vue'

import {
  getGlobeRenderEngine,
  subscribeGlobeScene,
  type GlobeRenderEngine,
} from '../../../services/settings-local'

export function useGlobeRenderEngine(): Ref<GlobeRenderEngine> {
  const engine = ref<GlobeRenderEngine>(getGlobeRenderEngine())
  const unsubscribe = subscribeGlobeScene(() => {
    engine.value = getGlobeRenderEngine()
  })
  onUnmounted(() => {
    unsubscribe()
  })
  return engine
}
