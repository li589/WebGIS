// @vitest-environment jsdom
//
// 发布就绪修复（P0-11）：建立前端组件渲染回归网的首个用例。
// 此前 Test/frontend 446 个用例全为纯 TS 模块逻辑测试，无任何 .vue 挂载渲染测试，
// 模板绑定 / props / v-if 分支 / 空态无自动化覆盖。本文件以 AboutSettings（架构树无条件渲染、
// 其余区块依赖 store.aboutInfo 空态）为例，验证 @vue/test-utils + jsdom 渲染链路可用。
//
// 2026-08 扩展：项目信息五项字段（名称/版本/描述/后端服务/前端界面）、
// 引擎状态卡片区移除（改由架构图节点状态点承载）、节点状态色与悬停提示。
import { describe, expect, it } from 'vitest'
// 经 src 内垫片引入，避免 root 外测试文件直接 bare import 无法解析 node_modules。
import { createPinia, mount, setActivePinia } from '@/test-utils'
import AboutSettings from '@/components/settings/AboutSettings.vue'
import Tooltip from '@/components/ui/Tooltip.vue'
import { useSettingsStore } from '@/stores/settings'
import type {
  AboutInfo,
  DataSourceConfig,
  GeeRuntimeConfig,
  WeatherConfig,
} from '@/services/settings-api'

const aboutInfoFixture: AboutInfo = {
  project_name: 'Comprehensive Geographic Data Analysis System (CGDA) Backend',
  version: '0.1.0',
  description: '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
}

const geeDisabledFixture: GeeRuntimeConfig = {
  gee_enabled: false,
  max_parallel_exports: 2,
  max_parallel_uploads: 2,
  max_parallel_downloads: 2,
  account_cooldown_seconds: 300,
  storage_backend: 'minio',
  local_storage_root: 'D:/data',
  api_account_management_enabled: false,
  credentials_encryption_enabled: true,
}

const weatherConfigFixture: WeatherConfig = {
  default_model: 'gfs_global',
  cache_ttl_seconds: 300,
  refresh_forecast_hours: 48,
  schedule_enabled: true,
  default_latitude: 23.1,
  default_longitude: 113.3,
  default_place_name: '广州',
  max_active_weather_tile_runs: 4,
}

const dataSourceFixture: DataSourceConfig = {
  storage_backend: 'local',
  data_root: 'D:/data',
  output_root: 'D:/output',
  download_source_root: '',
  download_real_fetch_enabled: false,
  tile_proxy_enabled: false,
  tile_proxy_cache_ttl_seconds: 0,
  static_cache_root: '',
  cache_dir: '',
}

describe('AboutSettings 组件渲染', () => {
  it('无 aboutInfo 时渲染架构树并显示加载占位', () => {
    setActivePinia(createPinia())
    const wrapper = mount(AboutSettings)

    // 架构树无条件渲染（v-for 绑定正常）
    const text = wrapper.text()
    expect(text).toContain('前端层')
    expect(text).toContain('后端层')
    expect(text).toContain('引擎层')
    expect(text).toContain('数据层')

    // aboutInfo 为 null → v-if 空态分支显示"加载中"
    expect(wrapper.find('.loading-hint').exists()).toBe(true)
    expect(wrapper.find('.loading-hint').text()).toContain('加载中')
  })

  it('点击架构节点切换 selected 选中态', async () => {
    setActivePinia(createPinia())
    const wrapper = mount(AboutSettings)

    const node = wrapper.find('.arch-node.level-1')
    expect(node.exists()).toBe(true)
    expect(node.classes()).not.toContain('selected')

    await node.trigger('click')
    expect(node.classes()).toContain('selected')

    // 再次点击取消选中
    await node.trigger('click')
    expect(node.classes()).not.toContain('selected')
  })
})

