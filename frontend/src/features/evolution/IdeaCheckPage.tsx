import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, CircleDot, Lightbulb, MoonStar, Sparkle, Sparkles, Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { timeAgo } from '../../components/items/format'
import { Button, ButtonLink } from '../../ui/Button'
import { Chip, type ChipTone } from '../../ui/Chip'
import { EmptyState } from '../../ui/EmptyState'
import { Notice } from '../../ui/Notice'
import { PageHeader } from '../../ui/PageHeader'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import {
  useCreateIdeaCheck,
  useDeleteIdeaCheck,
  useIdeaCheck,
  useIdeaChecks,
  type GapTheme,
  type IdeaCheck,
  type IdeaPaper,
  type IdeaTheme,
} from './api'
import { AddToProjectMenu } from '../projects/AddToProjectMenu'

const STATUS: Record<GapTheme['status'], { label: string; icon: typeof CircleDot; tone: ChipTone }> = {
  persisting: { label: 'Still open', icon: CircleDot, tone: 'warn' },
  new: { label: 'Newly stated', icon: Sparkle, tone: 'accent' },
  addressed: { label: 'Fix claimed', icon: CheckCircle2, tone: 'good' },
  quiet: { label: 'No longer stated', icon: MoonStar, tone: 'neutral' },
}

/** Paste an idea or abstract: the closest papers in the maps, the gaps it touches, and what would be new. */
export function IdeaCheckPage() {
  const [params, setParams] = useSearchParams()
  const selected = params.get('check')
  const [idea, setIdea] = useState('')
  const [verdict, setVerdict] = useState(true)
  const create = useCreateIdeaCheck()
  const current = useIdeaCheck(selected)
  const select = (id: string | null) => setParams(id ? { check: id } : {}, { replace: true })

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const check = await create.mutateAsync({ idea: idea.trim(), verdict }).catch(() => null)
    if (check) select(check.id)
  }

  return (
    <div className="mx-auto max-w-[1200px]">
      <ButtonLink to="/evolution" variant="ghost" size="sm" className="mb-3 -ml-2.5"><ArrowLeft /> Evolution</ButtonLink>
      <PageHeader
        title="Check an idea"
        description="Paste a project idea or an abstract. See the closest papers in your maps, the research gaps it touches and whether they are still open, and what would be new."
      />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="grid min-w-0 gap-6">
          <form onSubmit={onSubmit} className="grid gap-2.5">
            <label htmlFor="idea" className="sr-only">Your idea</label>
            <textarea
              id="idea"
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              rows={6}
              maxLength={4000}
              placeholder="e.g. Fine-tune large language models with 2-bit adapters that keep full-precision accuracy by learning the quantization grid during training."
              className="w-full resize-y rounded-xl border border-line bg-surface px-3.5 py-3 text-[13.5px] leading-relaxed text-fg placeholder:text-fg-3 focus:border-accent-line focus:outline-none"
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" variant="ai" disabled={create.isPending || idea.trim().length < 20}>
                {create.isPending ? <Spinner className="h-4 w-4" /> : <Lightbulb />} Check it
              </Button>
              <label className="flex items-center gap-2 text-[12.5px] text-fg-2">
                <input type="checkbox" checked={verdict} onChange={(e) => setVerdict(e.target.checked)} className="accent-[var(--accent)]" />
                Ask AI for a short verdict
              </label>
              <span className="ml-auto font-mono text-[11.5px] text-fg-3 tabular-nums">{idea.length}/4000</span>
            </div>
            {create.isPending && <p className="text-[12.5px] text-fg-3">Searching every map, then writing the verdict. This takes up to half a minute.</p>}
            {create.error && <Notice tone="error" title="The check failed">{apiErrorMessage(create.error, 'Check that the API and the model server are running.')}</Notice>}
          </form>

          {selected && current.isLoading && <Spinner label="Loading the check…" />}
          {selected && current.error && <Notice tone="error" title="This check could not be loaded">It may have been deleted.</Notice>}
          {current.data && <CheckResult check={current.data} />}
        </div>
        <History selected={selected} onSelect={select} />
      </div>
    </div>
  )
}

function CheckResult({ check }: { check: IdeaCheck }) {
  const { papers, themes, verdict, verdict_error } = check.result
  return (
    <div className="grid gap-6">
      <div className="flex items-start gap-3">
        <blockquote className="min-w-0 flex-1 border-l-2 border-line pl-3 text-[13px] leading-relaxed text-fg-2 whitespace-pre-line">{check.idea}</blockquote>
        <AddToProjectMenu membershipRef={`idea:${check.id}`} item={{ kind: 'idea_check', id: check.id }} />
      </div>
      {verdict && (
        <section className="relative grid gap-3 rounded-xl border border-line bg-surface p-4">
          <span className="ai-ring" aria-hidden="true" />
          <p className="flex items-center gap-1.5 text-[12px] text-fg-3"><Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" /> Verdict written by AI from the papers and gaps below; numbers refer to the papers</p>
          <Verdict title="Closest prior work" text={verdict.closest} />
          <Verdict title="What would be new" text={verdict.new} />
          {verdict.gaps && <Verdict title="Gaps it would address" text={verdict.gaps} />}
        </section>
      )}
      {verdict_error && <Notice tone="warn" title="No verdict">The model did not answer ({verdict_error}). The search results below still stand.</Notice>}

      <section className="grid gap-2.5">
        <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Closest papers in your maps</h2>
        {papers.length === 0 ? (
          <p className="text-[13px] text-fg-2">No paper in your maps comes close. Either the idea is far from them, or no map covers its field yet.</p>
        ) : (
          <ol className="grid gap-px overflow-hidden rounded-xl border border-line bg-line">
            {papers.map((p, i) => <PaperHit key={p.id} paper={p} n={i + 1} />)}
          </ol>
        )}
      </section>

      <section className="grid gap-2.5">
        <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Research gaps it touches</h2>
        {themes.length === 0 ? (
          <p className="text-[13px] text-fg-2">
            No gap theme matches closely. Gap themes exist only for maps whose papers' full text has been read.
          </p>
        ) : (
          <ul className="grid gap-3">{themes.map((t) => <ThemeHit key={t.id} theme={t} />)}</ul>
        )}
      </section>
    </div>
  )
}

