declare module '@datapool/guangdong.geojson' {
  interface GuangdongBoundaryFeature {
    type: 'Feature'
    properties: {
      adcode: number
      name: string
      center?: [number, number]
      centroid?: [number, number]
      level?: string
    }
    geometry: {
      type: 'Polygon' | 'MultiPolygon'
      coordinates: unknown
    }
  }

  interface GuangdongBoundaryFeatureCollection {
    type: 'FeatureCollection'
    features: GuangdongBoundaryFeature[]
  }

  const GuangdongGeoJSON: GuangdongBoundaryFeatureCollection
  export default GuangdongGeoJSON
}
