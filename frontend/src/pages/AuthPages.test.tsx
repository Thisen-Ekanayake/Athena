import { screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { AuthStatus, AuthUser } from '../api/queries/auth'
import { mockApi, renderWithProviders } from '../test/utils'
import { RequireAuth } from './AuthPages'

const user = (over: Partial<AuthUser> = {}): AuthUser => ({
  id: 'u1', email: 'ada@example.com', display_name: 'Ada', role: 'user', is_active: true,
  must_change_password: false, created_at: null, last_login_at: null, onboarded_at: '2026-10-01T00:00:00Z', ...over,
})

function guard(status: AuthStatus | null, { guide = false, route = '/feed' } = {}) {
  mockApi({ 'GET /auth/status': status ? { data: status } : { status: 502 } })
  renderWithProviders(<RequireAuth guide={guide}><p>The feed</p></RequireAuth>, { route, path: '/feed' })
}

const landedOn = async () => (await screen.findByTestId('location')).textContent

describe('RequireAuth', () => {
  it('lets a ready account through', async () => {
    guard({ needs_setup: false, user: user() })
    expect(await screen.findByText('The feed')).toBeInTheDocument()
  })

  it('sends a new install to create the first admin', async () => {
    guard({ needs_setup: true, user: null })
    expect(await landedOn()).toBe('/setup')
  })

  it('sends a visitor to log in, remembering where they were going', async () => {
    guard({ needs_setup: false, user: null }, { route: '/feed?sort=date' })
    expect(await landedOn()).toBe('/login')
    expect(JSON.parse(screen.getByTestId('location').dataset.state!)).toEqual({ from: '/feed?sort=date' })
  })

  it('makes a temporary password be replaced first', async () => {
    guard({ needs_setup: false, user: user({ must_change_password: true }) })
    expect(await landedOn()).toBe('/change-password')
  })

  it('opens the setup guide until it is finished', async () => {
    guard({ needs_setup: false, user: user({ onboarded_at: null }) })
    expect(await landedOn()).toBe('/welcome')
  })

  it('shows the guide itself to a new account', async () => {
    guard({ needs_setup: false, user: user({ onboarded_at: null }) }, { guide: true })
    expect(await screen.findByText('The feed')).toBeInTheDocument()
  })

  it('says so when the API is not answering', async () => {
    guard(null)
    expect(await screen.findByText("Athena's API is not answering", {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.queryByText('The feed')).not.toBeInTheDocument()
  })
})
