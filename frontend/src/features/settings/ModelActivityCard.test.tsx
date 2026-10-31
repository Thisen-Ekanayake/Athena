import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Activity, ModelCall } from '../../api/queries/modelActivity'
import { mockApi, renderWithProviders } from '../../test/utils'
import { ModelActivityCard } from './ModelActivityCard'

const NOW = 1_800_000_000

const call = (over: Partial<ModelCall>): ModelCall => ({
  id: 'c1', feature: 'summary', label: 'Summaries', model: 'qwen3.5-9b', kind: 'chat', user_id: null, user: null,
  background: true, started: NOW - 30, server: 'gpu', swapped: false, ...over,
})

const ACTIVITY: Activity = {
  servers: [
    { server: 'gpu', url: 'http://127.0.0.1:8080/v1', online: true, models: [{
      preset: 'qwen3.5-9b', model: 'qwen3.5-9b', status: 'loaded', context: 16384, vision: false, device: 'gpu', gpu_layers: 33,
      layers: 33, vram_mb: 5927, ram_mb: 0,
      slots: [{ id: 0, processing: true, context: 16384, prompt_tokens: 1008, prompt_done: 1008, prompt_cached: 0, decoded: 230,
        max_tokens: null, in_context: 1238, tps: 37.4 }],
    }] },
    { server: 'cpu', url: 'http://127.0.0.1:8081/v1', online: false, models: [] },
  ],
  gpu: null,
  calls: [call({ elapsed: 6.2 }), call({ id: 'c2', feature: 'chat', label: 'Chats', user: 'Ada', user_id: 'u1', background: false, elapsed: 2 })],
  lane: { holder: 'chat', paused: null, groups: [
    { key: 'feed', label: 'Feed', covers: 'summaries, cluster labels and embeddings of new items', paused: null },
    { key: 'maps', label: 'Maps', covers: 'embedding and labelling for map builds and refreshes', paused: null },
  ], waiting: [{ who: 'map_build', label: 'Map building', reason: 'chat', since: NOW - 12 }] },
  queues: [{ label: 'Feed summaries', count: 42, group: 'feed' }, { label: 'Cluster labels', count: 0, group: 'feed' }],
  recent: [
    call({ id: 'r1', seconds: 8, status: 'done', input_tokens: 1200, output_tokens: 400, swapped: true }),
    call({ id: 'r2', feature: 'feed_embed', label: 'Feed embeddings', model: 'qwen3-embedding-8b', kind: 'embed', seconds: 1,
      status: 'failed', error: 'APITimeoutError', input_tokens: 0 }),
  ],
  swaps: [{ at: NOW - 60, server: 'gpu', before: 'qwen3-embedding-8b', after: 'qwen3.5-9b', cause: 'summary', cause_label: 'Summaries', seconds: 1.8 }],
  today: [{ feature: 'summary', label: 'Summaries', calls: 310, failed: 2, input_tokens: 400_000, output_tokens: 90_000, seconds: 2100 }],
  now: NOW,
}

