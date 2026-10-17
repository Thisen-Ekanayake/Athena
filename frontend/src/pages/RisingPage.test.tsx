import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { RisingItem } from '../api/queries/momentum'
import { mockApi, renderWithProviders, type Call } from '../test/utils'
import { RisingPage } from './RisingPage'

const paper = (id: string, title: string, gain: number): RisingItem => ({
  id, title, url: `https://arxiv.org/abs/${id}`, summary: null, score: 0.6, published_at: '2026-10-01T12:00:00Z',
  category: 'paper', source: { name: 'ArXiv AI', type: 'api', authority: 0.85 }, related_count: 0,
  citation_count: 40 + gain, gain, series: [40, 40 + gain],
})

function rising(byWindow: Record<string, RisingItem[]>): Call[] {
  const calls = mockApi({
    'GET /momentum/rising': ({ params }) => ({ data: { window: params.window, items: byWindow[String(params.window)] ?? [] } }),
  })
  renderWithProviders(<RisingPage />)
  return calls
}

const windows = (calls: Call[]) => calls.filter((c) => c.url === '/momentum/rising').map((c) => c.params.window)

describe('RisingPage', () => {
  it('lists the papers gaining the most citations this week', async () => {
    const calls = rising({ '7d': [paper('a', 'Sparse attention', 12), paper('b', 'Diffusion policies', 4)] })
    expect(await screen.findByText('Sparse attention')).toBeInTheDocument()
    expect(screen.getByText('Diffusion policies')).toBeInTheDocument()
    expect(screen.getByText('+12')).toBeInTheDocument()
    expect(calls.at(-1)?.params).toMatchObject({ window: '7d', limit: 50 })
  })

  it('switches to the month', async () => {
    const calls = rising({ '7d': [paper('a', 'Sparse attention', 12)], '30d': [paper('c', 'Long context', 30)] })
    await screen.findByText('Sparse attention')
    await userEvent.click(screen.getByRole('button', { name: 'This month' }))
    expect(await screen.findByText('Long context')).toBeInTheDocument()
    await waitFor(() => expect(windows(calls)).toEqual(['7d', '30d']))
  })

  it('says when nothing gained citations', async () => {
    rising({})
    expect(await screen.findByText('No paper gained citations this week')).toBeInTheDocument()
  })
})
