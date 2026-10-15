import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Check, Download, GitBranch, Search } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { useCurrentUser, useSetOnboarded } from '../../api/queries/auth'
import { useWatches } from '../../api/queries/inbox'
import { useSources } from '../../api/queries/sources'
import { SyncLog } from '../../components/layout/SyncLog'
import { useStartSync } from '../../api/queries/sync'
import { Button } from '../../ui/Button'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { OwlCoin } from '../../ui/OwlCoin'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { createProposal, isBuilding, searchTopics, useEvolutionTopics, type EvolutionTopic, type TopicProposal } from '../evolution/api'
import { ProposalPanel } from '../evolution/ProposalPanel'
import { FollowButton } from '../inbox/FollowButton'
import { ModelsCard } from '../settings/ModelsCard'

type Step = 'model' | 'map' | 'sources' | 'go'

const LABELS: Record<Step, string> = { model: 'Model', map: 'Map', sources: 'Sources', go: 'Go' }

/**
 * The setup guide (R3), on a new account's first visit: admins connect a model, then everyone picks or builds a
 * map, follows a few sources and goes. Every step can be skipped, and Settings → Account brings the guide back.
 */
export function WelcomePage() {
  const user = useCurrentUser()
  const navigate = useNavigate()
  const done = useSetOnboarded()
  const admin = user?.role === 'admin'
  const steps: Step[] = admin ? ['model', 'map', 'sources', 'go'] : ['map', 'sources', 'go']
  const [index, setIndex] = useState(0)
  const [modelOk, setModelOk] = useState<boolean | null>(null)
  const step = steps[index]
  const last = index === steps.length - 1
  const finish = () => done.mutate(true, { onSuccess: () => navigate('/', { replace: true }) })
  const canContinue = step !== 'model' || modelOk === true

  return (
    <div className="min-h-screen bg-bg text-fg">
      <div className="mx-auto grid max-w-[820px] gap-8 px-4 py-10 md:py-14">
        <header className="grid gap-5">
          <div className="flex items-center gap-3">
            <OwlCoin size={36} />
            <div className="grid gap-0.5">
              <h1 className="text-[20px] font-semibold tracking-[-0.01em]">Set up Athena</h1>
              <p className="text-[13px] text-fg-2">
                {admin ? 'A few minutes to connect a model and choose what to follow.' : 'A minute to choose what to follow.'}
              </p>
            </div>
            <Button variant="ghost" size="sm" className="ml-auto" onClick={finish} disabled={done.isPending}>Skip the guide</Button>
          </div>
          <StepRail steps={steps} index={index} />
        </header>

        <main>
          {step === 'model' && <ModelStep ok={modelOk} onTested={setModelOk} />}
          {step === 'map' && <MapStep />}
          {step === 'sources' && <SourcesStep />}
          {step === 'go' && <GoStep admin={admin} />}
        </main>

        <footer className="flex flex-wrap items-center gap-2 border-t border-line pt-5">
          {index > 0 && <Button variant="ghost" onClick={() => setIndex(index - 1)}><ArrowLeft /> Back</Button>}
          {done.isError && <span className="text-[12.5px] text-bad">{apiErrorMessage(done.error, 'That did not save')}</span>}
          <span className="ml-auto flex items-center gap-2">
            {!last && <Button variant="ghost" onClick={() => setIndex(index + 1)}>Skip this step</Button>}
            {last ? (
              <Button variant="primary" onClick={finish} disabled={done.isPending}>{done.isPending ? 'Opening…' : 'Open Athena'} <ArrowRight /></Button>
            ) : (
              <Button variant="primary" onClick={() => setIndex(index + 1)} disabled={!canContinue}
                title={canContinue ? undefined : 'Test the models first, or skip this step'}>
                Continue <ArrowRight />
              </Button>
            )}
          </span>
        </footer>
      </div>
    </div>
  )
}

function StepRail({ steps, index }: { steps: Step[]; index: number }) {
  return (
    <ol className="flex items-center gap-2" aria-label="Steps">
      {steps.map((s, i) => (
        <li key={s} className="flex flex-1 items-center gap-2 last:flex-none" aria-current={i === index ? 'step' : undefined}>
          <span className={cn(
            'grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[11px]',
            i < index ? 'border-accent bg-accent text-on-primary' : i === index ? 'border-accent text-accent' : 'border-line-strong text-fg-3',
          )}>
            {i < index ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : i + 1}
          </span>
          <span className={cn('text-[13px]', i === index ? 'text-fg' : 'text-fg-3')}>{LABELS[s]}</span>
          {i < steps.length - 1 && <span className={cn('h-px min-w-4 flex-1', i < index ? 'bg-accent-line' : 'bg-line')} aria-hidden="true" />}
        </li>
      ))}
    </ol>
  )
}

