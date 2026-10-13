declare module 'cytoscape-svg' {
  import type cytoscape from 'cytoscape'
  const extension: cytoscape.Ext
  export default extension
}

declare namespace cytoscape {
  interface Core {
    /** From cytoscape-svg: the graph as an SVG document. */
    svg(options?: { full?: boolean; scale?: number; bg?: string }): string
  }
}
