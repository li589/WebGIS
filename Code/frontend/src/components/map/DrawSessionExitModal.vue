<script setup lang="ts">
import AppButton from '../ui/AppButton.vue'
import AppModal from '../ui/AppModal.vue'
import { useDrawSessionExitModal } from '../../composables/useDrawSessionTransition'

const { exitModalOpen, confirmExit, cancelExit } = useDrawSessionExitModal()
</script>

<template>
  <AppModal
    :open="exitModalOpen"
    aria-label="未闭合的绘制要素"
    :close-on-backdrop="false"
    max-width="min(420px, 92vw)"
    @close="cancelExit"
  >
    <div class="draw-exit-modal">
      <h3 class="draw-exit-modal__title">存在未闭合的绘制要素</h3>
      <p class="draw-exit-modal__body">
        切换模式将结束当前绘制。保留修改则丢弃未闭合部分并保留已闭合多边形；不保留则撤销本次修改（空图层将被移除）。
      </p>
      <div class="draw-exit-modal__actions">
        <AppButton size="sm" variant="secondary" @click="cancelExit">取消</AppButton>
        <AppButton size="sm" variant="secondary" @click="confirmExit('discard')">
          不保留修改
        </AppButton>
        <AppButton size="sm" variant="primary" @click="confirmExit('keep')">保留修改</AppButton>
      </div>
    </div>
  </AppModal>
</template>

<style scoped>
.draw-exit-modal {
  padding: 1.1rem 1.25rem 1.25rem;
}

.draw-exit-modal__title {
  margin: 0 0 0.5rem;
  font-size: var(--font-size-body);
  font-weight: 600;
}

.draw-exit-modal__body {
  margin: 0 0 1rem;
  font-size: var(--font-size-caption);
  color: var(--text-secondary);
  line-height: 1.5;
}

.draw-exit-modal__actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.45rem;
  flex-wrap: wrap;
}
</style>
