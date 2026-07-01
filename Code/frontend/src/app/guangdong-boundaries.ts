import GuangdongGeoJSON from '@datapool/guangdong.geojson'

type BoundaryFeature = (typeof GuangdongGeoJSON.features)[number]

export const guangdongCityBoundaries = GuangdongGeoJSON

export const guangdongCityCenters = {
  type: 'FeatureCollection',
  features: GuangdongGeoJSON.features.map((feature: BoundaryFeature) => ({
    type: 'Feature' as const,
    properties: {
      name: feature.properties.name,
      adcode: feature.properties.adcode,
    },
    geometry: {
      type: 'Point' as const,
      coordinates: feature.properties.centroid ?? feature.properties.center ?? [113.2644, 23.1291],
    },
  })),
}
