export const demoAdministrativeBoundaries = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { name: '珠三角西部' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [111.9, 21.5],
            [113.45, 21.5],
            [113.45, 23.65],
            [111.9, 23.65],
            [111.9, 21.5],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: { name: '广州佛山' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [113.0, 22.75],
            [114.05, 22.75],
            [114.05, 23.65],
            [113.0, 23.65],
            [113.0, 22.75],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: { name: '深圳东莞' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [113.7, 22.35],
            [114.75, 22.35],
            [114.75, 23.35],
            [113.7, 23.35],
            [113.7, 22.35],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: { name: '粤北山区' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [111.9, 23.45],
            [114.75, 23.45],
            [114.75, 25.25],
            [111.9, 25.25],
            [111.9, 23.45],
          ],
        ],
      },
    },
    {
      type: 'Feature',
      properties: { name: '东部沿海' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [114.1, 22.2],
            [115.55, 22.2],
            [115.55, 24.25],
            [114.1, 24.25],
            [114.1, 22.2],
          ],
        ],
      },
    },
  ],
} as const

export const demoProvinceOutline = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { name: '广东研究范围' },
      geometry: {
        type: 'Polygon',
        coordinates: [
          [
            [111.65, 21.2],
            [115.75, 21.2],
            [115.75, 25.45],
            [111.65, 25.45],
            [111.65, 21.2],
          ],
        ],
      },
    },
  ],
} as const