describe('AboutSettings 项目信息', () => {
  it('渲染五项字段：项目名称（平台英文显示名）/ 版本 / 描述 / 后端服务 / 前端界面（浏览器内核）', () => {
    setActivePinia(createPinia())
    const store = useSettingsStore()
    store.aboutInfo = aboutInfoFixture
    const wrapper = mount(AboutSettings)

    const rows = wrapper.findAll('.info-row')
    expect(rows).toHaveLength(5)

    expect(rows[0].find('.info-label').text()).toBe('项目名称')
    expect(rows[0].find('.info-value').text()).toBe('Star-Ground Fusion Soil Data Platform')

    expect(rows[1].find('.info-label').text()).toBe('版本')
    expect(rows[1].find('.info-value').text()).toBe('0.1.0')

    expect(rows[2].find('.info-label').text()).toBe('描述')
    expect(rows[2].find('.info-value').text()).toBe(
      '星地融合土壤水分监测与干旱预警数据分析与可视化系统',
    )

    expect(rows[3].find('.info-label').text()).toBe('后端服务')
    expect(rows[3].find('.info-value').text()).toBe(
      'Comprehensive Geographic Data Analysis System (CGDA) Backend',
    )

    expect(rows[4].find('.info-label').text()).toBe('前端界面')
    expect(rows[4].find('.info-value').text()).not.toBe('')
  })
})

describe('AboutSettings 引擎状态融入架构图', () => {
  it('不再渲染独立的引擎状态卡片区', () => {
    setActivePinia(createPinia())
    const wrapper = mount(AboutSettings)

    expect(wrapper.text()).not.toContain('引擎状态')
    expect(wrapper.find('.engine-status').exists()).toBe(false)
    expect(wrapper.find('.engine-card').exists()).toBe(false)
  })

  it('架构图节点以状态点颜色呈现启停，悬停提示携带状态文字', () => {
    setActivePinia(createPinia())
    const store = useSettingsStore()
    store.geeRuntimeConfig = geeDisabledFixture
    store.weatherConfig = weatherConfigFixture
    store.dataSourceConfig = dataSourceFixture
    const wrapper = mount(AboutSettings)

    const findNode = (selector: string, keyword: string) =>
      wrapper.findAll(selector).find((n) => n.text().includes(keyword))

    // GEE 引擎：gee_enabled=false → 关闭（灰色点 + 节点降透明）
    const geeNode = findNode('.arch-node.level-2', 'GEE 引擎')
    expect(geeNode).toBeDefined()
    expect(geeNode!.find('.status-dot.disabled').exists()).toBe(true)
    expect(geeNode!.classes()).toContain('disabled')

    // 天气引擎：配置已加载 → 启用（绿色点）
    const weatherNode = findNode('.arch-node.level-2', '天气引擎')
    expect(weatherNode).toBeDefined()
    expect(weatherNode!.find('.status-dot.enabled').exists()).toBe(true)
    expect(weatherNode!.classes()).toContain('enabled')

    // 数据层：数据源配置已加载 → 启用
    const dataNode = findNode('.arch-node.level-1', '数据层')
    expect(dataNode).toBeDefined()
    expect(dataNode!.find('.status-dot.enabled').exists()).toBe(true)

    // 无状态来源的节点不渲染状态点
    const algoNode = findNode('.arch-node.level-2', '算法引擎')
    expect(algoNode).toBeDefined()
    expect(algoNode!.find('.status-dot').exists()).toBe(false)

    // Tooltip 悬停文案含状态说明；无状态节点的 Tooltip 文案为空
    const tooltips = wrapper.findAllComponents(Tooltip)
    expect(tooltips.some((t) => t.props('text') === 'GEE 引擎：关闭')).toBe(true)
    expect(tooltips.some((t) => t.props('text') === '天气引擎：启用')).toBe(true)
    expect(tooltips.some((t) => t.props('text') === '数据层：启用')).toBe(true)
    expect(tooltips.some((t) => t.props('text') === '')).toBe(true)
  })

  it('配置未加载时节点呈加载中状态', () => {
    setActivePinia(createPinia())
    const wrapper = mount(AboutSettings)

    const geeNode = wrapper
      .findAll('.arch-node.level-2')
      .find((n) => n.text().includes('GEE 引擎'))
    expect(geeNode).toBeDefined()
    expect(geeNode!.find('.status-dot.loading').exists()).toBe(true)

    const tooltips = wrapper.findAllComponents(Tooltip)
    expect(tooltips.some((t) => t.props('text') === 'GEE 引擎：加载中')).toBe(true)
  })
})
