<script setup lang="ts">
/**
 * 时间轴动作确认卡 + 失败通知条。
 * 默认左下角（图层管理器下方、比例尺/图层信息上方）；可拖到视口内任意完整可见位置；置顶显示。
 */
import { computed, nextTick, onMounted, onScopeDispose, ref, toRef, watch } from 'vue'
import AppButton from './ui/AppButton.vue'
import Tooltip from './ui/Tooltip.vue'
import { useTimelineActionBannerStore } from '../stores/timeline-action-banner'

const banner = useTimelineActionBannerStore()
const notice = toRef(banner, 'notice')
const confirm = toRef(banner, 'confirm')
const recovery = toRef(banner, 'recovery')
const alignChecked = toRef(banner, 'alignChecked')

const emit = defineEmits<{
  reuse: []
  rerun: []
  cancel: []
  dismissNotice: []
  switchOnline: []
  openPlan: []
  dismissRecovery: []
}>()

const rootRef = ref<HTMLElement | null>(null)
/** 用户拖动后的视口坐标（left/top）；null 表示用默认左下角 CSS */
const placed = ref<{ left: number; top: number } | null>(null)
const dragging = ref(false)

const PAD = 8

const noticePreview = computed(() => {
  const raw = String(notice.value?.message || '').trim()
  if (raw.length <= 56) return raw
  return `${raw.slice(0, 54)}…`
})

const noticeFull = computed(() => String(notice.value?.message || '').trim())

const recoveryPreview = computed(() => {
  const raw = String(recovery.value?.message || '').trim()
  if (raw.length <= 56) return raw
  return `${raw.slice(0, 54)}…`
})

const recoveryFull = computed(() => {
  const r = recovery.value
  if (!r) return ''
  const parts = [r.timeKey, r.message].filter(Boolean)
  return parts.join('\n')
})

const recoveryHasSwitchOnline = computed(() =>
  Boolean(recovery.value?.offers.includes('switch_online')),
)

const recoveryHasOpenPlan = computed(() => Boolean(recovery.value?.offers.includes('open_plan')))

const recoveryPlanHint = computed(() => String(recovery.value?.planHint || '').trim())

const confirmHint = computed(() => {
  const c = confirm.value
  if (!c) return ''
  const parts = [c.timeKey, c.scopeLabel, c.layerHint].filter(Boolean)
  return parts.join('\n')
})

const posStyle = computed(() => {
  if (!placed.value) return undefined
  return {
    left: `${placed.value.left}px`,
    top: `${placed.value.top}px`,
    right: 'auto',
    bottom: 'auto',
  } as Record<string, string>
})

function clampToViewport(left: number, top: number, width: number, height: number) {
  const maxL = Math.max(PAD, window.innerWidth - width - PAD)
  const maxT = Math.max(PAD, window.innerHeight - height - PAD)
  return {
    left: Math.min(Math.max(PAD, left), maxL),
    top: Math.min(Math.max(PAD, top), maxT),
  }
}

function ensureFullyVisible() {
  const el = rootRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  if (!placed.value) {
    // 默认定位：若溢出视口右侧/上方，改写成 placed 并夹紧
    if (rect.right > window.innerWidth - PAD || rect.top < PAD) {
      placed.value = clampToViewport(rect.left, rect.top, rect.width, rect.height)
    }
    return
  }
  placed.value = clampToViewport(placed.value.left, placed.value.top, rect.width, rect.height)
}

let dragOffsetX = 0
let dragOffsetY = 0
let activePointerId: number | null = null

function onDragPointerDown(e: PointerEvent) {
  // 仅左键；点在按钮/输入上不拖（手柄/正文空白可拖）
  if (e.button !== 0) return
  const t = e.target as HTMLElement | null
  if (t?.closest('button, input, label, a, .tab-actions')) return
  const el = rootRef.value
  if (!el) return
  e.preventDefault()
  e.stopPropagation()
  const rect = el.getBoundingClientRect()
  // 首次拖动：从当前几何转为 left/top
  if (!placed.value) {
    placed.value = { left: rect.left, top: rect.top }
  }
  dragOffsetX = e.clientX - placed.value.left
  dragOffsetY = e.clientY - placed.value.top
  dragging.value = true
  activePointerId = e.pointerId
  // 捕获挂在根节点，避免子树（Tooltip 等）吞掉 pointermove
  el.setPointerCapture?.(e.pointerId)
}

