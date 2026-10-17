import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { mockApi, renderWithProviders } from '../../test/utils'
import { FeedMixSettings } from './FeedMixSettings'

function open() {
  const calls = mockApi({
    'GET /settings/feed': { data: { source_share: 0.25, default_source_share: 0.25 } },
    'PUT /settings/feed': ({ body }) => ({ data: { ...(body as object), default_source_share: 0.25 } }),
  })
  renderWithProviders(<FeedMixSettings />)
  return calls
}

describe('FeedMixSettings', () => {
  it('shows the cap as a percentage and what it means for a page', async () => {
    open()
    expect(await screen.findByRole('spinbutton')).toHaveValue(25)
    expect(screen.getByText('5 of every 20 items')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('saves a new cap as a share', async () => {
    const calls = open()
    const input = await screen.findByRole('spinbutton')
    await userEvent.clear(input)
    await userEvent.type(input, '40')
    expect(screen.getByText('8 of every 20 items')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(calls.find((c) => c.method === 'PUT')?.body).toEqual({ source_share: 0.4 }))
  })

  it('will not save a cap outside 1–100', async () => {
    open()
    const input = await screen.findByRole('spinbutton')
    await userEvent.clear(input)
    await userEvent.type(input, '0')
    expect(screen.getByText('Between 1 and 100')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })
})
