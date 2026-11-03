import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AccessToken } from '../../api/queries/tokens'
import { mockApi, renderWithProviders } from '../../test/utils'
import { AgentsSettings } from './AgentsSettings'
import { claudeCommand, mcpUrl } from './connect'

const old: AccessToken = {
  id: 't1', name: 'Laptop agent', hint: 'ath_abcd', created_at: '2026-10-01T00:00:00Z',
  last_used_at: null, expires_at: null,
}

afterEach(() => vi.restoreAllMocks())

describe('AgentsSettings', () => {
  it('lists the tokens by name and hint, never their value', async () => {
    mockApi({ 'GET /tokens': { data: [old] } })
    renderWithProviders(<AgentsSettings />)
    expect(await screen.findByText('Laptop agent')).toBeInTheDocument()
    expect(screen.getByText('ath_abcd…')).toBeInTheDocument()
    expect(screen.getByText(/Not used yet/)).toBeInTheDocument()
  })

  it('shows a new token once, with the command that connects Claude Code', async () => {
    const calls = mockApi({
      'GET /tokens': { data: [] },
      'POST /tokens': { status: 201, data: { ...old, id: 't2', name: 'Claude Code', token: 'ath_secret' } },
    })
    renderWithProviders(<AgentsSettings />)
    await userEvent.selectOptions(await screen.findByLabelText('Expires'), '90 days')
    await userEvent.click(screen.getByRole('button', { name: 'Make a token' }))
    expect(await screen.findByText('ath_secret')).toBeInTheDocument()
    expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ name: 'Claude Code', expires_days: 90 })
    expect(screen.getByText(claudeCommand('ath_secret'))).toBeInTheDocument()
    expect(claudeCommand('ath_secret')).toContain(`${mcpUrl()} --header "Authorization: Bearer ath_secret"`)
    await userEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(screen.queryByText('ath_secret')).not.toBeInTheDocument()
  })

  it('revokes a token after asking', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const calls = mockApi({ 'GET /tokens': { data: [old] }, 'DELETE /tokens/t1': { status: 204 } })
    renderWithProviders(<AgentsSettings />)
    await userEvent.click(await screen.findByRole('button', { name: 'Revoke Laptop agent' }))
    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE' && c.url === '/tokens/t1')).toBe(true))
  })
})
