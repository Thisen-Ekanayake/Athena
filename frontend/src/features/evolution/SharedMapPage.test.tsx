import { screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { mockApi, renderWithProviders } from '../../test/utils'
import type { EvolutionNode, EvolutionTopic } from './api'
import { SharedMapPage } from './SharedMapPage'

// The lineage map draws with WebGL and d3-force, which jsdom has neither of; the page around it is under test.
vi.mock('./EvolutionGraph', () => ({
  EvolutionGraph: ({ nodes }: { nodes: EvolutionNode[] }) => <div data-testid="graph">{nodes.length} stars</div>,
}))

const topic: EvolutionTopic = {
  id: 't1', slug: 'diffusion-models', name: 'Diffusion models', aliases: [], description: 'From score matching to latent diffusion.',
  status: 'ready', status_detail: null, built_at: '2026-10-10T00:00:00Z', origin: 'curated', query: null, build_stats: {},
}

const node = (id: string, title: string, year: number, milestone: boolean): EvolutionNode => ({
  id, openalex_id: `W${id}`, title, year, year_source: 'openalex', authors: ['A. Author'], author_count: 1, venue: null, cited_by_count: 100,
  kind: 'method', role: 'core', named_method: null, in_degree: 3, pagerank: 0.1, citation_percentile: 0.9, specificity: 0.5,
  on_main_path: milestone, milestone_score: milestone ? 0.9 : 0.2, score_detail: {}, is_milestone: milestone,
  is_milestone_auto: milestone, milestone_override: null, override_note: null, full_text_status: 'parsed',
  url: `https://openalex.org/W${id}`,
})

const ddpm = node('p1', 'Denoising diffusion probabilistic models', 2020, true)
const ldm = node('p2', 'High-resolution image synthesis with latent diffusion models', 2022, false)

const open = (token: string) => renderWithProviders(<SharedMapPage />, { route: `/share/${token}`, path: '/share/:token' })

describe('SharedMapPage', () => {
  it('shows the map read-only, without the parts that need an account', async () => {
    const calls = mockApi({
      'GET /share/good-token': { data: topic },
      'GET /share/good-token/graph': {
        data: { topic, nodes: [ddpm, ldm], edges: [], loose_edges: [], total_papers: 2, strict_links: 0, year_range: [2020, 2022] },
      },
      'GET /share/good-token/timeline': { data: { topic, years: [{ year: 2020, papers: [ddpm] }], without_full_text: [] } },
      'POST /share/good-token/view': { data: {} },
    })
    open('good-token')

    expect(await screen.findByRole('heading', { name: 'Diffusion models' })).toBeInTheDocument()
    expect(screen.getByText('Shared map · read only')).toBeInTheDocument()
    expect(screen.getByTestId('graph')).toHaveTextContent('2 stars')
    expect(screen.getByRole('button', { name: /Denoising diffusion probabilistic models/ })).toBeInTheDocument()

    const tabs = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(tabs).toEqual(['Lineage map', 'Reading path', 'Open problems', 'People', 'Changes'])
    expect(screen.queryByRole('button', { name: /Follow/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Share/ })).not.toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST')).toEqual([expect.objectContaining({ url: '/share/good-token/view' })])
  })

  it('explains a link that no longer opens a map, and counts the visit once', async () => {
    const calls = mockApi({ 'GET /share/dead-token': { status: 404, data: { detail: 'Not found' } } })
    open('dead-token').unmount()
    open('dead-token')  // mounted again, as React does twice in development

    expect(await screen.findByText('This link no longer opens a map')).toBeInTheDocument()
    expect(calls.filter((c) => c.url === '/share/dead-token/view')).toHaveLength(1)
    expect(calls.filter((c) => c.url === '/share/dead-token')).toHaveLength(1)  // a dead link isn't retried
  })
})
