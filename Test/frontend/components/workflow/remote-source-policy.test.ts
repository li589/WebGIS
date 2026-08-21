import { describe, expect, it } from 'vitest'
import {
  authorizedPrefixesForSource,
  collectManagedPrefixes,
  filterSourcesByDatasetPolicy,
} from '@/components/workflow/node-forms/remote-source-policy'
import type { RemoteDatasetPolicy, RemoteSourceEntry } from '@/types/api-reexports'

function makeEntry(overrides: Partial<RemoteSourceEntry> = {}): RemoteSourceEntry {
  return {
    remote_source_id: 'src-1',
    kind: 'storage_profile',
    ref_id: 'profile-a',
    remote_path: 'GLDAS/data',
    display_name: '',
    cache_policy: 'standard',
    access_mode: 'legacy',
    archived: false,
    created_at: '',
    updated_at: '',
    ref: null,
    ref_exists: true,
    ...overrides,
  }
}

function makePolicy(overrides: Partial<RemoteDatasetPolicy> = {}): RemoteDatasetPolicy {
  return {
    portal_id: 'nasa_gldas',
    managed: true,
    compatible: false,
    datasets: [
      {
        grant_id: 'g1',
        dataset_key: 'GLDAS_NOAH025_3H',
        title: '',
        path_prefix: ['GLDAS/data'],
      },
    ],
    ...overrides,
  }
}

describe('filterSourcesByDatasetPolicy（#57 编辑器授权过滤）', () => {
  it('site_compatible 源全放行（无视前缀）', () => {
    const entries = [makeEntry({ access_mode: 'site_compatible', remote_path: 'ANY/secret' })]
    const policy = [makePolicy()]
    expect(filterSourcesByDatasetPolicy(entries, policy)).toHaveLength(1)
  })

  it('policy 为 null（拉取失败）→ fail-open 放行', () => {
    const entries = [makeEntry({ remote_path: 'UNRELATED/path' })]
    expect(filterSourcesByDatasetPolicy(entries, null)).toHaveLength(1)
  })

  it('授权前缀并集为空（未管控）→ 放行', () => {
    const entries = [makeEntry({ remote_path: 'ANY/path' })]
    const policy = [makePolicy({ datasets: [] })]
    expect(filterSourcesByDatasetPolicy(entries, policy)).toHaveLength(1)
  })

  it('legacy 源 remote_path 在授权前缀子树内 → 可选', () => {
    const entries = [makeEntry({ remote_path: 'GLDAS/data/subdir' })]
    const policy = [makePolicy()]
    expect(filterSourcesByDatasetPolicy(entries, policy)).toHaveLength(1)
  })

  it('legacy 源与授权前缀无交集 → 过滤掉', () => {
    const entries = [makeEntry({ remote_path: 'SECRET/other' })]
    const policy = [makePolicy()]
    expect(filterSourcesByDatasetPolicy(entries, policy)).toHaveLength(0)
  })

  it('前缀是 remote_path 的子目录（反向子树）→ 可选', () => {
    // remote_path=GLDAS（整源粗粒度注册），授权前缀 GLDAS/data 是其子目录 → 可选
    const entries = [makeEntry({ remote_path: 'GLDAS' })]
    const policy = [makePolicy()]
    expect(filterSourcesByDatasetPolicy(entries, policy)).toHaveLength(1)
  })

  it('compatible 门户的前缀不参与并集', () => {
    const entries = [makeEntry({ remote_path: 'SECRET/other' })]
    const policy = [makePolicy({ compatible: true })]
    // compatible 门户不贡献前缀 → 并集空 → 放行
    expect(filterSourcesByDatasetPolicy(entries, policy)).toHaveLength(1)
  })

  it('多门户前缀取并集（与后端全量 grants 语义一致）', () => {
    const entries = [makeEntry({ remote_path: 'SMAP/granule' })]
    const policy = [
      makePolicy(), // GLDAS/data
      makePolicy({
        portal_id: 'nsidc_data',
        datasets: [
          { grant_id: 'g2', dataset_key: 'SPL3SMP_E', title: '', path_prefix: ['SMAP/granule'] },
        ],
      }),
    ]
    expect(filterSourcesByDatasetPolicy(entries, policy)).toHaveLength(1)
  })
})

describe('collectManagedPrefixes / authorizedPrefixesForSource', () => {
  it('汇总管控门户前缀（归一化小写去斜杠）', () => {
    const policy = [
      makePolicy({ datasets: [{ grant_id: 'g', dataset_key: 'K', title: '', path_prefix: [' /A/B/ ', 'C'] }] }),
    ]
    expect(collectManagedPrefixes(policy)).toEqual(['a/b', 'c'])
  })

  it('site_compatible 源无前缀提示', () => {
    const entry = makeEntry({ access_mode: 'site_compatible' })
    expect(authorizedPrefixesForSource(entry, [makePolicy()])).toEqual([])
  })

  it('legacy 源返回交集前缀', () => {
    const entry = makeEntry({ remote_path: 'GLDAS/data' })
    expect(authorizedPrefixesForSource(entry, [makePolicy()])).toEqual(['gldas/data'])
  })
})
