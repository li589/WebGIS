/**
 * 矢量文件分组与 SHP sidecar 预检（浏览器无法读取未选中的同目录文件）。
 */
import { fileExtension } from './api'

const SHP_REQUIRED = ['dbf', 'shx'] as const
const SHP_OPTIONAL = ['prj', 'cpg', 'sbn', 'sbx', 'qix'] as const

export type VectorGroupKind = 'archive' | 'geojson' | 'shapefile' | 'other'

export interface VectorFileGroup {
  kind: VectorGroupKind
  files: File[]
  stem?: string
  missingSidecars?: string[]
}

export function fileStem(name: string): string {
  return name.replace(/\.[^.]+$/, '').toLowerCase()
}

/** 将选中文件拆成独立导入组：每个 zip/geojson 一组；同 stem 的 shp+sidecar 一组 */
export function groupVectorFiles(files: File[]): File[][] {
  return buildVectorGroups(files).map((g) => g.files)
}

export function buildVectorGroups(files: File[]): VectorFileGroup[] {
  const groups: VectorFileGroup[] = []
  const used = new Set<File>()
  const byStem = new Map<string, File[]>()

  for (const f of files) {
    const ext = fileExtension(f.name)
    if (ext === 'zip' || ext === 'rar') {
      groups.push({ kind: 'archive', files: [f] })
      used.add(f)
      continue
    }
    if (ext === 'geojson' || ext === 'json') {
      groups.push({ kind: 'geojson', files: [f] })
      used.add(f)
      continue
    }
    const stem = fileStem(f.name)
    const list = byStem.get(stem) ?? []
    list.push(f)
    byStem.set(stem, list)
  }

  for (const [stem, list] of byStem.entries()) {
    const leftover = list.filter((f) => !used.has(f))
    if (!leftover.length) continue
    const exts = new Set(leftover.map((f) => fileExtension(f.name)))
    if (exts.has('shp')) {
      const missing = SHP_REQUIRED.filter((ext) => !exts.has(ext))
      groups.push({
        kind: 'shapefile',
        files: leftover,
        stem,
        missingSidecars: missing.length ? missing.map((e) => `.${e}`) : undefined,
      })
    } else {
      groups.push({ kind: 'other', files: leftover, stem })
    }
  }
  return groups
}

export function describeShapefileReadiness(files: File[]): {
  ok: boolean
  lines: string[]
  errors: string[]
} {
  const groups = buildVectorGroups(files)
  const lines: string[] = []
  const errors: string[] = []

  for (const g of groups) {
    if (g.kind === 'archive' || g.kind === 'geojson') {
      lines.push(`✓ ${g.files[0]?.name}`)
      continue
    }
    if (g.kind === 'shapefile') {
      const exts = new Set(g.files.map((f) => fileExtension(f.name)))
      const checks = [
        ...SHP_REQUIRED.map((e) => ({ e, req: true })),
        ...SHP_OPTIONAL.map((e) => ({ e, req: false })),
      ]
      const parts = checks
        .filter((c) => c.req || exts.has(c.e))
        .map((c) => (exts.has(c.e) ? `✓.${c.e}` : `✗.${c.e}`))
      const label = `${g.stem ?? 'shp'}.shp  ${parts.join(' ')}`
      if (g.missingSidecars?.length) {
        lines.push(`✗ ${label}`)
        errors.push(
          `「${g.stem}.shp」缺少已选附属文件: ${g.missingSidecars.join(', ')}。` +
            `请在文件选择框中同时选中同名的 .dbf / .shx（Ctrl 多选，或打成 zip 再导入）。` +
            `浏览器不会自动上传磁盘同目录未选中的文件。`,
        )
      } else {
        lines.push(`✓ ${label}`)
      }
      continue
    }
    // orphan sidecars without shp
    const names = g.files.map((f) => f.name).join(', ')
    lines.push(`⚠ ${names}`)
    errors.push(`已选 ${names}，但缺少对应的 .shp，无法导入。`)
  }

  return { ok: errors.length === 0 && groups.length > 0, lines, errors }
}
