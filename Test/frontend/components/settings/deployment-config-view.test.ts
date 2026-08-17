// @vitest-environment jsdom
//
// 部署配置中心（/deployment，DeploymentConfigView）渲染与三步状态机测试：
//   1) 分组渲染 + 三方对比元信息 + 敏感键不回填；
//   2) 预览：payload 只含非空键、int 转数值、敏感键留空不发送；
//   3) 预览失败（errors）阻断保存；成功后确认保存调用 PUT 并提示重启。
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createPinia, createRouter, mount, setActivePinia } from '@/test-utils'
import DeploymentConfigView from '@/views/DeploymentConfigView.vue'
import {
  getDeploymentConfig,
  previewDeploymentConfig,
  updateDeploymentConfig,
} from '@/services/settings-api'
import type { DeploymentConfigStatus } from '@/types/api-reexports'

vi.mock('@/services/settings-api', () => ({
  getDeploymentConfig: vi.fn(),
  previewDeploymentConfig: vi.fn(),
  updateDeploymentConfig: vi.fn(),
  restartBackendService: vi.fn(),
  waitForBackendHealthy: vi.fn(),
  deploymentConfigExportUrl: vi.fn(() => '/config/deployment/export?redact=true'),
}))

const mockedGet = vi.mocked(getDeploymentConfig)
const mockedPreview = vi.mocked(previewDeploymentConfig)
const mockedUpdate = vi.mocked(updateDeploymentConfig)

function key(overrides: Record<string, unknown>) {
  return {
    group: 'data',
    group_label: '数据根与导入导出',
    key: 'data_root',
    env_key: 'BACKEND_DATA_ROOT',
    kind: 'path',
    label: '地理数据根目录',
    restart_level: 'restart-backend',
    must_exist: true,
    sensitive: false,
    double_write_sync: false,
    runtime_value: 'D:/geo',
    env_value: 'D:/geo',
    config_value: 'D:/geo',
    source: 'config',
    pending: false,
    ...overrides,
  }
}

function makeStatus(): DeploymentConfigStatus {
  return {
    path: 'D:/repo/Code/backend/deployment.config.json',
    exists: true,
    schema_version: 1,
    applied_env_keys: ['BACKEND_DATA_ROOT'],
    keys: [
      key({}),
      key({
        group: 'runtime',
        group_label: '运行时与日志',
        key: 'log_level',
        env_key: 'BACKEND_LOG_LEVEL',
        kind: 'level',
        label: '日志级别',
        must_exist: false,
        runtime_value: 'INFO',
        env_value: '',
        config_value: 'WARNING',
        source: 'config',
        pending: true,
      }),
      key({
        group: 'docker',
        group_label: 'Docker 与 Open-Meteo',
        key: 'open_meteo_host_port',
        env_key: 'OPEN_METEO_HOST_PORT',
        kind: 'int',
        label: 'Open-Meteo 宿主端口',
        restart_level: 'restart-full',
        must_exist: false,
        runtime_value: '8080',
      }),
      key({
        group: 'docker',
        key: 'minio_root_password',
        env_key: 'MINIO_ROOT_PASSWORD',
        kind: 'password',
        label: 'MinIO root 密码',
        sensitive: true,
        runtime_value: '••••',
        env_value: '••••',
        config_value: '••••',
      }),
    ],
    backups: [
      {
        name: 'deployment.config.json.bak.1',
        path: 'D:/repo/Code/backend/deployment.config.json.bak.1',
        size_bytes: 512,
        mtime: 1_700_000_000,
      },
    ],
    pending_restart: true,
    env_path: 'D:/repo/Code/backend/.env',
    sync_env_path: 'D:/repo/Code/infra/data-sync/.env',
    notes: 'lab deploy',
  }
}

async function flushPromises(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

const testRouter = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/deployment', component: { template: '<div />' } },
  ],
})

