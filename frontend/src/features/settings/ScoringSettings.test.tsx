import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { BASE_SIGNALS, type CategoryWeights, type ScoringSettings as Settings } from '../../api/queries/app_settings'
import { mockApi, renderWithProviders, type Reply } from '../../test/utils'
import { ScoringSettings } from './ScoringSettings'

// Spread evenly over whichever signals there are, so removing one (T1) doesn't break the tests.
const even = (): CategoryWeights => ({
  ...(Object.fromEntries(BASE_SIGNALS.map((k) => [k, 1 / BASE_SIGNALS.length])) as Record<(typeof BASE_SIGNALS)[number], number>),
  preference: 0.3, half_life_days: 14,
})

const settings: Settings = {
  categories: {
    paper: { ...even(), version: 3, source: 'saved' },
    company_blog: { ...even(), version: null, source: 'default' },
  },
  defaults: { paper: even(), company_blog: even() },
}

function open(save: Reply = { data: { ...settings, rescoring: true } }) {
  const calls = mockApi({ 'GET /settings/scoring': { data: settings }, 'PUT /settings/scoring': save })
  renderWithProviders(<ScoringSettings />)
  return calls
}

/** The card of one kind of item: its title sits in the card's header. */
const card = async (title: string) => (await screen.findByRole('heading', { name: title })).closest('header')!.parentElement!
const [first, second] = BASE_SIGNALS

async function moveWeight(papers: HTMLElement, by: number) {
  const inputs = within(papers).getAllByRole('spinbutton')
  const [a, b] = inputs
  await userEvent.clear(a)
  await userEvent.type(a, String(+(1 / BASE_SIGNALS.length + by).toFixed(2)))
  await userEvent.clear(b)
  await userEvent.type(b, String(+(1 / BASE_SIGNALS.length - by).toFixed(2)))
}

describe('ScoringSettings', () => {
  it('shows each kind of item with its weights and where they come from', async () => {
    open()
    const papers = await card('Papers')
    expect(within(papers).getByText('Version 3')).toBeInTheDocument()
    expect(within(await card('Lab blogs')).getByText('Defaults')).toBeInTheDocument()
    expect(within(papers).getAllByRole('spinbutton')).toHaveLength(BASE_SIGNALS.length + 2)
    expect(within(papers).getByText('adds up to 1.00')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it("won't save weights that don't add up to 1", async () => {
    open()
    const papers = await card('Papers')
    const citation = within(papers).getAllByRole('spinbutton')[0]
    await userEvent.clear(citation)
    await userEvent.type(citation, '0.9')
    expect(within(papers).getByText(/^adds up to \d\.\d\d, not 1\.00$/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('saves an edit and says rescoring started', async () => {
    const calls = open()
    await moveWeight(await card('Papers'), 0.1)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Saved. Rescoring started in the background.')).toBeInTheDocument()
    const put = calls.find((c) => c.method === 'PUT')!
    const { categories } = put.body as { categories: Record<string, CategoryWeights> }
    expect(categories.paper[first]).toBeCloseTo(1 / BASE_SIGNALS.length + 0.1)
    expect(categories.paper[second]).toBeCloseTo(1 / BASE_SIGNALS.length - 0.1)
    expect(categories.company_blog[first]).toBeCloseTo(1 / BASE_SIGNALS.length)
  })

  it('shows why a save was refused and keeps the edit', async () => {
    open({ status: 422, data: { detail: 'Each weight must be between 0 and 1' } })
    await moveWeight(await card('Papers'), 0.1)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Not saved')).toBeInTheDocument()
    expect(screen.getByText('Each weight must be between 0 and 1')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Discard' })).toBeInTheDocument())
  })
})
