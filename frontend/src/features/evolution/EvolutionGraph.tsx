import { useEffect, useMemo, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
import { forceCollide, forceSimulation, forceX, forceY, type SimulationNodeDatum } from 'd3-force'
import { useAppStore } from '../../store/appStore'
import { cn } from '../../ui/cn'
import type { EvolutionEdge, EvolutionNode, LooseEdge } from './api'
import { makeExporter, type GraphExporter } from './graphExport'

interface EvolutionGraphProps {
  nodes: EvolutionNode[]
  edges: EvolutionEdge[]
  looseEdges: LooseEdge[]
  selectedId: string | null
  onSelect: (id: string | null) => void
  showCitations: boolean
  /** Receives an exporter while the map is drawn, and null when it is taken down. */
  onExporter?: (exporter: GraphExporter | null) => void
  /** Overrides the box's fixed height, e.g. to fill the screen. */
  className?: string
}

// Graph units. Time runs left to right; each year's column is as wide as its paper count needs
// (square-root scaled, with a minimum), so sparse early decades do not take half the width.
const MIN_YEAR_WIDTH = 24
const WIDTH_PER_SQRT_PAPER = 34
const BAND_HEIGHT = 640

/** Centre x of each year's column, for every year from first to last. */
function yearScale(nodes: EvolutionNode[], firstYear: number, lastYear: number): Map<number, number> {
  const counts = new Map<number, number>()
  for (const n of nodes) if (n.year !== null) counts.set(n.year, (counts.get(n.year) ?? 0) + 1)
  const centres = new Map<number, number>()
  let x = 0
  for (let y = firstYear - 1; y <= lastYear; y++) {
    const width = MIN_YEAR_WIDTH + WIDTH_PER_SQRT_PAPER * Math.sqrt(counts.get(y) ?? 0)
    centres.set(y, x + width / 2)
    x += width
  }
  return centres
}

interface LaidOutNode extends SimulationNodeDatum {
  id: string
  targetX: number
  r: number
  milestone: boolean
}

// How far outside a circle, in screen pixels, the pointer still names its paper.
const HOVER_SLACK = 4

// Milestone labels are 10px; below this zoom they are under 7px on screen and unreadable.
const LABEL_MIN_ZOOM = 0.7

const nodeRadius = (n: EvolutionNode) =>
  n.is_milestone ? 9 + 13 * n.milestone_score : 3 + 5 * n.milestone_score

// Deterministic start position so the same topic always lays out the same way.
function hashUnit(id: string) {
  let h = 2166136261
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619)
  return ((h >>> 0) % 10000) / 10000
}

/** x is pinned to the year; d3-force spreads papers vertically without overlap, milestones near the middle. */
function layout(nodes: EvolutionNode[], firstYear: number, xOf: Map<number, number>): Map<string, { x: number; y: number }> {
  const sim: LaidOutNode[] = nodes.map((n) => {
    const targetX = xOf.get(n.year ?? firstYear - 1) ?? 0
    return {
      id: n.id,
      targetX,
      r: nodeRadius(n),
      milestone: n.is_milestone,
      x: targetX,
      y: (hashUnit(n.id) - 0.5) * BAND_HEIGHT,
    }
  })
  const simulation = forceSimulation(sim)
    .force('x', forceX<LaidOutNode>((d) => d.targetX).strength(0.8))
    .force('y', forceY<LaidOutNode>(0).strength((d) => (d.milestone ? 0.12 : 0.025)))
    .force('collide', forceCollide<LaidOutNode>((d) => d.r + (d.milestone ? 14 : 3)).iterations(2))
    .stop()
  for (let i = 0; i < 300; i++) simulation.tick()
  // Stretch vertically to roughly the canvas's shape; otherwise fitting a long timeline
  // leaves a thin band in a tall box. Scaling y only adds space, so nothing starts overlapping.
  const xs = sim.map((d) => d.x ?? 0)
  const ys = sim.map((d) => d.y ?? 0)
  const width = Math.max(...xs) - Math.min(...xs) || 1
  const height = Math.max(...ys) - Math.min(...ys) || 1
  const stretch = Math.min(6, Math.max(1, (width * 0.6) / height))
  return new Map(sim.map((d) => [d.id, { x: d.x ?? d.targetX, y: (d.y ?? 0) * stretch }]))
}

