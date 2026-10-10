import { useEffect, useMemo, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
import { forceCollide, forceSimulation, forceX, forceY, type SimulationNodeDatum } from 'd3-force'
import { useAppStore } from '../../store/appStore'
import type { EvolutionEdge, EvolutionNode } from './api'

interface EvolutionGraphProps {
  nodes: EvolutionNode[]
  edges: EvolutionEdge[]
  selectedId: string | null
  onSelect: (id: string | null) => void
  showCitations: boolean
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

function themeColors() {
  const css = getComputedStyle(document.documentElement)
  const read = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    milestone: read('--color-accent-primary', '#4c5fff'),
    path: read('--color-accent-tertiary', '#38c5d4'),
    seed: read('--color-accent-warning', '#e0a94b'),
    node: read('--text-muted', 'rgba(120, 135, 185, 0.55)'),
    edge: read('--text-ghost', 'rgba(90, 105, 160, 0.40)'),
    label: read('--text-primary', 'rgba(235, 238, 255, 0.95)'),
    surface: read('--color-void', '#060917'),
  }
}

function graphStyle(showCitations: boolean): cytoscape.StylesheetJson {
  const c = themeColors()
  return [
    {
      selector: 'node',
      style: {
        width: 'data(size)',
        height: 'data(size)',
        'background-color': c.node,
        'border-width': 0,
      },
    },
    {
      selector: 'node.milestone',
      style: {
        'background-color': c.milestone,
        'border-width': 2,
        'border-color': c.surface,
        label: 'data(label)',
        color: c.label,
        'font-size': 10,
        'font-family': 'DM Sans, sans-serif',
        'text-valign': 'bottom',
        'text-margin-y': 4,
        'text-wrap': 'wrap',
        'text-max-width': '120px',
        'text-outline-width': 2,
        'text-outline-color': c.surface,
        'min-zoomed-font-size': 7, // hide labels too small to read until the user zooms in
      },
    },
    { selector: 'node.main-path', style: { 'border-width': 3, 'border-color': c.path } },
    { selector: 'node.seed', style: { 'border-width': 3, 'border-color': c.seed } },
    { selector: 'node.selected', style: { 'border-width': 4, 'border-color': c.label } },
    { selector: 'node.faded', style: { opacity: 0.15 } },
    {
      selector: 'edge',
      style: {
        'curve-style': 'haystack',
        width: 0.6,
        'line-color': c.edge,
        opacity: showCitations ? 0.35 : 0,
      },
    },
    {
      selector: 'edge.main-path',
      style: {
        'curve-style': 'straight',
        width: 2.5,
        'line-color': c.path,
        'target-arrow-shape': 'triangle',
        'target-arrow-color': c.path,
        'arrow-scale': 0.8,
        opacity: 0.9,
      },
    },
    { selector: 'edge.highlighted', style: { 'line-color': c.milestone, width: 1.5, opacity: 0.85 } },
    { selector: 'edge.faded', style: { opacity: 0.03 } },
  ]
}

export function EvolutionGraph({ nodes, edges, selectedId, onSelect, showCitations }: EvolutionGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const onSelectRef = useRef(onSelect)
  const theme = useAppStore((s) => s.theme)
  const [ticks, setTicks] = useState<{ year: number; x: number }[]>([])

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

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
          classes: e.main_path ? 'main-path' : '',
        })),
    ]
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      layout: { name: 'preset' },
      style: graphStyle(showCitations),
      minZoom: 0.15,
      maxZoom: 3,
      autoungrabify: true,
    })
    // Open on the milestones; the whole corpus is one zoom-out away.
    const milestones = cy.nodes('.milestone')
    cy.fit(milestones.nonempty() ? milestones : undefined, 50)
    cy.on('tap', 'node', (evt) => onSelectRef.current(evt.target.id()))
    cy.on('tap', (evt) => {
      if (evt.target === cy) onSelectRef.current(null)
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
    updateAxis()
    cyRef.current = cy
    return () => {
      cancelAnimationFrame(frame)
      cy.destroy()
      cyRef.current = null
    }
    // Rebuild only when the data changes; style and selection are applied below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, edges, firstYear, lastYear])

  // Re-colour on theme change or when citations are toggled.
  useEffect(() => {
    cyRef.current?.style(graphStyle(showCitations))
  }, [theme, showCitations, nodes])

  // Highlight the selected paper and its neighbours, and bring it into view.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.elements().removeClass('selected highlighted faded')
    if (!selectedId) return
    const node = cy.getElementById(selectedId)
    if (node.empty()) return
    const neighbourhood = node.closedNeighborhood()
    cy.elements().not(neighbourhood).addClass('faded')
    node.addClass('selected')
    node.connectedEdges().addClass('highlighted')
    cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 0.9) }, { duration: 300 })
  }, [selectedId, nodes])

  return (
    <div className="relative w-full h-[620px] rounded-xl border border-border-subtle bg-glass-fill overflow-hidden">
      {/* Explicit size: an absolutely positioned container collapsed to zero height once cytoscape took it over. */}
      <div ref={containerRef} className="w-full h-full" aria-label="Citation graph of the topic, oldest papers on the left" />
      <div className="absolute left-0 right-0 bottom-0 h-7 border-t border-border-subtle bg-glass-fill pointer-events-none">
        {ticks.map((t) => (
          <span
            key={t.year}
            className="absolute top-1.5 -translate-x-1/2 text-[10px] font-mono text-text-muted tabular-nums"
            style={{ left: t.x }}
          >
            {t.year}
          </span>
        ))}
      </div>
    </div>
  )
}
