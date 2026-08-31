import { describe, expect, it } from 'vitest'

import { cleanProductDisplayName, stripDataExtension } from '@/utils/workflow-result-naming'

describe('workflow-result-naming 共享清洗（P2-C 收敛回归锁）', () => {
  it('stripDataExtension 剥数据扩展名（大小写不敏感，含 hdf5/he5/tar/gz）', () => {
    expect(stripDataExtension('landcover_025.mat')).toBe('landcover_025')
    expect(stripDataExtension('RESULT.TIF')).toBe('RESULT')
    expect(stripDataExtension('a/b/c.nc')).toBe('a/b/c')
    expect(stripDataExtension('archive.tar')).toBe('archive')
    expect(stripDataExtension('noext')).toBe('noext')
  })

  it('cleanProductDisplayName 剥 materialize 前缀 + 路径段 + 扩展名', () => {
    expect(cleanProductDisplayName('Algorithm Map Layer: CLCD 土地利用')).toBe('CLCD 土地利用')
    expect(cleanProductDisplayName('Algorithm Output: 结果报告')).toBe('结果报告')
    // 注意：路径段正则剥「最后一个分隔符+末段」（留目录）——与旧实现
    // 行为等价（注释曾误写"只留文件名"，收敛时保持原语义不顺手改）。
    expect(cleanProductDisplayName('Algorithm Map Layer: /data/out/landcover_025.tif')).toBe(
      '/data/out',
    )
    expect(cleanProductDisplayName('  SM_20251201.mat  ')).toBe('SM_20251201')
    // 今日三联报障 A 场景：全大写文件名不得泄漏扩展名
    expect(cleanProductDisplayName('Algorithm Map Layer: LANDCOVER_025.MAT')).toBe(
      'LANDCOVER_025',
    )
  })

  it('cleanProductDisplayName 空值安全', () => {
    expect(cleanProductDisplayName('')).toBe('')
  })
})