function StepTitle({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-5 grid gap-1">
      <h2 className="text-[17px] font-semibold text-fg">{title}</h2>
      {children && <p className="max-w-[68ch] text-[13.5px] text-fg-2">{children}</p>}
    </div>
  )
}

// ── 1. model (admins) ────────────────────────────────────────────────

function ModelStep({ ok, onTested }: { ok: boolean | null; onTested: (ok: boolean) => void }) {
  return (
    <section>
      <StepTitle title="Connect a model">
        Every AI feature talks to one OpenAI-compatible server for chat and one for embeddings. The defaults are the local
        llama-server router; point them at OpenAI or another provider instead, save, then test.
      </StepTitle>
      <ModelsCard onTested={onTested} />
      {ok === true && <Notice className="mt-3" title="Both models answered">Summaries, questions and maps will work.</Notice>}
      {ok === false && (
        <Notice tone="warn" className="mt-3" title="A model did not answer">
          Check the address and the model names, and that the model server is running. You can also skip this step and
          come back to it in Settings → Models and keys.
        </Notice>
      )}
    </section>
  )
}

// ── 2. map ───────────────────────────────────────────────────────────

function MapStep() {
  const { data: topics, isLoading } = useEvolutionTopics()
  const [built, setBuilt] = useState<EvolutionTopic | null>(null)
  const maps = topics ?? []

  return (
    <section className="grid gap-6">
      <StepTitle title={maps.length ? 'Follow a map, or build one' : 'Build your first map'}>
        A map traces how a research field developed: the papers it grew from, its milestones and the problems still open.
        {maps.length ? ' Follow the ones you care about; their updates come to your inbox.' : ' Name a field to start.'}
      </StepTitle>
      {isLoading ? <Spinner label="Loading the maps…" /> : maps.length > 0 && (
        <ul className="grid gap-2.5 sm:grid-cols-2">
          {maps.map((t) => <MapCard key={t.slug} topic={t} />)}
        </ul>
      )}
      {built ? (
        <Notice title={`Building the map for ${built.name}`}>
          It usually takes a few minutes and carries on without this page. You follow it already, so your inbox says when it is ready.
        </Notice>
      ) : (
        <BuildMap onBuilt={setBuilt} />
      )}
    </section>
  )
}

function MapCard({ topic: t }: { topic: EvolutionTopic }) {
  const readable = !isBuilding(t.status) && t.status !== 'failed'
  return (
    <li className="grid content-start gap-2 rounded-xl border border-line bg-surface p-3.5">
      <div className="flex items-start gap-2">
        <GitBranch className="mt-0.5 h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
        <div className="grid min-w-0 flex-1 gap-0.5">
          <p className="text-[14px] font-medium text-fg">{t.name}</p>
          {t.description && <p className="line-clamp-2 text-[12.5px] text-fg-2">{t.description}</p>}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {readable ? (
          <span className="font-mono text-[11.5px] text-fg-3 tabular-nums">{t.paper_count ?? 0} papers · {t.milestone_count ?? 0} milestones</span>
        ) : (
          <Chip>{t.status === 'failed' ? 'failed' : 'building'}</Chip>
        )}
        {t.id && <FollowButton target={{ kind: 'map', topic_id: t.id }} className="ml-auto" />}
      </div>
    </li>
  )
}

/** A field's name, then the proposal to check, then the build; an existing map with that name is offered instead. */
function BuildMap({ onBuilt }: { onBuilt: (topic: EvolutionTopic) => void }) {
  const [query, setQuery] = useState('')
  const [pending, setPending] = useState(false)
  const [existing, setExisting] = useState<EvolutionTopic | null>(null)
  const [proposal, setProposal] = useState<TopicProposal | null>(null)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const q = query.trim()
    if (!q) return
    setPending(true)
    setError(null)
    setExisting(null)
    setProposal(null)
    try {
      const found = await searchTopics(q)
      if (found.found && found.match.method === 'alias') setExisting(found.topic)
      else setProposal(await createProposal(q))
    } catch (err) {
      setError(apiErrorMessage(err, 'The search failed. Check that the API and the model server are running.'))
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="grid gap-3">
      <form onSubmit={(e) => void submit(e)} className="flex gap-2">
        <label className="flex h-9 min-w-0 flex-1 items-center gap-2.5 rounded-lg border border-line bg-surface px-3 focus-within:border-accent-line">
          <Search className="h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="A research field, e.g. object tracking or mixture of experts"
            maxLength={200}
            aria-label="Research field"
            className="min-w-0 flex-1 bg-transparent text-[13.5px] text-fg placeholder:text-fg-3 focus:outline-none"
          />
        </label>
        <Button type="submit" variant="secondary" className="h-9" disabled={pending || !query.trim()}>
          {pending ? <Spinner className="h-4 w-4" /> : 'Propose a map'}
        </Button>
      </form>
      {pending && <Spinner label="Looking for papers in OpenAlex…" />}
      {error && <Notice tone="error" title="Something went wrong">{error}</Notice>}
      {existing && (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface px-4 py-3 text-[13px]">
          <span className="min-w-0 flex-1 text-fg-2">There is a map for <span className="text-fg">{existing.name}</span> already.</span>
          {existing.id && <FollowButton target={{ kind: 'map', topic_id: existing.id }} />}
        </div>
      )}
      {proposal && <ProposalPanel key={proposal.id} proposal={proposal} onCancel={() => setProposal(null)} onBuilt={onBuilt} />}
    </div>
  )
}

