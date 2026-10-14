import cytoscape from 'cytoscape'

/** Saves the map as an image; the graph component hands one out while the map is on screen. */
export interface GraphExporter {
  png: () => Promise<Blob>
  svg: () => Promise<Blob>
}

let svgLoaded: Promise<void> | null = null

/** The SVG extension, loaded on the first SVG export so the map page does not carry it. */
function loadSvg() {
  svgLoaded ??= import('cytoscape-svg').then((m) => {
    cytoscape.use(m.default)
  })
  return svgLoaded
}

const AXIS = 28 // px of year axis under the graph, at scale 1
const TICK_GAP = 40 // px between year labels, at scale 1

function colours() {
  const css = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return { bg: read('--map-bg', '#08090c'), text: read('--fg-3', '#767168'), line: read('--line', '#26272b') }
}

/** Year labels for an export: model x -> image x, about TICK_GAP apart. */
function ticks(cy: cytoscape.Core, xOf: Map<number, number>, firstYear: number, lastYear: number, scale: number, width: number) {
  const bb = cy.elements().boundingBox()
  const out: { year: number; x: number }[] = []
  for (let y = firstYear; y <= lastYear; y++) {
    const x = ((xOf.get(y) ?? 0) - bb.x1) * scale
    if (x < 0 || x > width) continue
    if (!out.length || x - out[out.length - 1].x >= TICK_GAP * scale) out.push({ year: y, x })
  }
  return out
}

/** The whole map (not just the view) at twice the size, with the year axis drawn under it. */
export function makeExporter(cy: cytoscape.Core, xOf: Map<number, number>, firstYear: number, lastYear: number): GraphExporter {
  return {
    png: async () => {
      const scale = 2
      const c = colours()
      const graph = await createImageBitmap(await cy.png({ full: true, scale, bg: c.bg, output: 'blob-promise' }))
      const canvas = document.createElement('canvas')
      canvas.width = graph.width
      canvas.height = graph.height + AXIS * scale
      const ctx = canvas.getContext('2d')!
      ctx.fillStyle = c.bg
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(graph, 0, 0)
      ctx.fillStyle = c.line
      ctx.fillRect(0, graph.height, canvas.width, scale)
      ctx.fillStyle = c.text
      ctx.font = `${10 * scale}px ui-monospace, monospace`
      ctx.textAlign = 'center'
      for (const t of ticks(cy, xOf, firstYear, lastYear, scale, canvas.width)) ctx.fillText(String(t.year), t.x, graph.height + 18 * scale)
      return new Promise<Blob>((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('The image could not be made'))), 'image/png'))
    },
    svg: async () => {
      await loadSvg()
      const c = colours()
      const doc = new DOMParser().parseFromString(cy.svg({ full: true, scale: 1, bg: c.bg }), 'image/svg+xml')
      const root = doc.documentElement
      const width = parseFloat(root.getAttribute('width') ?? '0')
      const height = parseFloat(root.getAttribute('height') ?? '0')
      root.setAttribute('height', String(height + AXIS))
      if (root.getAttribute('viewBox')) root.setAttribute('viewBox', `0 0 ${width} ${height + AXIS}`)
      const ns = 'http://www.w3.org/2000/svg'
      const band = doc.createElementNS(ns, 'rect')
      Object.entries({ x: 0, y: height, width, height: AXIS, fill: c.bg }).forEach(([k, v]) => band.setAttribute(k, String(v)))
      root.appendChild(band)
      for (const t of ticks(cy, xOf, firstYear, lastYear, 1, width)) {
        const label = doc.createElementNS(ns, 'text')
        Object.entries({ x: t.x, y: height + 18, fill: c.text, 'font-size': 10, 'font-family': 'ui-monospace, monospace', 'text-anchor': 'middle' })
          .forEach(([k, v]) => label.setAttribute(k, String(v)))
        label.textContent = String(t.year)
        root.appendChild(label)
      }
      return new Blob([new XMLSerializer().serializeToString(doc)], { type: 'image/svg+xml' })
    },
  }
}

export { saveBlob } from '../../api/download'