function onDragPointerMove(e: PointerEvent) {
  if (!dragging.value || activePointerId !== e.pointerId) return
  const el = rootRef.value
  if (!el || !placed.value) return
  const w = el.offsetWidth
  const h = el.offsetHeight
  placed.value = clampToViewport(e.clientX - dragOffsetX, e.clientY - dragOffsetY, w, h)
}

function onDragPointerUp(e: PointerEvent) {
  if (activePointerId !== e.pointerId) return
  dragging.value = false
  activePointerId = null
  ensureFullyVisible()
}

function onResize() {
  ensureFullyVisible()
}

watch(
  () => Boolean(confirm.value || notice.value || recovery.value),
  async (open) => {
    if (!open) return
    await nextTick()
    ensureFullyVisible()
  },
)

onMounted(() => {
  window.addEventListener('resize', onResize)
})

onScopeDispose(() => {
  window.removeEventListener('resize', onResize)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="confirm || notice || recovery"
      ref="rootRef"
      class="timeline-action-banner timeline-action-banner--slide-in"
      :class="{
        'is-placed': Boolean(placed),
        'is-dragging': dragging,
        'cgda-dragging': dragging,
        'cgda-drag-lift': dragging,
      }"
      :style="posStyle"
      role="region"
      aria-label="时间轴动作提示"
      @pointerdown="onDragPointerDown"
      @pointermove="onDragPointerMove"
      @pointerup="onDragPointerUp"
      @pointercancel="onDragPointerUp"
    >
      <div class="tab-drag" title="拖动到任意位置" aria-hidden="true">
        <span class="tab-drag-grip" />
      </div>
      <div v-if="confirm" class="tab-card tab-card--confirm">
        <div class="tab-main">
          <span class="tab-badge">确认</span>
          <Tooltip
            :text="confirmHint"
            position="top"
            :max-width="'20rem'"
            :wrap="true"
            :delay-ms="150"
          >
            <strong class="tab-time">{{ confirm.timeKey }}</strong>
            <span class="tab-scope">{{ confirm.scopeLabel }}</span>
          </Tooltip>
        </div>
        <div class="tab-actions" role="group" aria-label="时间轴操作">
          <AppButton
            v-if="confirm.canReuse"
            variant="secondary"
            size="xs"
            type="button"
            @click="emit('reuse')"
          >
            复用
          </AppButton>
          <AppButton variant="primary" size="xs" type="button" @click="emit('rerun')">
            重跑
          </AppButton>
          <AppButton
            variant="ghost"
            size="xs"
            type="button"
            class="tab-btn-cancel"
            @click="emit('cancel')"
          >
            取消
          </AppButton>
        </div>
        <label v-if="confirm.alignOffer" class="tab-align">
          <input
            type="checkbox"
            :checked="alignChecked"
            @change="banner.setAlignChecked(($event.target as HTMLInputElement).checked)"
          />
          <Tooltip
            :text="confirm.alignOffer.label"
            position="top"
            :max-width="'18rem'"
            :wrap="true"
          >
            <span class="tab-align-text">{{ confirm.alignOffer.label }}</span>
          </Tooltip>
        </label>
      </div>
      <div v-else-if="recovery" class="tab-card tab-card--recovery">
        <div class="tab-main">
          <span class="tab-badge tab-badge--warn">{{ recoveryPlanHint || '缺数' }}</span>
          <Tooltip
            :text="recoveryFull"
            position="top"
            :max-width="'22rem'"
            :wrap="true"
            :delay-ms="120"
          >
            <p class="tab-msg">
              <template v-if="recoveryPlanHint"
                ><strong class="tab-time">{{ recoveryPlanHint }}</strong>
                <template v-if="recovery.timeKey"> · {{ recovery.timeKey }}</template>
              </template>
              <template v-else>
                <template v-if="recovery.timeKey"
                  ><strong class="tab-time">{{ recovery.timeKey }}</strong> ·
                </template>
                {{ recoveryPreview }}
              </template>
            </p>
          </Tooltip>
          <button
            type="button"
            class="tab-dismiss-x"
            aria-label="关闭"
            title="关闭"
            @click="emit('dismissRecovery')"
          >
            ×
          </button>
        </div>
        <div class="tab-actions" role="group" aria-label="缺数恢复">
          <AppButton
            v-if="recoveryHasSwitchOnline"
            variant="primary"
            size="xs"
            type="button"
            @click="emit('switchOnline')"
          >
            切换在线重跑
          </AppButton>
          <AppButton
            v-if="recoveryHasOpenPlan"
            :variant="recoveryHasSwitchOnline ? 'secondary' : 'primary'"
            size="xs"
            type="button"
            @click="emit('openPlan')"
          >
            {{ recoveryPlanHint ? '打开' : '打开计划' }}
          </AppButton>
          <AppButton
            variant="secondary"
            size="xs"
            type="button"
            class="tab-btn-cancel"
            @click="emit('dismissRecovery')"
          >
            关闭
          </AppButton>
        </div>
      </div>
      <div
        v-else-if="notice"
        class="tab-card"
        :class="notice.tone === 'info' ? 'tab-card--info' : 'tab-card--error'"
      >
        <div class="tab-main">
          <span
            class="tab-badge"
            :class="notice.tone === 'info' ? 'tab-badge--info' : 'tab-badge--err'"
          >
            {{ notice.tone === 'info' ? '提示' : '失败' }}
          </span>
          <Tooltip
            :text="noticeFull"
            position="top"
            :max-width="'22rem'"
            :wrap="true"
            :delay-ms="120"
          >
            <p class="tab-msg">{{ noticePreview }}</p>
          </Tooltip>
          <button
            type="button"
            class="tab-dismiss-x"
            aria-label="关闭"
            title="关闭"
            @click="emit('dismissNotice')"
          >
            ×
          </button>
        </div>
        <div class="tab-actions" role="group" aria-label="关闭提示">
          <AppButton
            variant="secondary"
            size="xs"
            type="button"
            class="tab-btn-cancel"
            @click="emit('dismissNotice')"
          >
            关闭
          </AppButton>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.timeline-action-banner {
  /* 默认：左下角，图层面板下方、比例尺/图层信息上方 */
  position: fixed;
  left: 12px;
  bottom: 56px;
  z-index: var(--z-toast);
  width: min(26rem, calc(100vw - 1.5rem));
  max-width: calc(100vw - 1.5rem);
  pointer-events: auto;
  cursor: grab;
  touch-action: none;
  /* 盖住地图控件与侧栏，避免被遮挡 */
  isolation: isolate;
}

.timeline-action-banner--slide-in {
  animation: tab-slide-in-left 0.28s ease-out;
}

@keyframes tab-slide-in-left {
  from {
    opacity: 0;
    transform: translateX(-18px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .timeline-action-banner--slide-in {
    animation: none;
  }
}

.timeline-action-banner.is-placed {
  bottom: auto;
  right: auto;
}

/* 拖拽视觉由全局 .cgda-dragging / .cgda-drag-lift 承担 */
.timeline-action-banner.is-dragging {
  cursor: grabbing;
}

.tab-drag {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 1.1rem;
  padding: 0.25rem 0 0.1rem;
  margin-bottom: -0.05rem;
  cursor: grab;
  touch-action: none;
}

.tab-drag-grip {
  width: 2.6rem;
  height: 0.34rem;
  border-radius: 999px;
  background: var(--border-strong);
  opacity: 0.9;
  pointer-events: none;
}

.tab-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem 0.5rem;
  padding: 0.35rem 0.4rem 0.35rem 0.45rem;
  border-radius: var(--radius-md, 0.5rem);
  background: var(--surface-2);
  border: 1px solid var(--border-strong);
  box-shadow: var(--elevation-2, 0 4px 14px var(--shadow-ambient));
  color: var(--text-strong);
  position: relative;
}

.tab-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.35rem;
  bottom: 0.35rem;
  width: 3px;
  border-radius: 0 2px 2px 0;
  background: var(--accent);
}

.tab-card--confirm {
  border-color: var(--accent-border, var(--border-strong));
}

.tab-card--recovery {
  border-color: var(--warning-border, var(--accent-border, var(--border-strong)));
}

.tab-card--recovery::before {
  background: var(--warning, var(--accent));
}

.tab-card--error {
  border-color: var(--danger-border);
}

.tab-card--error::before {
  background: var(--danger);
}

.tab-card--info {
  border-color: var(--info-border, var(--border-strong));
}

.tab-card--info::before {
  background: var(--info, var(--accent));
}

.tab-main {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  min-width: 0;
  flex: 1 1 10rem;
  padding-left: 0.35rem;
}

.tab-dismiss-x {
  flex: 0 0 auto;
  margin-left: auto;
  border: none;
  background: transparent;
  color: var(--text-muted, var(--text-strong));
  font-size: 1.05rem;
  line-height: 1;
  padding: 0.1rem 0.3rem;
  border-radius: var(--radius-sm, 0.25rem);
  cursor: pointer;
  opacity: 0.7;
}

.tab-dismiss-x:hover,
.tab-dismiss-x:focus-visible {
  opacity: 1;
  background: color-mix(in srgb, var(--text-strong) 10%, transparent);
  outline: none;
}

.tab-badge {
  flex: 0 0 auto;
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  padding: 0.1rem 0.32rem;
  border-radius: 0.28rem;
  color: var(--text-strong);
  background: var(--accent-surface);
  border: 1px solid var(--accent-border, var(--border-default));
}

.tab-badge--err {
  background: var(--danger-surface);
  border-color: var(--danger-border);
  color: var(--danger);
}

.tab-badge--warn {
  background: var(--warning-surface, var(--accent-surface));
  border-color: var(--warning-border, var(--accent-border, var(--border-default)));
  color: var(--warning, var(--accent-strong));
}

.tab-badge--info {
  background: var(--info-surface, var(--accent-surface));
  border-color: var(--info-border, var(--border-default));
  color: var(--info, var(--accent-strong));
}

.tab-time {
  flex: 0 1 auto;
  font-size: 0.78rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text-strong);
  white-space: nowrap;
  margin-right: 0.25rem;
}

