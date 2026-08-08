// @vitest-environment jsdom
//
// Phase 2 缺口补齐（审查发现 F13，前端）：WeatherProviderSettings.vue 渲染分支防御测试。
//
// 该组件从 settings store 读取 weatherProviders / weatherConfig，并在模板中对多个
// 可选字段做了防御性读取（?. / ?? 兜底）。本文件挂载组件并注入不同形状的 store 数据，
// 验证以下分支在**缺失可选字段时不崩溃**：
//   1) config_schema 为 undefined —— 不应迭代崩溃，显示"无可配置项"。
//   2) field.options 为 undefined —— select 分支不应崩溃，回退到 textarea。
//   3) status.daily_quota = 0 —— 进度条 warn 分支（quota>0 才告警）不被触发。
//   4) provider_type 为 undefined —— typeMeta 回退到 free_api（"免费 API"）。
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, mount, setActivePinia } from '@/test-utils'
import { useSettingsStore } from '@/stores/settings'
import WeatherProviderSettings from '@/components/settings/WeatherProviderSettings.vue'

// 极简 weatherConfig，仅用于让"天气引擎概览"区块正常渲染（其字段均为可选读取）。
function baseWeatherConfig() {
  return {
    default_model: 'era5',
    cache_ttl_seconds: 60,
    max_active_weather_tile_runs: 4,
    sync_domains: [],
  }
}

// 构造一个 WeatherProviderItem 形状的运行时对象（TS 类型在 vitest 运行时被擦除，
// 只需提供模板实际读取的字段即可）。
function makeProvider(overrides: Record<string, unknown> = {}) {
  return {
    provider_id: 'test-provider',
    display_name: 'Test Provider',
    provider_type: 'free_api',
    enabled: true,
    version: '1.0.0',
    homepage_url: 'https://example.com',
    description: 'a test weather provider',
    priority: 10,
    supported_capabilities: ['temperature'],
    requires_api_key: false,
    status: { healthy: true, circuit_state: 'closed' },
    last_tested_at: null,
    last_test_status: null,
    config_schema: undefined,
    persisted_config: undefined,
    current_config: undefined,
    ...overrides,
  }
}

function mountWith(providers: unknown[], weatherConfig: unknown = baseWeatherConfig()) {
  setActivePinia(createPinia())
  const store = useSettingsStore()
  // storeToRefs 在组件内解包这两个 ref；直接赋值即可驱动渲染。
  store.weatherProviders = providers as never
  store.weatherConfig = weatherConfig as never
  return mount(WeatherProviderSettings)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('WeatherProviderSettings 可选字段防御', () => {
  it('weatherProviders 为空时不崩溃（空状态分支）', () => {
    const wrapper = mountWith([])
    expect(wrapper.find('.empty-state').exists()).toBe(true)
  })

  it('config_schema 为 undefined 时不崩溃，显示无可配置项', async () => {
    const wrapper = mountWith([makeProvider({ provider_id: 'p-no-schema' })])
    // 展开配置区（点击"配置"）
    const configBtns = wrapper.findAll('.action-btn.config')
    expect(configBtns.length).toBe(1)
    await configBtns[0].trigger('click')
    await wrapper.vm.$nextTick()

    // 没有 config_schema → 不应迭代子字段，显示"无可配置项"
    expect(wrapper.find('.no-config').exists()).toBe(true)
    expect(wrapper.text()).toContain('无可配置项')
  })

  it('field.options 为 undefined 时 select 分支不崩溃，回退 textarea', async () => {
    const schema = [
      { key: 'api_url', label: 'API URL', field_type: 'string', required: true },
      {
        key: 'mode',
        label: 'Mode',
        field_type: 'select',
        // 故意不给 options
        required: false,
      },
    ]
    const wrapper = mountWith([
      makeProvider({ provider_id: 'p-select-no-options', config_schema: schema }),
    ])
    const configBtns = wrapper.findAll('.action-btn.config')
    await configBtns[0].trigger('click')
    await wrapper.vm.$nextTick()

    // string 字段 → input；select 但 options 缺失 → 落入 v-else 的 textarea（不崩溃）
    expect(wrapper.find('input.form-input').exists()).toBe(true)
    expect(wrapper.find('textarea.form-textarea').exists()).toBe(true)
  })

  it('daily_quota = 0 时进度条不进入 warn 分支', () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const wrapper = mountWith([
      makeProvider({
        provider_id: 'p-quota-zero',
        status: {
          healthy: true,
          circuit_state: 'closed',
          daily_quota: 0,
          daily_used: 0,
          daily_remaining: 0,
        },
      }),
    ])
    const fill = wrapper.find('.runtime-bar-fill')
    expect(fill.exists()).toBe(true)
    // quota=0 时 warn 条件（daily_quota > 0）不成立 → 不应带 warn 类且不告警
    expect(fill.classes()).not.toContain('warn')
    const warnedAboutQuota = warnSpy.mock.calls.some((c) =>
      String(c[0]).toLowerCase().includes('quota'),
    )
    expect(warnedAboutQuota).toBe(false)
  })

  it('provider_type 为 undefined 时 typeMeta 回退到 free_api', () => {
    const wrapper = mountWith([
      makeProvider({ provider_id: 'p-unknown-type', provider_type: undefined }),
    ])
    const typeBadge = wrapper.find('.type-badge')
    expect(typeBadge.exists()).toBe(true)
    // typeMeta(undefined) → key 回退 'free_api' → 标签"免费 API"
    expect(typeBadge.text()).toContain('免费 API')
  })
})