describe('model activity', () => {
  it('shows what is loaded, how far the request has got, who is calling and what waits', async () => {
    mockApi({ 'GET /models/activity': { data: ACTIVITY } })
    renderWithProviders(<ModelActivityCard />)
    expect(await screen.findByText(/Writing · 230 tokens · 37.4 tok\/s/)).toBeInTheDocument()
    expect(screen.getByText('1,238 of 16,384 context tokens in use')).toBeInTheDocument()
    expect(screen.getByText('Nothing loaded')).toBeInTheDocument()  // the CPU router
    const groups = screen.getByRole('list', { name: 'Background work' })
    const running = screen.getAllByRole('listitem').filter((li) => !groups.contains(li))
    expect(running[0]).toHaveTextContent(/Summaries.*qwen3.5-9b.*Background.*6.2 s/)
    expect(running[1]).toHaveTextContent(/Chats.*Ada/)
    expect(screen.getByText(/A chat has the model/)).toBeInTheDocument()
    expect(screen.getByText('Background work is held for a chat and carries on by itself when it ends.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Pause all/ })).toBeInTheDocument()  // a pause can still be set
    expect(screen.getByText('Map building')).toBeInTheDocument()
    expect(screen.getByText(/waits for a chat/)).toBeInTheDocument()
    expect(screen.getByText('Feed summaries')).toHaveTextContent('42')
    expect(screen.queryByText('Cluster labels')).not.toBeInTheDocument()  // nothing queued
  })

  it('lists recent calls, swaps and today’s totals without any prompt text', async () => {
    mockApi({ 'GET /models/activity': { data: ACTIVITY } })
    renderWithProviders(<ModelActivityCard />)
    const rows = await screen.findAllByRole('row')
    expect(rows[1]).toHaveTextContent(/Summaries.*qwen3.5-9b.*swap.*Background.*1,200 → 400.*8\.0 s.*50\.0 tok\/s.*done/)
    expect(rows[2]).toHaveTextContent(/Feed embeddings.*failed · APITimeoutError/)
    await userEvent.click(screen.getByRole('button', { name: 'Model swaps' }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent(/1 min ago.*GPU.*qwen3-embedding-8b → qwen3.5-9b.*Summaries.*1\.8 s/)
    await userEvent.click(screen.getByRole('button', { name: 'Today by feature' }))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent(/Summaries.*310.*2.*400,000.*90,000.*35 min 0 s/)
  })

  it('names who asked for each call and shows long lists 20 rows a page', async () => {
    const recent = Array.from({ length: 45 }, (_, i) => call({
      id: `r${i}`, seconds: 1, status: 'done', input_tokens: i,
      ...(i === 0 ? { feature: 'connection_test', label: 'Connection tests', background: false } : {}),
    }))
    mockApi({ 'GET /models/activity': { data: { ...ACTIVITY, recent } } })
    renderWithProviders(<ModelActivityCard />)
    expect(await screen.findByRole('columnheader', { name: 'Requested by' })).toBeInTheDocument()
    let rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(21)  // the header and a page
    expect(rows[1]).toHaveTextContent(/Connection tests.*System/)
    expect(rows[2]).toHaveTextContent(/Summaries.*Background task/)
    expect(screen.getByText('1–20 of 45')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Page 3' }))
    rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(6)
    expect(screen.getByRole('button', { name: 'Page 3' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Model swaps' }))  // another list starts on its first page
    expect(screen.queryByRole('navigation', { name: 'Pages' })).not.toBeInTheDocument()
  })

  it('pauses one group of background work, or all of it, and resumes it', async () => {
    const state: Record<string, Activity['lane']['paused']> = { feed: null, maps: null }
    const set = (on: boolean) => (call: { body: unknown }) => {
      const group = (call.body as { group?: string } | undefined)?.group
      for (const g of group ? [group] : ['feed', 'maps']) state[g] = on ? { by: 'Ada', since: NOW - 120 } : null
      return { data: {} }
    }
    const lane = () => ({ ...ACTIVITY.lane, holder: null, groups: ACTIVITY.lane.groups.map((g) => ({ ...g, paused: state[g.key] })) })
    const calls = mockApi({
      'GET /models/activity': () => ({ data: { ...ACTIVITY, lane: lane() } }),
      'POST /models/activity/pause': set(true),
      'POST /models/activity/resume': set(false),
    })
    renderWithProviders(<ModelActivityCard />)
    const rows = await screen.findByRole('list', { name: 'Background work' })
    expect(within(rows).getAllByRole('listitem')[0]).toHaveTextContent(/Feed.*runs.*42 queued.*Summaries, cluster labels and embeddings/)
    await userEvent.click(screen.getByRole('button', { name: 'Pause Maps' }))
    expect(await screen.findByText('Maps paused; the rest runs.')).toBeInTheDocument()
    expect(within(rows).getAllByRole('listitem')[1]).toHaveTextContent(/Maps.*paused by Ada, 2 min/)
    await userEvent.click(screen.getByRole('button', { name: /Pause all/ }))
    expect(await screen.findByText(/All background work is paused/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Resume all/ }))
    expect(await screen.findByText('Background work runs.')).toBeInTheDocument()
    expect(calls.filter((c) => c.method === 'POST').map((c) => [c.url, c.body])).toEqual([
      ['/models/activity/pause', { group: 'maps' }], ['/models/activity/pause', undefined], ['/models/activity/resume', undefined]])
  })
})
