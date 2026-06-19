<script setup lang="ts">
defineProps<{
  hourLabel: string
}>()

const emit = defineEmits<{
  step: [delta: number]
}>()
</script>

<template>
  <section class="timeline">
    <div class="timeline-main">
      <div>
        <p class="timeline-label">时间轴</p>
        <strong>{{ hourLabel }}</strong>
      </div>

      <div class="timeline-actions">
        <button @click="emit('step', -1)">上一小时</button>
        <button @click="emit('step', 1)">下一小时</button>
      </div>
    </div>

    <p class="timeline-tip">后续这里可以接真实时间轴组件、动画播放、时空范围筛选和任务触发。</p>
  </section>
</template>

<style scoped>
.timeline {
  padding: 0.85rem 1rem;
  border-radius: 1rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(10, 18, 33, 0.78);
  backdrop-filter: blur(14px);
}

.timeline-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.timeline-label {
  margin: 0 0 0.25rem;
  color: #8aa0b4;
  font-size: 0.82rem;
}

strong {
  font-size: 1.05rem;
  color: #f2f8ff;
}

.timeline-actions {
  display: inline-flex;
  gap: 0.75rem;
}

button {
  border: 1px solid rgba(136, 192, 255, 0.2);
  border-radius: 0.8rem;
  padding: 0.58rem 0.85rem;
  background: rgba(8, 18, 33, 0.84);
  color: #dce8f4;
  cursor: pointer;
  font: inherit;
  font-size: 0.9rem;
}

.timeline-tip {
  margin: 0.65rem 0 0;
  color: #8ea3b8;
  font-size: 0.84rem;
}

@media (max-width: 700px) {
  .timeline-main {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
