import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { ConfEdition, ConfPaperBrief, ConferenceList } from '../../api/queries/conferences'
import { usePanelStore } from '../../store/panelStore'
import { mockApi, renderWithProviders, type ApiRoutes, type Call } from '../../test/utils'
import { ConferencePage } from './ConferencePage'
import { ConferencesTab } from './ConferencesTab'

const topics = [
  { id: 1, name: 'LLM agents and tool use', description: '', position: 0 },
  { id: 2, name: 'Machine translation', description: '', position: 1 },
  { id: 3, name: 'Reasoning', description: '', position: 2 },
]

const venue = (slug: string, name: string, years: number[]) => ({
  slug, name, full_name: `${name} conference`, journal: false, years: [...years].reverse(),
  editions: years.map((year) => ({ year, papers: 100 })), latest: Math.max(...years), latest_papers: 100,
  latest_kinds: { main: 60, findings: 40 }, papers: 100 * years.length,
})

const list: ConferenceList = {
  family: { slug: 'all', name: 'ACL family', editions: [{ year: 2025, papers: 300 }, { year: 2026, papers: 400 }] },
  venues: [venue('acl', 'ACL', [2025, 2026]), venue('emnlp', 'EMNLP', [2025, 2026]), venue('eacl', 'EACL', [2025])],
  topics, progress: { papers: 700, sorted: 700, cited: 700, abstracts: 690 }, status: { stage: 'idle' },
}

const paper = (id: string, title: string, extra: Partial<ConfPaperBrief> = {}): ConfPaperBrief => ({
  id, title, year: 2026, authors: ['Ada Lovelace', 'Alan Turing'], author_count: 3, awards: [], award_rank: null,
  citation_count: 12, kind: 'main', topic: { id: 1, name: 'LLM agents and tool use' },
  url: `https://aclanthology.org/${id}/`, pdf_url: `https://aclanthology.org/${id}.pdf`, item_id: null, ...extra,
})

const edition: ConfEdition = {
  venue: 'acl', name: 'ACL', year: 2026, previous_year: 2025, kinds: ['main', 'findings', 'journal'],
  years: [{ year: 2025, papers: 300 }, { year: 2026, papers: 400 }], papers: 400, by_kind: { main: 250, findings: 150 },
  topics: [
    { id: 1, name: 'LLM agents and tool use', papers: 60, share: 0.15, prev_papers: 30, prev_share: 0.1, change: 0.05 },
    { id: 2, name: 'Machine translation', papers: 8, share: 0.02, prev_papers: 15, prev_share: 0.05, change: -0.03 },
    { id: 3, name: 'Reasoning', papers: 0, share: 0, prev_papers: 0, prev_share: 0, change: 0 },
  ],
  awards: [paper('2026.acl-long.1', 'OctoTools', { awards: ['Best Paper Award'], award_rank: 0 })],
  terms: { rising: [{ term: 'agentic', papers: 40, share: 0.1, prev_share: 0.01, score: 9 }], falling: [] },
  summary: { text: 'ACL 2026 moved toward agents.', written_at: '2026-11-07T10:00:00Z', model: 'qwen3.5-9b' },
  progress: { papers: 400, sorted: 400, cited: 400, abstracts: 400 },
}

function page(route = '/library/conferences/acl', extra: ApiRoutes = {}): Call[] {
  const calls = mockApi({
    'GET /conferences': { data: list },
    'GET /conferences/acl': { data: edition },
    'GET /conferences/acl/papers': ({ params }) => ({ data: {
      name: 'ACL', total: 2, offset: 0, topic: null,
      papers: params.topic === 2 ? [paper('2026.acl-long.9', 'A translation paper')] : [paper('2026.acl-long.1', 'OctoTools'), paper('2026.acl-long.2', 'Agents at scale')],
    } }),
    'GET /conferences/acl/trends': { data: { venue: 'acl', name: 'ACL', topics, years: [
      { year: 2025, papers: 300, sorted: 300, topics: { 1: 30, 2: 15, 3: 3 } },
      { year: 2026, papers: 400, sorted: 400, topics: { 1: 60, 2: 8, 3: 20 } },
    ] } },
    'GET /conferences/compare': ({ params }) => ({ data: {
      year: params.year, topics, missing: [],
      venues: String(params.venues).split(',').map((v) => ({ venue: v, name: v.toUpperCase(), papers: 200, sorted: 200, topics: { 1: v === 'acl' ? 40 : 20 } })),
    } }),
    ...extra,
  })
  renderWithProviders(<ConferencePage />, { route, path: '/library/conferences/:venue' })
  return calls
}

