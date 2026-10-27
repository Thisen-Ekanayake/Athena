import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { ChatSummary } from '../../api/queries/chats'
import { mockApi, renderWithProviders } from '../../test/utils'
import { Sidebar } from './Sidebar'

const chat = (c: Partial<ChatSummary>): ChatSummary => ({
  id: 'c1', title: 'LoRA questions', project_id: null, project_name: null, model: null, effort: null, pinned: false,
  archived: false, created_at: '', updated_at: '2026-10-27T09:00:00Z', ...c,
})

const PROJECT = {
  id: 'p1', name: 'Sinhala NLP', description: '', instructions: '', created_at: '', updated_at: '',
  counts: { chats: 1, items: 0, files: 0, artifacts: 0 },
}

function setup(chats: ChatSummary[] = [chat({})]) {
  return mockApi({
    'GET /chats': { data: { chats } },
    'GET /projects': { data: { projects: [PROJECT] } },
    'PATCH /chats/c1': ({ body }) => ({ data: { ...chats[0], ...(body as object) } }),
    'DELETE /chats/c1': { status: 204 },
  })
}

describe('Sidebar', () => {
  it('lists the projects under the Projects link when opened', async () => {
    setup()
    renderWithProviders(<Sidebar />)
    expect(screen.queryByRole('link', { name: 'Sinhala NLP' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show projects' }))
    expect(await screen.findByRole('link', { name: 'Sinhala NLP' })).toHaveAttribute('href', '/projects/p1')
    await userEvent.click(screen.getByRole('button', { name: 'Hide projects' }))
    expect(screen.queryByRole('link', { name: 'Sinhala NLP' })).not.toBeInTheDocument()
  })

  it('pins, archives and renames a chat from its row', async () => {
    const calls = setup()
    renderWithProviders(<Sidebar />)
    await screen.findByRole('link', { name: 'LoRA questions' })

    await userEvent.click(screen.getByRole('button', { name: 'Pin LoRA questions' }))
    await waitFor(() => expect(calls).toContainEqual(expect.objectContaining({ method: 'PATCH', url: '/chats/c1', body: { pinned: true } })))

    await userEvent.click(screen.getByRole('button', { name: 'Actions for LoRA questions' }))
    await userEvent.click(within(screen.getByRole('dialog', { name: 'Chat actions' })).getByRole('button', { name: 'Archive' }))
    await waitFor(() => expect(calls).toContainEqual(expect.objectContaining({ method: 'PATCH', body: { archived: true } })))

    await userEvent.click(screen.getByRole('button', { name: 'Actions for LoRA questions' }))
    await userEvent.click(screen.getByRole('button', { name: 'Rename' }))
    const field = screen.getByRole('textbox', { name: 'Chat title' })
    await userEvent.clear(field)
    await userEvent.type(field, 'Adapters{Enter}')
    await waitFor(() => expect(calls).toContainEqual(expect.objectContaining({ method: 'PATCH', body: { title: 'Adapters' } })))
  })

  it('deletes a chat only once confirmed', async () => {
    const calls = setup()
    renderWithProviders(<Sidebar />)
    await screen.findByRole('link', { name: 'LoRA questions' })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    for (let i = 0; i < 2; i++) {
      await userEvent.click(screen.getByRole('button', { name: 'Actions for LoRA questions' }))
      await userEvent.click(screen.getByRole('button', { name: 'Delete' }))
    }
    await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE')).toHaveLength(1))
    expect(confirm).toHaveBeenCalledTimes(2)
    confirm.mockRestore()
  })

  it('marks a pinned chat', async () => {
    setup([chat({ pinned: true })])
    renderWithProviders(<Sidebar />)
    expect(await screen.findByLabelText('Pinned')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Unpin LoRA questions' })).toHaveAttribute('aria-pressed', 'true')
  })
})
