<script setup lang="ts">
/**
 * 助手额度条（输入框上方）。
 *
 * 数据来自 `GET /agent/quota`，与后端中间件的拦截口径同源：
 * 未登录按「访客号（缺省退回 IP）+ 北京自然日」计数，登录账号不占额度。
 *
 * 三种状态对应三套配色/文案：
 *   - 正常：还能问；
 *   - 将尽（剩余 ≤20%）：提示但不拦；
 *   - 用尽：说明原因与恢复时间，父组件据此把发送按钮置灰。
 *
 * 设计上刻意不显示 token 数字——用户无法通过 token 预估还能问几句。
 */
import { computed } from 'vue'

import type { AgentQuota } from '../../services/agent-api'

const props = defineProps<{
  quota: AgentQuota | null
  loading?: boolean
}>()

const percent = computed(() => {
  const q = props.quota
  if (!q || q.scope === 'account' || q.limit <= 0) return 100
  return Math.max(0, Math.min(100, q.percent))
})

const tone = computed<'ok' | 'low' | 'blocked'>(() => {
  const q = props.quota
  if (!q) return 'ok'
  if (q.blocked || (q.scope === 'guest' && q.limit > 0 && percent.value <= 0)) {
    return 'blocked'
  }
  if (q.scope === 'guest' && q.limit > 0 && percent.value <= 20) return 'low'
  return 'ok'
})

const isAccount = computed(() => props.quota?.scope === 'account')

const headline = computed(() => {
  if (props.loading && !props.quota) return '正在获取额度'
  const q = props.quota
  if (!q) return ''
  // 左侧标题已经写了「今日 AI 助手额度」，这里再返回同样的字会变成左右各一遍
  if (isAccount.value) return '不限次数'
  if (q.limit <= 0) return '不限次数'
  if (tone.value === 'blocked') return '已用完'
  return `剩余 ${percent.value}%`
})

const detail = computed(() => {
  const q = props.quota
  if (!q) return '向 AI 提问或发送指令会使用此额度。'
  if (isAccount.value) return '已登录，不占用访客额度，可正常提问。'
  if (q.limit <= 0) return '本站当前未限制访客提问次数。'
  if (tone.value === 'blocked') return q.message || '今日额度已用完，0 点恢复。'
  return '向 AI 提问或发送指令会使用此额度。可手动切换图层、选择日期和查看数据。'
})

/** 把 ISO 时间显示成「今天 24:00 / 明天 00:00」这类人话。 */
const resetLabel = computed(() => {
  const raw = props.quota?.reset_at
  if (!raw) return ''
  const at = new Date(raw)
  if (Number.isNaN(at.getTime())) return ''
  const hh = String(at.getHours()).padStart(2, '0')
  const mm = String(at.getMinutes()).padStart(2, '0')
  const month = String(at.getMonth() + 1).padStart(2, '0')
  const day = String(at.getDate()).padStart(2, '0')
  return `${month}-${day} ${hh}:${mm}`
})

const usageLine = computed(() => {
  const q = props.quota
  if (!q || q.scope !== 'guest' || q.limit <= 0) return ''
  return `今日已用 ${q.used} 次 / 上限 ${q.limit} 次`
})
</script>

<template>
  <section
    class="agent-quota"
    :class="[`agent-quota--${tone}`, { 'agent-quota--account': isAccount }]"
    aria-live="polite"
  >
    <div class="agent-quota__head">
      <span class="agent-quota__title">今日 AI 助手额度</span>
      <span class="agent-quota__value">{{ headline }}</span>
    </div>

    <div
      v-if="!isAccount && (quota?.limit ?? 0) > 0"
      class="agent-quota__track"
      role="progressbar"
      :aria-valuenow="percent"
      aria-valuemin="0"
      aria-valuemax="100"
      :aria-label="`今日 AI 助手额度剩余 ${percent}%`"
    >
      <div class="agent-quota__fill" :style="{ width: `${percent}%` }" />
    </div>

    <p class="agent-quota__detail">{{ detail }}</p>

    <p v-if="tone === 'blocked' && resetLabel" class="agent-quota__reset">
      额度将在 {{ resetLabel }}（北京时间）恢复
    </p>

    <details v-if="!isAccount && usageLine" class="agent-quota__more">
      <summary>查看 AI 用量</summary>
      <p>{{ usageLine }}</p>
      <p>每提一个问题或发一条指令计 1 次；切换图层、选择日期、查看数据不计次数。</p>
    </details>
  </section>
</template>

<style scoped>
.agent-quota {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  padding: 0.5rem 0.6rem;
  margin-bottom: 0.45rem;
  border-radius: 10px;
  border: 1px solid var(--accent-border);
  background: var(--accent-surface);
  color: var(--text-primary);
  font-size: 0.7rem;
  line-height: 1.5;
}

.agent-quota--low {
  border-color: var(--warning-border);
  background: var(--warning-surface);
}

.agent-quota--blocked {
  border-color: var(--danger-border);
  background: var(--danger-surface);
}

.agent-quota--account {
  border-color: var(--border-default);
  background: color-mix(in srgb, var(--surface-2) 60%, transparent);
}

.agent-quota__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
}

.agent-quota__title {
  font-weight: 600;
  font-size: 0.74rem;
  color: var(--text-primary);
}

.agent-quota__value {
  flex: none;
  font-weight: 600;
  font-size: 0.72rem;
  color: var(--accent);
}

.agent-quota--low .agent-quota__value {
  color: var(--warning);
}

.agent-quota--blocked .agent-quota__value {
  color: var(--danger);
}

.agent-quota--account .agent-quota__value {
  color: var(--text-secondary);
}

.agent-quota__track {
  height: 4px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--border-default) 75%, transparent);
  overflow: hidden;
}

.agent-quota__fill {
  height: 100%;
  border-radius: inherit;
  background: var(--accent);
  transition: width var(--motion-interactive-duration, 180ms) ease;
}

.agent-quota--low .agent-quota__fill {
  background: var(--warning);
}

.agent-quota--blocked .agent-quota__fill {
  background: var(--danger);
}

.agent-quota__detail {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.68rem;
}

.agent-quota--blocked .agent-quota__detail {
  color: var(--danger);
}

.agent-quota__reset {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.66rem;
}

.agent-quota__more {
  font-size: 0.66rem;
  color: var(--text-secondary);
}

.agent-quota__more summary {
  cursor: pointer;
  color: var(--accent);
  user-select: none;
}

.agent-quota__more p {
  margin: 0.2rem 0 0;
}
</style>
