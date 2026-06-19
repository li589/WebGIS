<script setup lang="ts">
defineProps<{
  currentModeLabel: string
  activeDataset: string
  hourLabel: string
}>()
</script>

<template>
  <aside class="panel">
    <h2>结果与说明</h2>

    <dl class="meta-list">
      <div>
        <dt>当前模式</dt>
        <dd>{{ currentModeLabel }}</dd>
      </div>
      <div>
        <dt>数据图层</dt>
        <dd>{{ activeDataset }}</dd>
      </div>
      <div>
        <dt>时间点</dt>
        <dd>{{ hourLabel }}</dd>
      </div>
    </dl>

    <div class="learning-note">
      <h3>学习重点</h3>
      <p>你现在看到的是一个典型的“父页面统一调度，多个子组件分别负责一块 UI”的 Vue 项目壳子。</p>
    </div>

    <div class="learning-note">
      <h3>下一步建议</h3>
      <p>先把这个占位页面看懂，再把 `MapCanvas` 换成真实地图组件，最后接接口和任务状态。</p>
    </div>
  </aside>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 0.85rem;
  padding: 1rem;
  border-radius: 1rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  background: rgba(10, 18, 33, 0.78);
  backdrop-filter: blur(14px);
}

h2,
h3 {
  margin: 0;
  color: #eef7ff;
  font-size: 1rem;
}

.meta-list {
  display: grid;
  gap: 0.7rem;
  margin: 0;
}

.meta-list div {
  padding-bottom: 0.75rem;
  border-bottom: 1px solid rgba(148, 163, 184, 0.12);
}

dt {
  margin-bottom: 0.3rem;
  color: #8fa5b9;
  font-size: 0.82rem;
}

dd {
  margin: 0;
  color: #e1ebf5;
  font-size: 0.92rem;
}

.learning-note {
  display: grid;
  gap: 0.35rem;
}

.learning-note p {
  margin: 0;
  color: #91a5b9;
  line-height: 1.5;
  font-size: 0.86rem;
}
</style>