/** Colours from the current look's CSS variables (gold or indigo). */
function themeColors() {
  const css = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    accent: read('--accent', '#d6ae5f'),
    star: read('--star', '#f6e3b4'),
    path: read('--fg-2', '#a4a5ab'),
    strict: read('--bad', '#e5727a'),
    loose: read('--warn', '#e0965a'),
    seed: read('--warn', '#e0965a'),
    edge: read('--map-line', 'rgba(246, 227, 180, 0.2)'),
    label: read('--fg', '#ececee'),
    surface: read('--map-bg', '#08090c'),
  }
}

/**
 * Papers are stars: milestones shine in the accent and carry labels, the rest are faint points.
 * Selecting one draws its thread: the citations into and out of it light up in the accent.
 */
function graphStyle(showCitations: boolean): cytoscape.StylesheetJson {
  const c = themeColors()
  return [
    {
      selector: 'node',
      style: {
        width: 'data(size)',
        height: 'data(size)',
        'background-color': c.star,
        'background-opacity': 0.55,
        'border-width': 0,
      },
    },
    {
      selector: 'node.milestone',
      style: {
        'background-color': c.accent,
        'background-opacity': 1,
        'border-width': 2,
        'border-color': c.surface,
        label: 'data(label)',
        color: c.label,
        'font-size': 10,
        'font-family': 'Geist, ui-sans-serif, system-ui, sans-serif',
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-wrap': 'wrap',
        'text-max-width': '120px',
        'text-outline-width': 2,
        'text-outline-color': c.surface,
        'min-zoomed-font-size': 7, // hide labels too small to read until the user zooms in
      },
    },
    // The WebGL renderer ignores min-zoomed-font-size, so small labels are also hidden by class.
    { selector: 'node.milestone.quiet', style: { label: '' } },
    { selector: 'node.main-path', style: { 'border-width': 2, 'border-color': c.path } },
    { selector: 'node.seed', style: { 'border-width': 2, 'border-color': c.seed } },
    { selector: 'node.selected', style: { 'border-width': 3, 'border-color': c.label, 'background-color': c.accent, 'background-opacity': 1 } },
    { selector: 'node.thread', style: { 'background-color': c.accent, 'background-opacity': 1 } },
    { selector: 'node.faded', style: { opacity: 0.18 } },
    {
      selector: 'edge',
      style: {
        'curve-style': 'haystack',
        width: 0.6,
        'line-color': c.edge,
        opacity: showCitations ? 0.5 : 0,
      },
    },
    {
      selector: 'edge.main-path',
      style: {
        'curve-style': 'straight',
        width: 1.6,
        'line-color': c.path,
        'target-arrow-shape': 'triangle',
        'target-arrow-color': c.path,
        'arrow-scale': 0.7,
        opacity: 0.55,
      },
    },
    {
      // Strict gap -> resolution link: shown whether or not all citations are.
      selector: 'edge.strict',
      style: {
        'curve-style': 'straight',
        width: 1.6,
        'line-color': c.strict,
        'target-arrow-shape': 'triangle',
        'target-arrow-color': c.strict,
        'arrow-scale': 0.7,
        opacity: 0.8,
      },
    },
    {
      // Loose link: no citation, only a text match between a gap and a later paper; on request.
      // Dashed in exports; the WebGL renderer draws every line solid, so its colour tells it apart.
      selector: 'edge.loose',
      style: {
        'curve-style': 'straight',
        width: 1.3,
        'line-style': 'dashed',
        'line-dash-pattern': [5, 4],
        'line-color': c.loose,
        'target-arrow-shape': 'triangle',
        'target-arrow-color': c.loose,
        'arrow-scale': 0.7,
        opacity: 0.8,
      },
    },
    // Ariadne's thread: the selected paper's citations, drawn in the accent.
    {
      selector: 'edge.thread',
      style: {
        'curve-style': 'straight',
        'line-color': c.accent,
        'target-arrow-shape': 'triangle',
        'target-arrow-color': c.accent,
        'arrow-scale': 0.7,
        width: 1.8,
        opacity: 0.95,
      },
    },
    { selector: 'edge.strict.thread', style: { 'line-color': c.strict, 'target-arrow-color': c.strict, width: 2.4 } },
    // Fading must not bring back citations that are switched off: thousands of faint lines read as haze.
    { selector: 'edge.faded', style: { opacity: showCitations ? 0.03 : 0 } },
    { selector: 'edge.main-path.faded, edge.strict.faded, edge.loose.faded', style: { opacity: 0.03 } },
  ]
}

