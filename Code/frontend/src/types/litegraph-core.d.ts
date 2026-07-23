declare module 'litegraph.js/build/litegraph.core.js' {
  import type {
    LiteGraph as LiteGraphStatic,
    LGraph as LGraphClass,
    LGraphCanvas as LGraphCanvasClass,
    LGraphNode as LGraphNodeClass,
    LLink as LLinkClass,
  } from 'litegraph.js'

  export const LiteGraph: typeof LiteGraphStatic
  export const LGraph: typeof LGraphClass
  export const LGraphCanvas: typeof LGraphCanvasClass
  export const LGraphNode: typeof LGraphNodeClass
  export const LLink: typeof LLinkClass
}
