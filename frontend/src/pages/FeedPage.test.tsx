import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { FeedItem, FeedResponse } from '../api/client'
import type { Interests } from '../api/queries/personal'
import { mockApi, renderWithProviders, type Call } from '../test/utils'
import { FeedPage } from './FeedPage'

const item = (id: string, title: string): FeedItem => ({
  id, title, url: `https://example.com/${id}`, summary: null, score: 0.8, published_at: '2026-10-16T12:00:00Z',
  category: 'paper', source: { name: 'arXiv', type: 'arxiv', authority: 0.9 }, related_count: 0,
})

const page = (items: FeedItem[]): FeedResponse => ({
  items, pagination: { page: 1, limit: 20, total: items.length, has_next: false },
})

const interests = (ready: boolean): Interests => ({
  enabled: true, signals: ready ? 12 : 2, full_at: 10, ready, counts: { up: 0, down: 0, hide: 0, saved: 0 },
})

function feed(items: FeedItem[], { ready = false } = {}): Call[] {
  const calls = mockApi({
    'GET /me/interests': { data: interests(ready) },
    'GET /feed': ({ params }) => ({ data: { ...page(items), personalised: params.sort === 'foryou' } }),
  })
  renderWithProviders(<FeedPage />)
  return calls
}

const feedRequests = (calls: Call[]) => calls.filter((c) => c.url === '/feed').map((c) => c.params)

describe('FeedPage', () => {
  it('lists the ranked items', async () => {
    const calls = feed([item('a', 'Attention is all you need'), item('b', 'Scaling laws')])
    expect(await screen.findByText('Attention is all you need')).toBeInTheDocument()
    expect(screen.getByText('Scaling laws')).toBeInTheDocument()
    expect(screen.getByText('2 items')).toBeInTheDocument()
    expect(feedRequests(calls).at(-1)).toMatchObject({ sort: 'score', page: 1, limit: 20 })
  })

  it('says how to get items when there are none', async () => {
    feed([])
    expect(await screen.findByText('Nothing here yet')).toBeInTheDocument()
    expect(screen.getByText('Sync your sources to fetch the first items.')).toBeInTheDocument()
  })

  it('re-sorts and remembers the pick on this browser', async () => {
    const calls = feed([item('a', 'Attention is all you need')])
    await screen.findByText('Attention is all you need')
    await userEvent.click(screen.getByRole('button', { name: 'Newest' }))
    await waitFor(() => expect(feedRequests(calls).at(-1)).toMatchObject({ sort: 'date' }))
    expect(screen.getByRole('button', { name: 'Newest' })).toHaveAttribute('aria-pressed', 'true')
    expect(localStorage.getItem('athena.feed.sort')).toBe('date')
  })

  it('opens on For you once it has enough to learn from', async () => {
    const calls = feed([item('a', 'Attention is all you need')], { ready: true })
    await waitFor(() => expect(feedRequests(calls).at(-1)).toMatchObject({ sort: 'foryou' }))
    expect(await screen.findByText('1 ranked for you')).toBeInTheDocument()
  })

  it('says when the feed could not be loaded', async () => {
    mockApi({ 'GET /me/interests': { data: interests(false) }, 'GET /feed': { status: 500 } })
    renderWithProviders(<FeedPage />)
    expect(await screen.findByText('The feed could not be loaded')).toBeInTheDocument()
  })
})