.tab-scope {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 0.7rem;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tab-msg {
  margin: 0;
  min-width: 0;
  flex: 1 1 auto;
  font-size: 0.75rem;
  line-height: 1.25;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 16rem;
}

.tab-align {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  flex: 1 1 100%;
  margin-left: 0.35rem;
  font-size: 0.7rem;
  color: var(--text-secondary);
  cursor: pointer;
}

.tab-align-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.tab-actions {
  display: inline-flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 0.28rem;
  margin-left: auto;
  padding: 0.18rem;
  border-radius: var(--radius-sm, 0.32rem);
  background: var(--surface-sunken);
  border: 1px solid var(--border-default);
  cursor: default;
}

.tab-actions :deep(.app-btn) {
  min-width: 2.75rem;
  font-weight: 600;
  cursor: pointer;
}

.tab-actions :deep(.tab-btn-cancel.app-btn--ghost),
.tab-actions :deep(.app-btn--ghost) {
  border-color: var(--border-default);
  color: var(--text-primary);
  background: var(--surface-2);
}

.tab-actions :deep(.app-btn--ghost:hover:not(:disabled)) {
  border-color: var(--border-strong);
  color: var(--text-strong);
  background: var(--surface-hover);
}

/* Tooltip 触发区在 flex 行内占满剩余空间 */
.tab-main :deep(.tooltip-wrapper) {
  display: inline-flex;
  min-width: 0;
  flex: 1 1 auto;
  align-items: center;
  gap: 0.35rem;
}
</style>
