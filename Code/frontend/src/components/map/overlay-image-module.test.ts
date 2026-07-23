import { describe, it, expect } from 'vitest'
import { validateOverlayBounds } from './overlay-image-module'

describe('validateOverlayBounds', () => {
  describe('合法 bounds', () => {
    it('中国区域 bounds 通过', () => {
      const r = validateOverlayBounds([73, 15, 137, 59])
      expect(r.ok).toBe(true)
      if (r.ok) expect(r.bounds).toEqual([73, 15, 137, 59])
    })

    it('北京小区域 bounds 通过', () => {
      const r = validateOverlayBounds([116.0, 39.5, 117.0, 40.5])
      expect(r.ok).toBe(true)
    })

    it('欧洲区域 bounds 通过', () => {
      const r = validateOverlayBounds([-10, 35, 30, 70])
      expect(r.ok).toBe(true)
    })

    it('正好 180° 跨度通过（临界值，不跨子午线）', () => {
      const r = validateOverlayBounds([-90, -10, 90, 10])
      expect(r.ok).toBe(true)
    })

    it('全球 bounds 通过', () => {
      const r = validateOverlayBounds([-180, -90, 180, 90])
      expect(r.ok).toBe(true)
    })

    it('西半球负经度 bounds 通过', () => {
      const r = validateOverlayBounds([-125, 25, -65, 49])
      expect(r.ok).toBe(true)
    })
  })

  describe('非法 bounds — 结构异常', () => {
    it('undefined 拒绝', () => {
      const r = validateOverlayBounds(undefined)
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('不是 4 元素数组')
    })

    it('null 拒绝', () => {
      const r = validateOverlayBounds(null)
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('不是 4 元素数组')
    })

    it('3 元素数组拒绝', () => {
      const r = validateOverlayBounds([1, 2, 3])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('不是 4 元素数组')
    })

    it('5 元素数组拒绝', () => {
      const r = validateOverlayBounds([1, 2, 3, 4, 5])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('不是 4 元素数组')
    })

    it('对象拒绝', () => {
      const r = validateOverlayBounds({ west: 1, south: 2, east: 3, north: 4 })
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('不是 4 元素数组')
    })
  })

  describe('非法 bounds — 非有限值', () => {
    it('NaN 拒绝', () => {
      const r = validateOverlayBounds([NaN, 15, 137, 59])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('非有限值')
    })

    it('Infinity 拒绝', () => {
      const r = validateOverlayBounds([73, 15, Infinity, 59])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('非有限值')
    })

    it('-Infinity 拒绝', () => {
      const r = validateOverlayBounds([-Infinity, 15, 137, 59])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('非有限值')
    })

    it('字符串数值拒绝（隐式 NaN）', () => {
      // 数组里混入字符串，Number.isFinite 会拒绝
      const r = validateOverlayBounds([73, 'invalid' as any, 137, 59])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('非有限值')
    })
  })

  describe('非法 bounds — 范围越界', () => {
    it('经度 < -180 拒绝', () => {
      const r = validateOverlayBounds([-181, 15, 137, 59])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('超出 WGS84 范围')
    })

    it('经度 > 180 拒绝', () => {
      const r = validateOverlayBounds([73, 15, 181, 59])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('超出 WGS84 范围')
    })

    it('纬度 < -90 拒绝', () => {
      const r = validateOverlayBounds([73, -91, 137, 59])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('超出 WGS84 范围')
    })

    it('纬度 > 90 拒绝', () => {
      const r = validateOverlayBounds([73, 15, 137, 91])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('超出 WGS84 范围')
    })
  })

  describe('非法 bounds — 顺序错乱', () => {
    it('west >= east 拒绝', () => {
      const r = validateOverlayBounds([137, 15, 73, 59])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('west >= east')
    })

    it('west == east 拒绝（零宽度）', () => {
      const r = validateOverlayBounds([116, 39, 116, 40])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('west >= east')
    })

    it('south >= north 拒绝', () => {
      const r = validateOverlayBounds([73, 59, 137, 15])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('south >= north')
    })

    it('south == north 拒绝（零高度）', () => {
      const r = validateOverlayBounds([116, 39, 117, 39])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('south >= north')
    })
  })

  describe('宽跨度 bounds — image source 可正常渲染', () => {
    it('东西跨度 = 200° 通过（image source 拉伸为单张图）', () => {
      const r = validateOverlayBounds([-100, 15, 100, 59])
      expect(r.ok).toBe(true)
    })

    it('东西跨度 = 181° 通过', () => {
      const r = validateOverlayBounds([-90.5, -10, 90.5, 10])
      expect(r.ok).toBe(true)
    })

    it('真正的跨子午线情况（east < west）仍被 west>=east 拦截', () => {
      // 例如太平洋数据 [170, -10, -170, 10]：east=-170 < west=170
      const r = validateOverlayBounds([170, -10, -170, 10])
      expect(r.ok).toBe(false)
      if (!r.ok) expect(r.reason).toContain('west >= east')
    })
  })

  describe('边界值通过', () => {
    it('东西跨度 = 179.999° 通过', () => {
      const r = validateOverlayBounds([-90, -10, 89.999, 10])
      expect(r.ok).toBe(true)
    })

    it('正好 -180 / 180 经度通过', () => {
      const r = validateOverlayBounds([-180, -10, -90, 10])
      expect(r.ok).toBe(true)
    })

    it('正好 -90 / 90 纬度通过', () => {
      const r = validateOverlayBounds([0, -90, 10, 90])
      expect(r.ok).toBe(true)
    })
  })
})