function Verdict({ title, text }: { title: string; text: string }) {
  return (
    <div className="grid gap-0.5">
      <h3 className="text-[12.5px] font-medium text-fg">{title}</h3>
      <p className="max-w-[80ch] text-[13.5px] leading-relaxed text-fg-2">{text}</p>
    </div>
  )
}

function Similarity({ score }: { score: number }) {
  return (
    <span className="flex items-center gap-1.5 font-mono text-[11.5px] text-fg-3 tabular-nums" title="Similarity to the idea (cosine)">
      <span className="h-1 w-10 overflow-hidden rounded-full bg-surface-2"><span className="block h-full bg-accent" style={{ width: `${Math.max(0, Math.min(1, (score - 0.4) / 0.45)) * 100}%` }} /></span>
      {score.toFixed(2)}
    </span>
  )
}

function PaperHit({ paper: p, n }: { paper: IdeaPaper; n: number }) {
  return (
    <li className="grid gap-1.5 bg-surface px-4 py-3">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 font-mono text-[12px] text-fg-3 tabular-nums">[{n}]</span>
        <a href={p.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 text-[13.5px] leading-snug font-medium text-fg hover:underline">{p.title}</a>
        <Similarity score={p.score} />
      </div>
      <div className="flex flex-wrap items-center gap-1.5 pl-7 text-[12px] text-fg-3">
        <span>{[p.year, p.authors.join(', ')].filter(Boolean).join(' · ')}</span>
        {p.maps.map((m) => (
          <Link key={m.topic} to={`/evolution/${m.topic}?paper=${p.id}`}>
            <Chip tone={m.milestone ? 'accent' : 'neutral'} className="hover:opacity-80">{m.topic_name}{m.milestone && ' · milestone'}</Chip>
          </Link>
        ))}
      </div>
    </li>
  )
}

function ThemeHit({ theme: t }: { theme: IdeaTheme }) {
  const status = STATUS[t.status]
  const Icon = status.icon
  return (
    <li className="grid gap-2 rounded-xl border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[14px] font-medium text-fg">{t.label}</span>
        <Chip tone={status.tone}><Icon aria-hidden="true" />{status.label}</Chip>
        <Link to={`/evolution/${t.topic}?tab=gaps`} className="text-[12px] text-fg-3 hover:text-fg hover:underline">{t.topic_name}</Link>
        <span className="ml-auto"><Similarity score={t.score} /></span>
      </div>
      <p className="border-l-2 border-line pl-2.5 text-[13px] leading-relaxed text-fg-2 italic">“{t.example.sentence}”</p>
      <p className="text-[12px] text-fg-3">
        {t.example.paper && <>About {t.example.paper.title} ({t.example.paper.year}) · </>}
        stated {t.size} {t.size === 1 ? 'time' : 'times'}{t.first_year && ` from ${t.first_year}`}{t.last_year && t.last_year !== t.first_year && ` to ${t.last_year}`}
        {t.hits > 1 && ` · ${t.hits} statements match the idea`}
      </p>
      {t.fixed_by.length > 0 && (
        <p className="text-[12.5px] text-fg-2">
          <span className="text-good">Fix claimed by</span> {t.fixed_by.map((p) => `${p.title} (${p.year})`).join('; ')}
        </p>
      )}
      {t.maybe_addressed_by.length > 0 && (
        <p className="text-[12.5px] text-fg-2">
          <span className="text-fg-3">Later papers whose text matches it:</span> {t.maybe_addressed_by.map((p) => p.title).join('; ')}
        </p>
      )}
    </li>
  )
}

function History({ selected, onSelect }: { selected: string | null; onSelect: (id: string | null) => void }) {
  const { data, isLoading } = useIdeaChecks()
  const remove = useDeleteIdeaCheck()
  return (
    <aside className="grid gap-2.5 lg:sticky lg:top-4">
      <h2 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Your checks</h2>
      {isLoading ? (
        <Spinner />
      ) : !data?.length ? (
        <EmptyState icon={Lightbulb} title="No checks yet">Checks you run are kept here.</EmptyState>
      ) : (
        <ul className="grid gap-1.5">
          {data.map((c) => (
            <li key={c.id} className={cn('group relative rounded-lg border px-3 py-2 transition-colors', selected === c.id ? 'border-accent-line bg-accent-soft' : 'border-line bg-surface hover:border-line-strong')}>
              <button type="button" onClick={() => onSelect(c.id)} className="grid w-full gap-1 pr-6 text-left">
                <span className="line-clamp-2 text-[12.5px] leading-snug text-fg">{c.idea}</span>
                <span className="text-[11.5px] text-fg-3">
                  {timeAgo(c.created_at)} · {c.papers} papers · {c.open_themes} open {c.open_themes === 1 ? 'gap' : 'gaps'}
                </span>
              </button>
              <Button
                variant="ghost"
                size="icon-sm"
                className="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                aria-label="Delete this check"
                onClick={() => remove.mutate(c.id, { onSuccess: () => selected === c.id && onSelect(null) })}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  )
}
