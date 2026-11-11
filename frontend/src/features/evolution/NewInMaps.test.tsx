import { screen, waitFor } from '@testing-library/react'
import { expect, test } from 'vitest'
import { mockApi, renderWithProviders } from '../../test/utils'
import { NewInMaps } from './NewInMaps'

const paper = (n: number) => ({
  id: `item-${n}`,
  title: `Recent paper ${n}`,
  url: `https://arxiv.org/abs/2610.0000${n}`,
  published_at: '2026-11-01T00:00:00+00:00',
  score: 0.5,
  cites: [{ topic: 'peft', topic_name: 'PEFT', paper_id: 'p1', title: 'LoRA', year: 2021, milestone: true, named_method: 'LoRA' }],
})

test('asks the server for only the papers it shows', async () => {
  // A month of papers citing milestones is over a thousand; the list shows a handful.
  const calls = mockApi({ 'GET /evolution/new-papers': (call) => ({ data: [1, 2, 3, 4, 5, 6, 7].slice(0, Number(call.params.limit)).map(paper) }) })
  renderWithProviders(<NewInMaps topic="peft" limit={5} />)
  expect(await screen.findByText('Recent paper 5')).toBeInTheDocument()
  expect(screen.queryByText('Recent paper 6')).not.toBeInTheDocument()
  await waitFor(() => expect(calls.find((c) => c.url === '/evolution/new-papers')?.params).toMatchObject({ topic: 'peft', limit: 5 }))
})