/**
 * WebGL2 lets the GPU draw the map; without it cytoscape's 2D canvas does, as before.
 * A software WebGL (no usable GPU) is several times slower than the canvas, so it counts as none.
 */
let webglSupport: boolean | undefined
function hasWebgl() {
  webglSupport ??= !!document.createElement('canvas').getContext('webgl2', { failIfMajorPerformanceCaveat: true })
  return webglSupport
}

/** The paper under the pointer, at its on-screen position. */
interface Hovered {
  paper: EvolutionNode
  x: number
  y: number
  r: number
  /** Which side of the node the label sits on, so it stays inside the map's box. */
  below: boolean
  align: 'left' | 'center' | 'right'
}

/** "A, B, C et al.": nodes carry the first three authors and the full count. */
function authorLine(paper: EvolutionNode) {
  const names = paper.authors.join(', ')
  return paper.author_count > paper.authors.length ? `${names} et al.` : names
}

export function EvolutionGraph({ nodes, edges, looseEdges, selectedId, onSelect, showCitations, onExporter, className }: EvolutionGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const onSelectRef = useRef(onSelect)
  const onExporterRef = useRef(onExporter)
  const accent = useAppStore((s) => s.accent)
  const [ticks, setTicks] = useState<{ year: number; x: number }[]>([])
  const [hovered, setHovered] = useState<Hovered | null>(null)

  useEffect(() => {
    onSelectRef.current = onSelect
    onExporterRef.current = onExporter
  }, [onSelect, onExporter])

  const years = useMemo(() => nodes.map((n) => n.year).filter((y): y is number => y !== null), [nodes])
  const firstYear = years.length ? Math.min(...years) : 2000
  const lastYear = years.length ? Math.max(...years) : 2000

  // Build the graph whenever the data changes.
  useEffect(() => {
    if (!containerRef.current) return
    const xOf = yearScale(nodes, firstYear, lastYear)
    const positions = layout(nodes, firstYear, xOf)
    const shown = new Set(nodes.map((n) => n.id))
    const elements: cytoscape.ElementDefinition[] = [
      ...nodes.map((n) => ({
        group: 'nodes' as const,
        data: { id: n.id, label: n.named_method ?? n.title, size: 2 * nodeRadius(n) },
        position: positions.get(n.id),
        classes: [n.is_milestone && 'milestone', n.on_main_path && 'main-path', n.role === 'seed' && 'seed']
          .filter(Boolean)
          .join(' '),
      })),
      // Drawn older -> newer, so arrows follow time: the cited paper flows into the one citing it.
      ...edges
        .filter((e) => shown.has(e.source) && shown.has(e.target))
        .map((e) => ({
          group: 'edges' as const,
          data: { id: `${e.target}->${e.source}`, source: e.target, target: e.source },
          classes: [e.main_path && 'main-path', e.strict && 'strict'].filter(Boolean).join(' '),
        })),
      ...looseEdges
        .filter((e) => shown.has(e.source) && shown.has(e.target))
        .map((e) => ({
          group: 'edges' as const,
          data: { id: `loose:${e.target}->${e.source}`, source: e.target, target: e.source },
          classes: 'loose',
        })),
    ]
    // The WebGL renderer reads the container's inline background: arrowheads are blended over it.
    containerRef.current.style.backgroundColor = themeColors().surface
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      layout: { name: 'preset' },
      style: graphStyle(showCitations),
      minZoom: 0.15,
      maxZoom: 3,
      autoungrabify: true,
      webgl: hasWebgl(),
    })
    // Open on the milestones; the whole corpus is one zoom-out away.
    const milestones = cy.nodes('.milestone')
    cy.fit(milestones.nonempty() ? milestones : undefined, 50)
    // The paper under the pointer is found here rather than by cytoscape's mouseover: its WebGL picking
    // often answers with an edge drawn over a node, or misses circles a pixel or two wide when zoomed out.
    const placed = nodes.map((n) => ({ paper: n, ...positions.get(n.id)!, r: nodeRadius(n) }))
    const paperAt = (sx: number, sy: number) => {
      const zoom = cy.zoom()
      const pan = cy.pan()
      const mx = (sx - pan.x) / zoom
      const my = (sy - pan.y) / zoom
      let best: (typeof placed)[number] | null = null
      let bestGap = HOVER_SLACK
      for (const p of placed) {
        // Screen pixels between the pointer and the circle's edge; inside the circle counts as 0.
        const gap = Math.max(0, Math.hypot(p.x - mx, p.y - my) * zoom - p.r * zoom)
        if (gap < bestGap || (gap === bestGap && best && p.r < best.r)) {
          best = p
          bestGap = gap
        }
      }
      return best
    }
    let pointer: { x: number; y: number } | null = null
    let hoveredId: string | null = null
    let hoverFrame = 0
    const updateHover = () => {
      cancelAnimationFrame(hoverFrame)
      hoverFrame = requestAnimationFrame(() => {
        const hit = pointer && paperAt(pointer.x, pointer.y)
        const box = containerRef.current
        if (!box) return
        box.style.cursor = hit ? 'pointer' : ''
        if (!hit) {
          if (hoveredId !== null) setHovered(null)
          hoveredId = null
          return
        }
        const zoom = cy.zoom()
        const pan = cy.pan()
        const x = hit.x * zoom + pan.x
        const y = hit.y * zoom + pan.y
        hoveredId = hit.paper.id
        setHovered({
          paper: hit.paper,
          x,
          y,
          r: hit.r * zoom,
          below: y < 110, // room above for the card's three lines
          align: x < 175 ? 'left' : x > box.clientWidth - 175 ? 'right' : 'center',
        })
      })
    }
    const box = containerRef.current
    const onMove = (e: MouseEvent) => {
      const rect = box.getBoundingClientRect()
      pointer = { x: e.clientX - rect.left, y: e.clientY - rect.top }
      updateHover()
    }
    const onLeave = () => {
      pointer = null
      updateHover()
    }
    box.addEventListener('mousemove', onMove)
    box.addEventListener('mouseleave', onLeave)
    // A click picks the same paper the card names, so a tiny circle can be selected too.
    cy.on('tap', (evt) => {
      const onNode = evt.target !== cy && evt.target.isNode()
      onSelectRef.current(onNode ? evt.target.id() : paperAt(evt.renderedPosition.x, evt.renderedPosition.y)?.paper.id ?? null)
    })

    // Year axis: model x -> screen x follows pan and zoom.
    let frame = 0
    const updateAxis = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => {
        const zoom = cy.zoom()
        const panX = cy.pan().x
        // Keep labels about 40px apart on screen, skipping years where columns are narrow.
        const next: { year: number; x: number }[] = []
        for (let y = firstYear; y <= lastYear; y++) {
          const x = (xOf.get(y) ?? 0) * zoom + panX
          if (!next.length || x - next[next.length - 1].x >= 40) next.push({ year: y, x })
        }
        setTicks(next)
      })
    }
    cy.on('viewport', updateAxis)
    let quiet: boolean | null = null
    const updateLabels = () => {
      const next = cy.zoom() < LABEL_MIN_ZOOM
      if (next !== quiet) cy.nodes('.milestone').toggleClass('quiet', (quiet = next))
    }
    cy.on('viewport', updateLabels)
    updateLabels()
    cy.on('viewport', updateHover) // the card follows its paper while the map pans and zooms
    updateAxis()
    // Going full screen resizes the box; cytoscape only notices window resizes by itself.
    const resize = new ResizeObserver(() => cy.resize())
    resize.observe(containerRef.current)
    cyRef.current = cy
    onExporterRef.current?.(makeExporter(cy, xOf, firstYear, lastYear))
    return () => {
      cancelAnimationFrame(frame)
      cancelAnimationFrame(hoverFrame)
      box.removeEventListener('mousemove', onMove)
      box.removeEventListener('mouseleave', onLeave)
      resize.disconnect()
      onExporterRef.current?.(null)
      setHovered(null)
      cy.destroy()
      cyRef.current = null
    }
    // Rebuild only when the data changes; style and selection are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges, looseEdges, firstYear, lastYear])

  // Re-colour when the look changes or citations are toggled.
  useEffect(() => {
    cyRef.current?.style(graphStyle(showCitations))
  }, [accent, showCitations, nodes])

  // Draw the selected paper's thread: its citations in and out light up, oldest first; the rest fades.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().stop(true, false)
    cy.elements().removeClass('selected thread faded').removeStyle('opacity')
    if (!selectedId) return
    const node = cy.getElementById(selectedId)
    if (node.empty()) return
    const neighbourhood = node.closedNeighborhood()
    cy.elements().not(neighbourhood).addClass('faded')
    node.addClass('selected')
    neighbourhood.nodes().not(node).addClass('thread')
    const thread = node.connectedEdges().addClass('thread')
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!reduced) {
      const year = (id: string) => nodes.find((n) => n.id === id)?.year ?? 0
      thread
        .sort((a, b) => year(a.source().id()) - year(b.source().id()))
        .forEach((edge, i) => {
          edge.style('opacity', 0)
          edge.delay(Math.min(i * 35, 900)).animate({ style: { opacity: 0.95 } }, { duration: 260 })
        })
    }
    cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 0.9) }, { duration: 300 })
  }, [selectedId, nodes])

  return (
    <div className={cn('relative h-[620px] w-full overflow-hidden rounded-xl border border-line', className)} style={{ background: 'var(--map-bg)' }}>
      {/* Explicit size: an absolutely positioned container collapsed to zero height once cytoscape took it over. */}
      <div ref={containerRef} className="relative h-full w-full" aria-label="Lineage map of the topic, oldest papers on the left" />
      {hovered && (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 grid w-max max-w-[340px] gap-0.5 rounded-md border border-line-strong bg-surface-2 px-2.5 py-1.5 text-[12px] leading-snug shadow-lg"
          style={{
            left: hovered.x,
            top: hovered.below ? hovered.y + hovered.r + 6 : hovered.y - hovered.r - 6,
            transform: `translate(${{ left: '-12px', center: '-50%', right: 'calc(-100% + 12px)' }[hovered.align]}, ${hovered.below ? '0' : '-100%'})`,
          }}
        >
          <span className="font-medium text-fg">{hovered.paper.title}</span>
          {hovered.paper.authors.length > 0 && <span className="text-fg-2">{authorLine(hovered.paper)}</span>}
          {(hovered.paper.venue || hovered.paper.year !== null) && (
            // Some venue names run to four lines ("IEEE Computer Society Conference on ..."): one line, then cut.
            <span className="flex min-w-0 gap-1 text-[11.5px] text-fg-3">
              {hovered.paper.venue && <span className="truncate">{hovered.paper.venue}</span>}
              {hovered.paper.venue && hovered.paper.year !== null && <span aria-hidden="true">·</span>}
              {hovered.paper.year !== null && <span className="shrink-0 tabular-nums">{hovered.paper.year}</span>}
            </span>
          )}
        </div>
      )}
      <div className="pointer-events-none absolute right-0 bottom-0 left-0 h-7 border-t border-line" style={{ background: 'color-mix(in srgb, var(--map-bg) 85%, transparent)' }}>
        {ticks.map((t) => (
          <span key={t.year} className="absolute top-1.5 -translate-x-1/2 font-mono text-[10px] text-fg-3 tabular-nums" style={{ left: t.x }}>
            {t.year}
          </span>
        ))}
      </div>
    </div>
  )
}
