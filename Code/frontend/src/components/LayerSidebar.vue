<script setup lang="ts">
defineProps<{
  datasets: string[]
  activeDataset: string
}>()

const emit = defineEmits<{
  selectDataset: [dataset: string]
}>()
</script>

<template>
  <aside class="panel">
    <div class="panel-header">
      <h2>图层与数据</h2>
      <span class="badge">实时</span>
    </div>

    <p class="panel-tip">这里后续会接风场、降水、温度、遥感反演结果，以及课题组算法输出图层。</p>

    <ul class="dataset-list">
      <li v-for="dataset in datasets" :key="dataset">
        <button
          class="dataset-button"
          :class="{ active: dataset === activeDataset }"
          @click="emit('selectDataset', dataset)"
        >
          {{ dataset }}
        </button>
      </li>
    </ul>

    <div class="panel-note">
      <h3>你可以学到</h3>
      <p>`v-for` 渲染列表、`props` 接收父组件数据、`emit` 回传用户点击事件。</p>
    </div>
  </aside>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
  padding: 1rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  border-radius: 1rem;
  background: rgba(10, 18, 33, 0.78);
  backdrop-filter: blur(14px);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

h2,
h3 {
  margin: 0;
  color: #eef6ff;
  font-size: 1rem;
}

.badge {
  padding: 0.2rem 0.55rem;
  border-radius: 999px;
  background: rgba(23, 201, 100, 0.14);
  color: #66f0a8;
  font-size: 0.78rem;
}

.panel-tip,
.panel-note p {
  margin: 0;
  color: #8ea3b8;
  line-height: 1.5;
  font-size: 0.88rem;
}

.dataset-list {
  display: grid;
  gap: 0.55rem;
  list-style: none;
  padding: 0;
  margin: 0;
}

.dataset-button {
  width: 100%;
  text-align: left;
  border: 1px solid rgba(136, 192, 255, 0.14);
  border-radius: 0.9rem;
  padding: 0.72rem 0.85rem;
  background: rgba(8, 18, 33, 0.66);
  color: #d8e4ef;
  cursor: pointer;
  font: inherit;
  font-size: 0.92rem;
  transition: border-color 0.2s ease, background-color 0.2s ease, transform 0.2s ease;
}

.dataset-button:hover {
  border-color: rgba(136, 192, 255, 0.4);
  transform: translateY(-1px);
}

.dataset-button.active {
  background: linear-gradient(135deg, rgba(10, 132, 255, 0.22), rgba(60, 180, 255, 0.14));
  border-color: rgba(96, 181, 255, 0.55);
}

.panel-note {
  padding-top: 0.55rem;
  border-top: 1px solid rgba(148, 163, 184, 0.12);
}

code {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
</style>
