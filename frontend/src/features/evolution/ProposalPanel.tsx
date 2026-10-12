import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Plus, Sparkles, X } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { useCreateTopic, useProposal, type TopicProposal } from './api'

interface Draft {
  name: string
  description: string
  aliases: string[]
  anchors: string[]
  keywords: string[]
  fields: string[]
}

const fromRules = (p: TopicProposal): Draft => ({
  name: p.name,
  description: p.description,
  aliases: p.aliases,
  anchors: p.anchors,
  keywords: p.keywords,
  fields: p.fields,
})

const fromModel = (p: TopicProposal, draft: Draft): Draft => ({
  ...draft,
  name: p.refine.name || draft.name,
  description: p.refine.description || draft.description,
  aliases: p.refine.aliases ?? draft.aliases,
  anchors: p.refine.anchors ?? draft.anchors,
  keywords: p.refine.keywords ?? draft.keywords,
})

const toggle = (list: string[], value: string) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value])

/** A search's proposed topic: anchors, keywords and fields to check before the map is built. */
export function ProposalPanel({ proposal: initial, onCancel }: { proposal: TopicProposal; onCancel: () => void }) {
  const navigate = useNavigate()
  const { data: proposal } = useProposal(initial)
  const create = useCreateTopic()
  // Until the first edit, the draft follows the proposal: the rules' picks, then the 9B's once it answers.
  // After it, the person's edits stand, and the 9B's answer waits behind an "Apply" link.
  const [edits, setEdits] = useState<Draft | null>(null)
  const [modelApplied, setModelApplied] = useState(false)
  const [newKeyword, setNewKeyword] = useState('')

  const refine = proposal.refine
  const modelDone = refine.status === 'done'
  const draft = edits ?? (modelDone ? fromModel(proposal, fromRules(proposal)) : fromRules(proposal))
  const touched = edits !== null
  const applied = !touched ? modelDone : modelApplied
  const modelPicks = new Set(modelDone && refine.anchors_from_model ? refine.anchors : [])

  const edit = (patch: Partial<Draft>) => {
    if (!touched) setModelApplied(modelDone)
    setEdits({ ...draft, ...patch })
  }

  const addKeyword = (e: FormEvent) => {
    e.preventDefault()
    const k = newKeyword.trim().toLowerCase()
    if (k && !draft.keywords.includes(k)) edit({ keywords: [...draft.keywords, k] })
    setNewKeyword('')
  }

  const build = () => {
    const byId = new Map(proposal.candidates.map((c) => [c.openalex_id, c]))
    create.mutate(
      {
        query: proposal.query,
        name: draft.name.trim() || proposal.name,
        description: draft.description.trim(),
        aliases: draft.aliases,
        keywords: draft.keywords,
        anchors: draft.anchors.map((id) => ({ openalex_id: id, alt_ids: byId.get(id)?.alt_ids ?? [] })),
        fields: draft.fields,
        proposal_id: proposal.id,
      },
      { onSuccess: (topic) => navigate(`/evolution/${topic.slug}`) },
    )
  }

  if (proposal.candidates.length === 0) {
    return (
      <Notice title={`OpenAlex found no papers for “${proposal.query}”`}>
        Try another wording, or the field’s usual name.
      </Notice>
    )
  }

  const fieldOptions = [...new Set([...draft.fields, ...proposal.field_counts.map(([f]) => f)])]
  const fieldTotal = proposal.field_counts.reduce((sum, [, n]) => sum + n, 0)
  const offered = proposal.keyword_suggestions.filter((k) => !draft.keywords.includes(k))
  const canBuild = draft.anchors.length > 0 && draft.keywords.length > 0 && !create.isPending

  return (
    <section className="grid gap-5 rounded-xl border border-line bg-surface p-4 sm:p-5" aria-label="Proposed map">
      <div className="grid gap-1">
        <h2 className="text-[15px] font-medium text-fg">No map for “{proposal.query}” yet</h2>
        <p className="text-[13px] text-fg-2">
          Athena proposes the papers to grow it from and the words that mark a paper as on-topic. Check them, then build.
        </p>
        <RefineLine status={refine.status} error={refine.error} touched={touched} applied={applied} modelAnchors={modelPicks.size > 0} onApply={() => {
          setEdits(fromModel(proposal, draft))
          setModelApplied(true)
        }} />
      </div>

      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <label className="grid gap-1 text-[12px] text-fg-3">
          Name
          <input
            id="proposal-name"
            value={draft.name}
            onChange={(e) => edit({ name: e.target.value })}
            maxLength={80}
            className="h-8 rounded-lg border border-line bg-bg px-2.5 text-[13px] text-fg focus:border-accent-line focus:outline-none"
          />
        </label>
        <label className="grid gap-1 text-[12px] text-fg-3">
          Description (optional)
          <input
            id="proposal-description"
            value={draft.description}
            onChange={(e) => edit({ description: e.target.value })}
            maxLength={500}
            placeholder="One sentence on what the topic is about"
            className="h-8 rounded-lg border border-line bg-bg px-2.5 text-[13px] text-fg placeholder:text-fg-3 focus:border-accent-line focus:outline-none"
          />
        </label>
      </div>

      <fieldset className="grid gap-2">
        <legend className="mb-1 flex flex-wrap items-baseline gap-x-2 text-[13px] font-medium text-fg">
          Anchor papers
          <span className="text-[12px] font-normal text-fg-3">
            {draft.anchors.length} chosen · the map grows from what they cite and what cites them
          </span>
        </legend>
        <ul className="max-h-80 divide-y divide-line overflow-y-auto rounded-lg border border-line">
          {proposal.candidates.map((c) => {
            const checked = draft.anchors.includes(c.openalex_id)
            return (
              <li key={c.openalex_id}>
                <label className={cn('grid cursor-pointer grid-cols-[1rem_3rem_minmax(0,1fr)_auto] items-baseline gap-3 px-3 py-2 text-[13px] transition-colors hover:bg-surface-2/60', checked && 'bg-accent-soft/40')}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => edit({ anchors: toggle(draft.anchors, c.openalex_id) })}
                    className="translate-y-0.5 accent-[var(--accent)]"
                  />
                  <span className="font-mono text-[12px] text-fg-3 tabular-nums">{c.year ?? '—'}</span>
                  <span className="min-w-0 text-fg">
                    {c.title}
                    <span className="ml-2 inline-flex gap-1 align-middle">
                      {c.kind !== 'method' && <Chip>{c.kind}</Chip>}
                      {!c.title_match && <Chip>found by meaning</Chip>}
                      {modelPicks.has(c.openalex_id) && <Chip tone="accent"><Sparkles aria-hidden="true" />9B pick</Chip>}
                    </span>
                  </span>
                  <span className="font-mono text-[12px] text-fg-3 tabular-nums">{c.citations.toLocaleString()}</span>
                </label>
              </li>
            )
          })}
        </ul>
        <p className="text-[12px] text-fg-3">Citation counts are OpenAlex’s, which run low for recent arXiv papers.</p>
      </fieldset>

      <div className="grid gap-2">
        <h3 className="flex flex-wrap items-baseline gap-x-2 text-[13px] font-medium text-fg">
          Keywords
          <span className="text-[12px] font-normal text-fg-3">
            only papers whose title or abstract uses one can be milestones
          </span>
        </h3>
        <div className="flex flex-wrap items-center gap-1.5">
          {draft.keywords.map((k) => (
            <span key={k} className="inline-flex items-center gap-1 rounded-full bg-accent-soft py-px pr-1 pl-2.5 text-[12.5px] text-accent-ink">
              {k}
              <button type="button" onClick={() => edit({ keywords: draft.keywords.filter((x) => x !== k) })} aria-label={`Remove ${k}`} className="rounded-full p-0.5 hover:bg-accent-soft">
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          {offered.map((k) => (
            <button key={k} type="button" onClick={() => edit({ keywords: [...draft.keywords, k] })} className="inline-flex items-center gap-1 rounded-full border border-dashed border-line-strong px-2.5 py-px text-[12.5px] text-fg-2 hover:border-accent-line hover:text-fg">
              <Plus className="h-3 w-3" aria-hidden="true" />{k}
            </button>
          ))}
          <form onSubmit={addKeyword} className="inline-flex">
            <input
              id="proposal-keyword"
              value={newKeyword}
              onChange={(e) => setNewKeyword(e.target.value)}
              placeholder="Add a keyword"
              maxLength={60}
              aria-label="Add a keyword"
              className="h-6 w-36 rounded-full border border-line bg-bg px-2.5 text-[12.5px] text-fg placeholder:text-fg-3 focus:border-accent-line focus:outline-none"
            />
          </form>
        </div>
        <p className="text-[12px] text-fg-3">
          A keyword matches the start of a word, so <code className="font-mono">detect</code> finds “detector”. In quotes, <code className="font-mono">"mot"</code> matches only the whole word, not “motion”.
        </p>
      </div>

      {fieldOptions.length > 0 && (
        <div className="grid gap-2">
          <h3 className="flex flex-wrap items-baseline gap-x-2 text-[13px] font-medium text-fg">
            Fields
            <span className="text-[12px] font-normal text-fg-3">papers from other fields are left out</span>
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {fieldOptions.map((f) => {
              const n = proposal.field_counts.find(([name]) => name === f)?.[1]
              const on = draft.fields.includes(f)
              return (
                <button
                  key={f}
                  type="button"
                  aria-pressed={on}
                  onClick={() => edit({ fields: toggle(draft.fields, f) })}
                  className={cn('rounded-full border px-2.5 py-px text-[12.5px] transition-colors', on ? 'border-accent-line bg-accent-soft text-accent-ink' : 'border-line text-fg-3 hover:text-fg-2')}
                >
                  {f}
                  {n !== undefined && fieldTotal > 0 && <span className="ml-1.5 font-mono text-[11px] opacity-70">{Math.round((100 * n) / fieldTotal)}%</span>}
                </button>
              )
            })}
          </div>
        </div>
      )}

      {create.error && <Notice tone="error" title="The map could not be started">{apiErrorMessage(create.error, 'Try again.')}</Notice>}

      <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
        <Button variant="primary" onClick={build} disabled={!canBuild}>
          {create.isPending ? <Spinner className="h-4 w-4" /> : 'Build the map'}
        </Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <span className="text-[12px] text-fg-3">
          {draft.anchors.length === 0 ? 'Choose at least one anchor paper.' : draft.keywords.length === 0 ? 'Keep at least one keyword.' : 'Takes a few minutes; you can leave the page while it builds.'}
        </span>
      </div>
    </section>
  )
}

function RefineLine({ status, error, touched, applied, modelAnchors, onApply }: {
  status: TopicProposal['refine']['status']
  error?: string
  touched: boolean
  applied: boolean
  modelAnchors: boolean
  onApply: () => void
}) {
  const line = (children: ReactNode, busy = false) => (
    <p className="mt-1 flex items-center gap-2 text-[12.5px] text-fg-2">
      {busy ? <Spinner className="h-3.5 w-3.5" /> : <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}
      <span>{children}</span>
    </p>
  )
  switch (status) {
    case 'pending':
      return line('Waiting for the GPU so the 9B can review these picks. You can build now.', true)
    case 'running':
      return line('The 9B is reviewing the candidates and keywords…', true)
    case 'done':
      return touched && !applied
        ? line(<>The 9B has suggestions. <button type="button" onClick={onApply} className="text-accent-ink underline-offset-2 hover:underline">Apply them</button> (replaces your edits).</>)
        : line(modelAnchors ? 'The 9B reviewed these picks; its anchor choices are marked.' : 'The 9B added keywords; the anchors are the rule-based picks.')
    case 'failed':
      return line(`The 9B could not answer${error ? ` (${error})` : ''}, so these are the rule-based picks.`)
    case 'expired':
      return line('The GPU is busy with another job, so these are the rule-based picks.')
    default:
      return null
  }
}
