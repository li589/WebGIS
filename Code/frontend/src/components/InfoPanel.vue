<script setup lang="ts">
import type { DemoHotspot, DemoLayer } from '../app/demo-data'

defineProps<{
  viewLabel: string
  activeLayer: DemoLayer
  hourLabel: string
  stageLabel: string
  visibleHotspots: DemoHotspot[]
}>()
</script>

<template>
  <aside class="panel">
    <div class="panel-topline">
      <div class="panel-header">
        <div>
          <h2>分析</h2>
          <p class="panel-subtitle">当前摘要</p>
        </div>
        <span class="readiness">{{ stageLabel }}</span>
      </div>

      <dl class="meta-list">
        <div>
          <dt>图层</dt>
          <dd>{{ activeLayer.name }}</dd>
        </div>
        <div>
          <dt>时间</dt>
          <dd>{{ hourLabel }}</dd>
        </div>
        <div>
          <dt>视图</dt>
          <dd>{{ viewLabel }}</dd>
        </div>
        <div>
          <dt>来源</dt>
          <dd>{{ activeLayer.sourceLabel }}</dd>
        </div>
      </dl>
    </div>

    <section class="hero-metric" :style="{ '--accent-color': activeLayer.accentColor }">
      <span>{{ activeLayer.metricLabel }}</span>
      <strong>{{ activeLayer.metricValue }}</strong>
      <p>{{ activeLayer.trendLabel }}</p>
    </section>

    <div class="insight-grid">
      <article class="insight-card">
        <span>更新频率</span>
        <strong>{{ activeLayer.updateLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>可用性</span>
        <strong>{{ activeLayer.availabilityLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>可靠性</span>
        <strong>{{ activeLayer.confidenceLabel }}</strong>
      </article>
      <article class="insight-card">
        <span>观测时间</span>
        <strong>{{ activeLayer.observationTimeLabel }}</strong>
      </article>
    </div>

    <div class="learning-note">
      <h3>摘要</h3>
      <p>{{ activeLayer.summary }}</p>
    </div>

    <details class="protocol-details">
      <summary>接入占位</summary>
      <p>协议模式：{{ activeLayer.dataStateLabel }}</p>
      <p>状态说明：{{ activeLayer.availabilityDescription }}</p>
      <p>缺失字段：{{ activeLayer.missingFieldsLabel }}</p>
      <p>字段别名：{{ activeLayer.fieldAliasLabel }}</p>
      <p>时间字段：{{ activeLayer.observationFieldLabel }}</p>
      <p>空值占位：{{ activeLayer.emptyStateLabel }}</p>
    </details>

    <div class="learning-note">
      <h3>热点区域</h3>
      <p v-if="visibleHotspots.length === 0" class="empty-hotspot">当前时段暂无可用热点，保留协议占位。</p>
      <ul v-else class="hotspot-list">
        <li v-for="hotspot in visibleHotspots" :key="hotspot.id">
          <span>{{ hotspot.name }}</span>
          <strong>{{ hotspot.value }}</strong>
        </li>
      </ul>
    </div>
  </aside>
</template>

<style scoped>
.panel {
  display: grid;
  gap: 0.56rem;
  padding: 0.58rem;
  border-radius: 0.88rem;
  border: 1px solid rgba(148, 163, 184, 0.15);
  background: linear-gradient(180deg, rgba(13, 21, 36, 0.42), rgba(8, 15, 28, 0.3));
  backdrop-filter: blur(18px);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.03),
    0 12px 26px rgba(1, 8, 16, 0.14);
  max-height: min(31rem, calc(100vh - 10rem));
  overflow: auto;
}

.panel-topline {
  display: grid;
  gap: 0.46rem;
  padding: 0.12rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 0.55rem;
}

h2,
h3 {
  margin: 0;
  color: #eef7ff;
  font-size: 0.76rem;
}

.panel-subtitle {
  margin: 0.14rem 0 0;
  color: #8195aa;
  font-size: 0.62rem;
}

.readiness {
  padding: 0.18rem 0.4rem;
  border-radius: 999px;
  background: rgba(84, 181, 255, 0.1);
  border: 1px solid rgba(84, 181, 255, 0.14);
  color: #a7dbff;
  font-size: 0.58rem;
}

.meta-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.34rem;
  margin: 0;
}

.meta-list div {
  padding: 0.34rem 0.38rem;
  border: 1px solid rgba(148, 163, 184, 0.08);
  border-radius: 0.7rem;
  background: rgba(8, 18, 33, 0.3);
}

dt {
  margin-bottom: 0.16rem;
  color: #8fa5b9;
  font-size: 0.58rem;
}

dd {
  margin: 0;
  color: #e1ebf5;
  font-size: 0.68rem;
}

.hero-metric {
  display: grid;
  gap: 0.24rem;
  padding: 0.58rem;
  border-radius: 0.78rem;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--accent-color) 12%, rgba(8, 18, 33, 0.82)), rgba(8, 18, 33, 0.58)),
    rgba(8, 18, 33, 0.52);
  border: 1px solid color-mix(in srgb, var(--accent-color) 22%, rgba(136, 192, 255, 0.14));
}

.hero-metric span {
  color: #95a8bb;
  font-size: 0.58rem;
}

.hero-metric strong {
  color: #f4fbff;
  font-size: 1.1rem;
  line-height: 1.1;
}

.hero-metric p {
  margin: 0;
  color: #d7e8f8;
  font-size: 0.64rem;
  line-height: 1.3;
}

.insight-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.3rem;
}

.insight-card {
  display: grid;
  gap: 0.18rem;
  padding: 0.42rem 0.46rem;
  border-radius: 0.72rem;
  background: rgba(8, 18, 33, 0.34);
  border: 1px solid rgba(148, 163, 184, 0.08);
}

.insight-card span {
  color: #8aa0b5;
  font-size: 0.56rem;
}

.insight-card strong {
  color: #e7f2fc;
  font-size: 0.64rem;
}

.learning-note {
  display: grid;
  gap: 0.22rem;
  padding: 0.12rem;
}

.protocol-details {
  display: grid;
  gap: 0.22rem;
  padding: 0.12rem;
}

.protocol-details summary {
  cursor: pointer;
  color: #eef7ff;
  font-size: 0.7rem;
  list-style: none;
}

.protocol-details summary::-webkit-details-marker {
  display: none;
}

.protocol-details summary::after {
  content: '展开';
  float: right;
  color: #88a8c7;
  font-size: 0.58rem;
}

.protocol-details[open] summary::after {
  content: '收起';
}

.learning-note p {
  margin: 0;
  color: #91a5b9;
  line-height: 1.34;
  font-size: 0.62rem;
}

.hotspot-list {
  display: grid;
  gap: 0.26rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.hotspot-list li {
  display: flex;
  justify-content: space-between;
  gap: 0.4rem;
  padding: 0.38rem 0.44rem;
  border-radius: 0.68rem;
  background: rgba(8, 18, 33, 0.28);
  border: 1px solid rgba(148, 163, 184, 0.08);
  color: #d8e6f2;
  font-size: 0.6rem;
}

.hotspot-list strong {
  color: #f6fbff;
}

.empty-hotspot {
  margin: 0;
  color: #9aabc0;
  font-size: 0.62rem;
  line-height: 1.34;
}
</style>
