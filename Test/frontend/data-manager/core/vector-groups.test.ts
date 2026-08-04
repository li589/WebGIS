import { describe, expect, it } from 'vitest'
import { buildVectorGroups, describeShapefileReadiness, groupVectorFiles } from '@/data-manager/core/vector-groups'

function fakeFile(name: string): File {
  return new File([new Uint8Array([1, 2, 3])], name)
}

describe('vector-groups', () => {
  it('groups shp with sidecars by stem', () => {
    const files = [
      fakeFile('气候区划.shp'),
      fakeFile('气候区划.dbf'),
      fakeFile('气候区划.shx'),
      fakeFile('气候区划.prj'),
      fakeFile('other.geojson'),
    ]
    const groups = groupVectorFiles(files)
    expect(groups).toHaveLength(2)
    const shpGroup = groups.find((g) => g.some((f) => f.name.endsWith('.shp')))
    expect(shpGroup).toHaveLength(4)
  })

  it('flags missing dbf/shx when only shp selected', () => {
    const readiness = describeShapefileReadiness([fakeFile('气候区划.shp')])
    expect(readiness.ok).toBe(false)
    expect(readiness.errors[0]).toMatch(/缺少已选附属文件/)
    expect(readiness.errors[0]).toMatch(/浏览器不会自动上传/)
  })

  it('accepts complete shapefile set ignoring extension case', () => {
    const readiness = describeShapefileReadiness([
      fakeFile('a.shp'),
      fakeFile('a.dbf'),
      fakeFile('a.shx'),
    ])
    expect(readiness.ok).toBe(true)
    expect(
      buildVectorGroups([fakeFile('a.shp'), fakeFile('a.dbf'), fakeFile('a.shx')])[0]
        ?.missingSidecars,
    ).toBeUndefined()
  })
})
