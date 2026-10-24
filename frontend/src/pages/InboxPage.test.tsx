import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { InboxEvent } from '../api/queries/inbox'
import { mockApi, renderWithProviders } from '../test/utils'
import { InboxPage } from './InboxPage'

const entry = (id: string, title: string): InboxEvent => ({
  id, kind: 'watch_matches', title, body: null, link: null, created_at: '2026-10-20T12:00:00Z', unread: false,
  payload: { items: [{ id: `item-${id}`, title: `Paper for ${title}` }] },
})

const expanded = (title: string) =>
  screen.getByRole('button', { name: new RegExp(`^${title}`) }).getAttribute('aria-expanded')

describe('InboxPage', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()  // jsdom has no layout
    mockApi({ 'GET /inbox': { data: { events: [entry('a', 'Sparse attention'), entry('b', 'Long context')], unread: 0 } } })
  })

  it('opens the entry the bell linked to', async () => {
    renderWithProviders(<InboxPage />, { route: '/inbox?open=a' })
    expect(await screen.findByText('Paper for Sparse attention')).toBeInTheDocument()
    expect(expanded('Sparse attention')).toBe('true')
    expect(expanded('Long context')).toBe('false')
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })

  it('opens another entry when the bell links to it while the page is open', async () => {
    renderWithProviders(<><InboxPage /><Link to="/inbox?open=b">bell</Link></>, { route: '/inbox?open=a' })
    await screen.findByText('Paper for Sparse attention')
    await userEvent.click(screen.getByRole('link', { name: 'bell' }))
    expect(await screen.findByText('Paper for Long context')).toBeInTheDocument()
    expect(expanded('Sparse attention')).toBe('true')
  })
})
