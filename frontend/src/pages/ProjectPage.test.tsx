import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Project } from '../api/queries/projects'
import { mockApi, renderWithProviders } from '../test/utils'
import { ProjectPage } from './ProjectPage'

const PROJECT: Project = {
  id: 'p1', name: 'Thesis', description: 'Efficient fine-tuning', instructions: '', created_at: '2026-10-20T10:00:00Z',
  updated_at: '2026-10-24T10:00:00Z', counts: { chats: 1, items: 2, files: 1, artifacts: 1 },
  items: [
    { id: 'i1', kind: 'paper', ref: 'item:x', title: 'LoRA', subtitle: 'E. Hu · 2021', link: '/items/x', index_status: 'indexed', index_error: null, added_at: '' },
    { id: 'i2', kind: 'map', ref: 'map:y', title: 'PEFT', subtitle: null, link: '/evolution/peft', slug: 'peft', built: true, index_status: 'pending', index_error: null, added_at: '' },
  ],
  files: [{ id: 'f1', filename: 'notes.pdf', mime: 'application/pdf', kind: 'pdf', size: 20480, pages: 3, status: 'ready', error: null, index_status: 'failed', chars: 5200, caption: null, project_id: 'p1', conversation_id: null, created_at: '' }],
  artifacts: [{ id: 'a1', title: 'Related work', version: 3, project_id: 'p1', conversation_id: 'c1', index_status: 'indexed', created_at: '', updated_at: '2026-10-24T09:00:00Z', chars: 900 }],
  chats: [{ id: 'c1', title: 'LoRA questions', project_id: 'p1', project_name: 'Thesis', model: null, effort: null, pinned: false, archived: false, created_at: '', updated_at: '2026-10-24T09:00:00Z' }],
}

describe('ProjectPage', () => {
  it('lists the knowledge with what is still being read, and saves instructions', async () => {
    const calls = mockApi({
      'GET /projects/p1': { data: PROJECT },
      'GET /chat/models': { data: { models: [], default: 'qwen3.5-9b', efforts: [], default_effort: 'low', vision_model: '' } },
      'PATCH /projects/p1': ({ body }) => ({ data: { ...PROJECT, ...(body as object) } }),
    })
    renderWithProviders(<ProjectPage />, { route: '/projects/p1', path: '/projects/:id' })
    expect(await screen.findByRole('heading', { name: 'Thesis' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'LoRA' })).toHaveAttribute('href', '/items/x')
    expect(screen.getByText('Reading')).toBeInTheDocument()            // the map is being indexed
    expect(screen.getByText('Not searchable')).toBeInTheDocument()     // the PDF failed
    expect(screen.getByText(/3 pages · 5,200 characters/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /LoRA questions/ })).toHaveAttribute('href', '/chats/c1')

    await userEvent.click(screen.getByRole('button', { name: 'Add' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Instructions' }), 'Use British spelling.')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ instructions: 'Use British spelling.' })
  })
})
