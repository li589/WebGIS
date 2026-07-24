declare module 'shpjs' {
  const shpjs: {
    (
      input: ArrayBuffer | Uint8Array | Buffer | string,
    ): Promise<GeoJSON.FeatureCollection | GeoJSON.FeatureCollection[]>
  }
  export default shpjs
}

declare module 'proj4' {
  interface Proj4Projection {
    forward(
      point: [number, number] | { x: number; y: number },
    ): [number, number] | { x: number; y: number }
    inverse(
      point: [number, number] | { x: number; y: number },
    ): [number, number] | { x: number; y: number }
  }
  const proj4: {
    (from: string, to: string, point: [number, number]): [number, number]
    defs(name: string, def: string): void
    defs(name: string): Proj4Projection | undefined
  }
  export default proj4
}