async function mountView() {
  const wrapper = mount(DeploymentConfigView, {
    global: { plugins: [createPinia(), testRouter] },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mockedGet.mockResolvedValue(makeStatus())
})

describe('DeploymentConfigView render', () => {
  it('renders group cards, meta chips, backup and pending badges', async () => {
    const wrapper = await mountView()
    const text = wrapper.text()
    expect(text).toContain('部署与数据源配置中心')
    expect(text).toContain('数据根与导入导出')
    expect(text).toContain('运行时与日志')
    expect(text).toContain('Docker 与 Open-Meteo')
    expect(text).toContain('待重启生效')
    expect(text).toContain('deployment.config.json.bak.1')
    // notes 预填在 textarea 值中（v-model）
    const notesBox = wrapper.find('textarea')
    expect((notesBox.element as HTMLTextAreaElement).value).toBe('lab deploy')
  })

  it('renders password input without prefilling masked value', async () => {
    const wrapper = await mountView()
    const pwd = wrapper.find('input[type="password"]')
    expect(pwd.exists()).toBe(true)
    expect((pwd.element as HTMLInputElement).value).toBe('')
    expect(pwd.attributes('placeholder')).toContain('留空保持不变')
    // 掩码绝不出现在表单值中
    expect((pwd.element as HTMLInputElement).value).not.toContain('•')
  })

  it('renders level key as select with unset option and current config value', async () => {
    const wrapper = await mountView()
    const select = wrapper.find('select')
    expect(select.exists()).toBe(true)
    expect((select.element as HTMLSelectElement).value).toBe('WARNING')
    const optionTexts = select.findAll('option').map((o) => o.text())
    expect(optionTexts).toContain('（未设置）')
    expect(optionTexts).toContain('DEBUG')
  })
})

describe('DeploymentConfigView preview → apply', () => {
  it('sends only non-empty keys, converts ints, omits sensitive blank', async () => {
    mockedPreview.mockResolvedValue({
      ok: true,
      errors: [],
      warnings: [],
      diff: [{ group: 'data', key: 'data_root', env_key: 'BACKEND_DATA_ROOT', old: 'D:/geo', new: 'E:/geo', restart_level: 'restart-backend' }],
      restart_level: 'restart-backend',
    })
    const wrapper = await mountView()

    const textInputs = wrapper.findAll('input[type="text"]')
    const rootInput = textInputs.find(
      (i) => (i.element as HTMLInputElement).value === 'D:/geo',
    )
    expect(rootInput).toBeTruthy()
    await rootInput!.setValue('E:/geo')

    const intInput = wrapper.find('input[type="number"]')
    await intInput.setValue('8081')

    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    expect(mockedPreview).toHaveBeenCalledTimes(1)
    const payload = mockedPreview.mock.calls[0][0]
    expect(payload.data).toEqual({ data_root: 'E:/geo' })
    expect(payload.docker).toEqual({ open_meteo_host_port: 8081 })
    // 表单为全量期望态：config_value 预填的 level 一并提交（json 全量替换语义）
    expect(payload.runtime).toEqual({ log_level: 'WARNING' })
    expect(payload.notes).toBe('lab deploy')
    // diff 表渲染
    expect(wrapper.text()).toContain('变更预览')
    expect(wrapper.text()).toContain('E:/geo')
  })

  it('blocks apply when preview has errors', async () => {
    mockedPreview.mockResolvedValue({
      ok: false,
      errors: ['data.data_root：必须为绝对路径'],
      warnings: [],
      diff: [],
      restart_level: 'none',
    })
    const wrapper = await mountView()
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('校验失败')
    expect(wrapper.text()).toContain('必须为绝对路径')
    const applyBtn = wrapper.findAll('button').find((b) => b.text() === '确认并保存')
    expect(applyBtn).toBeTruthy()
    expect((applyBtn!.element as HTMLButtonElement).disabled).toBe(true)
    expect(mockedUpdate).not.toHaveBeenCalled()
  })

  it('applies via PUT after confirm and surfaces restart guidance', async () => {
    mockedPreview.mockResolvedValue({
      ok: true,
      errors: [],
      warnings: ['caches.cache_dir 不存在，保存时将自动创建'],
      diff: [{ group: 'docker', key: 'minio_root_user', env_key: 'MINIO_ROOT_USER', old: '', new: 'cgda-minio', restart_level: 'restart-full' }],
      restart_level: 'restart-full',
    })
    mockedUpdate.mockResolvedValue({
      applied_env_keys: ['MINIO_ROOT_USER'],
      sync_env_keys: [],
      config_path: 'D:/repo/Code/backend/deployment.config.json',
      env_path: 'D:/repo/Code/backend/.env',
      sync_env_path: null,
      restart_level: 'restart-full',
      pending_restart: true,
      warnings: [],
      backups: ['deployment.config.json.bak.1'],
      message: '已保存并镜像写入 .env；含 Docker 相关键，需在服务器执行全量重启（launch.py restart）后生效。',
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const wrapper = await mountView()
    await wrapper.find('button.btn-primary').trigger('click')
    await flushPromises()

    const applyBtn = wrapper.findAll('button').find((b) => b.text() === '确认并保存')
    expect(applyBtn).toBeTruthy()
    await applyBtn!.trigger('click')
    await flushPromises()

    expect(mockedUpdate).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('已保存')
    expect(wrapper.text()).toContain('launch.py restart')
  })

  it('shows load error banner with retry', async () => {
    mockedGet.mockRejectedValue(new Error('Settings API failed: 403 /config/deployment'))
    const wrapper = await mountView()
    expect(wrapper.text()).toContain('加载失败')
    expect(wrapper.text()).toContain('403')

    mockedGet.mockResolvedValue(makeStatus())
    const retry = wrapper.findAll('button').find((b) => b.text() === '重试')
    await retry!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('数据根与导入导出')
  })
})