// ── 3. sources ───────────────────────────────────────────────────────

const CATEGORIES: { id: string; label: string }[] = [
  { id: 'paper', label: 'Papers' },
  { id: 'company', label: 'Lab blogs' },
  { id: 'blog', label: 'Community' },
]

function SourcesStep() {
  const { data: sources, isLoading } = useSources()
  const { data: watches } = useWatches()
  const active = (sources ?? []).filter((s) => s.is_active)
  const following = (watches?.watches ?? []).filter((w) => w.kind === 'source').length
  const groups = [...CATEGORIES, { id: '', label: 'Other' }]
    .map((c) => ({ ...c, sources: active.filter((s) => (c.id ? s.category === c.id : !CATEGORIES.some((k) => k.id === s.category))) }))
    .filter((g) => g.sources.length > 0)

  return (
    <section>
      <StepTitle title="Follow a few sources">
        Every source fills the feed. Following one also brings its new items to your inbox; three or four is a good start.
      </StepTitle>
      {isLoading ? <Spinner label="Loading the sources…" /> : active.length === 0 ? (
        <Notice title="No sources yet">An admin adds them in Settings → Sources.</Notice>
      ) : (
        <div className="grid gap-5">
          {groups.map((g) => (
            <div key={g.label} className="grid gap-2">
              <h3 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">{g.label}</h3>
              <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
                {g.sources.map((s) => (
                  <li key={s.id} className="flex items-center gap-3 px-4 py-2.5">
                    <div className="grid min-w-0 flex-1">
                      <span className="text-[13.5px] text-fg">{s.name}</span>
                      <span className="truncate font-mono text-[11.5px] text-fg-3">{host(s.url)}</span>
                    </div>
                    <FollowButton target={{ kind: 'source', source_id: s.id }} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="text-[12.5px] text-fg-3" aria-live="polite">Following {following} {following === 1 ? 'source' : 'sources'}.</p>
        </div>
      )}
    </section>
  )
}

function host(url: string) {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

// ── 4. go ────────────────────────────────────────────────────────────

function GoStep({ admin }: { admin: boolean }) {
  const { data: watches } = useWatches()
  const [syncing, setSyncing] = useState(false)
  const [syncError, setSyncError] = useState<string | null>(null)
  const all = watches?.watches ?? []
  const maps = all.filter((w) => w.kind === 'map').length
  const sources = all.filter((w) => w.kind === 'source').length

  const startSync = useStartSync()
  const sync = async () => {
    setSyncError(null)
    try {
      await startSync.mutateAsync()
      setSyncing(true)
    } catch (e) {
      setSyncError(apiErrorMessage(e, 'The sync could not start. Is the worker running?'))
    }
  }

  return (
    <section className="grid gap-5">
      <StepTitle title="You're set">
        You follow {maps} {maps === 1 ? 'map' : 'maps'} and {sources} {sources === 1 ? 'source' : 'sources'}. Change what you
        follow, and how often the digest comes, in Settings → Notifications. This guide is under Settings → Account.
      </StepTitle>
      {admin && (
        <div className="grid gap-3 rounded-xl border border-line bg-surface p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="grid min-w-0 flex-1 gap-0.5">
              <p className="text-[14px] font-medium text-fg">Fetch the first papers</p>
              <p className="text-[12.5px] text-fg-2">Sources are fetched every six hours on their own. Start now to fill the feed today.</p>
            </div>
            <Button variant="secondary" onClick={() => void sync()} disabled={syncing}><Download /> {syncing ? 'Fetching' : 'Fetch now'}</Button>
          </div>
          {syncError && <p className="text-[12.5px] text-bad">{syncError}</p>}
          {syncing && <SyncLog />}
        </div>
      )}
    </section>
  )
}
