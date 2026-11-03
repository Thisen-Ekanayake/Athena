import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockApi, renderWithProviders } from '../../test/utils'
import type { EvolutionTopic, TopicGaps } from './api'
import { GapsView } from './GapsView'

const topic: EvolutionTopic = {
  id: 't1', slug: 'vln', name: 'Vision-and-language navigation', aliases: [], description: null,
  status: 'ready', status_detail: null, built_at: '2026-11-02T00:00:00Z', origin: 'search', query: null, build_stats: {},
}

const gaps = (extra: Partial<TopicGaps>): TopicGaps => ({ topic, latest_year: 2026, themes: [], loose_min_score: 0.6, ...extra })

const show = (data: TopicGaps) => {
  mockApi({ 'GET /evolution/topics/vln/gaps': { data } })
  renderWithProviders(<GapsView slug="vln" onSelect={() => {}} />)
}

describe('GapsView', () => {
  it('says the open problems are not read yet, rather than that there are none', async () => {
    show(gaps({ progress: null }))
    expect(await screen.findByText('Open problems are not read yet')).toBeInTheDocument()
  })

  it('shows how far the GPU has got, the time left and what it waits for', async () => {
    show(gaps({
      progress: { stage: 'labelling', label: 'Labelling citing sentences', done: 340, total: 1200, started: 1, updated: 2, eta_seconds: 1500, note: null },
      waiting: { reason: 'turn', detail: 'qwen3-embedding-8b has the GPU', since: 1 },
    }))
    expect(await screen.findByText('Reading the open problems')).toBeInTheDocument()
    expect(screen.getByText(/Labelling citing sentences/)).toHaveTextContent('340 / 1,200')
    expect(screen.getByText(/about 25 min left/)).toBeInTheDocument()
    expect(screen.getByText(/waiting for the GPU \(qwen3-embedding-8b has the GPU\)/)).toBeInTheDocument()
  })

  it('says why the PDFs were not read', async () => {
    show(gaps({
      progress: { stage: 'labelling', label: 'Labelling citing sentences', done: 0, total: 0, started: 1, updated: 2, eta_seconds: null,
        note: 'The PDFs were not read: GROBID is not reachable at http://localhost:8070.' },
    }))
    expect(await screen.findByText(/GROBID is not reachable/)).toBeInTheDocument()
  })
})