describe('ConferencePage', () => {
  it('shows an edition: summary, topic shares with their change, rising terms and award winners', async () => {
    page()
    expect(await screen.findByText('ACL 2026 moved toward agents.')).toBeInTheDocument()
    const topicsCard = screen.getByText('Topics').closest('section')!
    expect(within(topicsCard).getByText('15.0%')).toBeInTheDocument()
    expect(within(topicsCard).getByText('5.0')).toBeInTheDocument()  // up 5 points
    expect(within(topicsCard).queryByText('Reasoning')).not.toBeInTheDocument()  // no papers this edition
    expect(screen.getByText('agentic')).toBeInTheDocument()
    expect(screen.getAllByText('Best Paper Award').length).toBeGreaterThan(0)
  })

  it('opens a topic\'s top papers', async () => {
    const calls = page()
    await userEvent.click(await screen.findByRole('button', { name: /Machine translation/ }))
    expect(await screen.findByText('A translation paper')).toBeInTheDocument()
    expect(calls.filter((c) => c.url === '/conferences/acl/papers').at(-1)?.params).toMatchObject({ year: 2026, topic: 2 })
  })

  it('counts only the kinds of papers picked', async () => {
    const calls = page()
    await screen.findByText('ACL 2026 moved toward agents.')
    await userEvent.click(screen.getByRole('button', { name: 'Findings' }))
    await waitFor(() => expect(calls.filter((c) => c.url === '/conferences/acl').at(-1)?.params).toMatchObject({ kinds: 'main,journal' }))
  })

  it('draws the biggest topics over the years and adds one picked', async () => {
    page('/library/conferences/acl?view=trends')
    const legend = await screen.findByRole('list', { name: 'Legend' })
    expect(within(legend).getAllByRole('listitem').map((li) => li.textContent)).toEqual(
      ['LLM agents and tool use', 'Reasoning', 'Machine translation'])
    expect(screen.getByText('Grew most, 2025–2026')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Reasoning', pressed: true }))
    expect(within(legend).getAllByRole('listitem')).toHaveLength(2)
  })

  it('compares venues in a year', async () => {
    const calls = page('/library/conferences/acl?view=compare')
    const table = await screen.findByRole('table')
    expect(within(table).getByText('20.0%')).toBeInTheDocument()
    expect(within(table).getByText('10.0%')).toBeInTheDocument()
    expect(calls.find((c) => c.url === '/conferences/compare')?.params).toMatchObject({ venues: 'acl,emnlp', year: 2026 })
  })

  it('shows a venue not sorted yet as no shares, not as zeros', async () => {
    page('/library/conferences/acl?view=compare', {
      'GET /conferences/compare': { data: { year: 2026, topics, missing: [], venues: [
        { venue: 'acl', name: 'ACL', papers: 200, sorted: 200, topics: { 1: 40 } },
        { venue: 'emnlp', name: 'EMNLP', papers: 300, sorted: 0, topics: {} },
      ] } },
    })
    const table = await screen.findByRole('table')
    expect(within(table).getByText('not sorted yet')).toBeInTheDocument()
    expect(within(table).getByText('–')).toBeInTheDocument()
    expect(within(table).queryByText('0.0%')).not.toBeInTheDocument()
  })

  it('opens a paper and keeps it in Athena on the way to the full panel', async () => {
    const calls = page('/library/conferences/acl', {
      'GET /conferences/papers/2026.acl-long.2': { data: { ...paper('2026.acl-long.2', 'Agents at scale'), abstract: 'We scale agents.',
        abstract_from: 'openalex', doi: null, volume: { id: '2026.acl-long', title: 'ACL 2026' }, venues: [{ slug: 'acl', name: 'ACL' }],
        topic_score: 0.6, citations_at: null, similar: [] } },
      'POST /conferences/papers/2026.acl-long.2/item': { data: { item_id: 'item-9', made: true } },
    })
    await userEvent.click(await screen.findByRole('button', { name: 'Agents at scale' }))
    expect(await screen.findByText('We scale agents.')).toBeInTheDocument()
    expect(screen.getByText(/Abstract from OpenAlex/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Open in Athena/ }))
    await waitFor(() => expect(usePanelStore.getState().itemId).toBe('item-9'))
    expect(calls.some((c) => c.method === 'POST' && c.url === '/conferences/papers/2026.acl-long.2/item')).toBe(true)
    usePanelStore.getState().close()
  })
})

describe('ConferencesTab', () => {
  it('lists the family and each venue with papers', async () => {
    mockApi({ 'GET /conferences': { data: list } })
    renderWithProviders(<ConferencesTab />)
    expect(await screen.findByRole('link', { name: /ACL family/ })).toHaveAttribute('href', '/library/conferences/all')
    expect(screen.getByRole('link', { name: /^EMNLP/ })).toHaveAttribute('href', '/library/conferences/emnlp')
    expect(screen.getAllByText('400 papers')).toHaveLength(1)  // the family's latest year
  })

  it('says how far the first build has got', async () => {
    mockApi({ 'GET /conferences': { data: { ...list, progress: { papers: 700, sorted: 200, cited: 0, abstracts: 600 }, status: { stage: 'embedding' } } } })
    renderWithProviders(<ConferencesTab />)
    expect(await screen.findByText('Sorting papers into topics')).toBeInTheDocument()
    expect(screen.getByText(/200 of 700/)).toBeInTheDocument()
  })

  it('tells people there is nothing yet', async () => {
    mockApi({ 'GET /conferences': { data: { ...list, venues: [], progress: { papers: 0, sorted: 0, cited: 0, abstracts: 0 } } } })
    renderWithProviders(<ConferencesTab />)
    expect(await screen.findByText('No conference papers yet')).toBeInTheDocument()
  })
})
