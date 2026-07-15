/**
 * Minimal GeoJSON namespace used by import / MapLibre helper modules.
 * Avoids adding @types/geojson under the current TypeScript peer constraints.
 */
declare namespace GeoJSON {
  type Position = number[]

  interface Point {
    type: 'Point'
    coordinates: Position
    bbox?: number[]
  }

  interface MultiPoint {
    type: 'MultiPoint'
    coordinates: Position[]
    bbox?: number[]
  }

  interface LineString {
    type: 'LineString'
    coordinates: Position[]
    bbox?: number[]
  }

  interface MultiLineString {
    type: 'MultiLineString'
    coordinates: Position[][]
    bbox?: number[]
  }

  interface Polygon {
    type: 'Polygon'
    coordinates: Position[][]
    bbox?: number[]
  }

  interface MultiPolygon {
    type: 'MultiPolygon'
    coordinates: Position[][][]
    bbox?: number[]
  }

  interface GeometryCollection {
    type: 'GeometryCollection'
    geometries: Geometry[]
    bbox?: number[]
  }

  type Geometry =
    | Point
    | MultiPoint
    | LineString
    | MultiLineString
    | Polygon
    | MultiPolygon
    | GeometryCollection

  interface Feature<G extends Geometry | null = Geometry, P = Record<string, unknown> | null> {
    type: 'Feature'
    geometry: G
    properties: P
    id?: string | number
    bbox?: number[]
  }

  interface FeatureCollection<G extends Geometry | null = Geometry, P = Record<string, unknown> | null> {
    type: 'FeatureCollection'
    features: Array<Feature<G, P>>
    bbox?: number[]
  }
}
