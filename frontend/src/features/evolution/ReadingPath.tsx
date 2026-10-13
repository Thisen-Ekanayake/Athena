import { useState } from 'react'
import { BookOpen, Check, ExternalLink, Sparkles } from 'lucide-react'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { useMarkRead, useReadingPath, type ReadingStep } from './api'

const SIZES = [
  { value: '5', label: '5' },
  { value: '10', label: '10' },
  { value: '15', label: '15' },
  { value: '20', label: '20' },
]

interface ReadingPathProps {
  slug: string
  onSelect: (id: string) => void
}

/** Learn the field in n papers: a survey, then the milestones in the order they appeared. */
export function ReadingPath({ slug, onSelect }: ReadingPathProps) {
  const [n, setN] = useState(10)
  const { data, isLoading, error } = useReadingPath(slug, n)
  const markRead = useMarkRead(slug, n)

  if (isLoading && !data) return <Spinner label="Choosing the papers…" />
  if (error || !data) return <Notice tone="error" title="The reading path could not be loaded">Check that the API is running.</Notice>

  const entries = [...(data.survey ? [data.survey] : []), ...data.steps]
  const read = entries.filter((e) => e.read).length
  if (entries.length === 0) {
    return <Notice title="No reading path yet">This map has no milestones or surveys to read. Pin milestones from the map to build one.</Notice>
  }
  const toggle = (step: ReadingStep) => markRead.mutate({ paperId: step.id, read: !step.read })

  return (
    <div className="grid max-w-4xl gap-5">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="grid gap-0.5">
          <h2 className="text-[16px] font-semibold text-fg">Learn {data.topic.name} in {entries.length} papers</h2>
          <p className="text-[13px] text-fg-2">
            A survey first, then the milestones in the order they appeared, at least one from each era.
          </p>
        </div>
        <span className="ml-auto flex items-center gap-2 text-[12.5px] text-fg-2">
          Papers
          <Segmented label="Papers on the path" value={String(n)} options={SIZES} onChange={(v) => setN(Number(v))} />
        </span>
      </div>

      <div className="flex items-center gap-3" aria-live="polite">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuemin={0} aria-valuemax={entries.length} aria-valuenow={read} aria-label="Papers read">
          <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${(100 * read) / entries.length}%` }} />
        </div>
        <span className="font-mono text-[12px] text-fg-3 tabular-nums">{read} of {entries.length} read</span>
      </div>

      {data.notes_error && (
        <Notice tone="warn" title="The notes could not be written">
          The model server did not answer ({data.notes_error}). The papers are still in order; reload later for the notes.
        </Notice>
      )}

      <section className="relative rounded-xl border border-line bg-surface">
        <span className="ai-ring" data-active={data.notes_pending} aria-hidden="true" />
        <p className="flex items-center gap-1.5 border-b border-line px-4 py-2.5 text-[12px] text-fg-3">
          <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden="true" />
          {data.notes_pending ? 'Writing a line on why each paper matters…' : 'Notes on why each paper matters are written by AI from its abstract.'}
        </p>
        <ol className="divide-y divide-line">
          {data.survey && (
            <Step step={data.survey} label="Start here" onSelect={onSelect} onToggle={toggle} pending={data.notes_pending} />
          )}
          {data.steps.map((s) => (
            <Step key={s.id} step={s} onSelect={onSelect} onToggle={toggle} pending={data.notes_pending} />
          ))}
        </ol>
      </section>

      {data.other_surveys.length > 0 && (
        <section className="grid gap-2">
          <h3 className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Other surveys</h3>
          <ul className="grid gap-1.5">
            {data.other_surveys.map((s) => (
              <li key={s.id} className="flex items-baseline gap-2 text-[13px]">
                <span className="font-mono text-[12px] text-fg-3 tabular-nums">{s.year ?? '—'}</span>
                <button type="button" onClick={() => onSelect(s.id)} className="text-left text-fg-2 hover:text-fg hover:underline">{s.title}</button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

interface StepProps {
  step: ReadingStep
  label?: string
  pending: boolean
  onSelect: (id: string) => void
  onToggle: (step: ReadingStep) => void
}

function Step({ step, label, pending, onSelect, onToggle }: StepProps) {
  return (
    <li className="flex gap-3 px-4 py-3.5">
      <button
        type="button"
        onClick={() => onToggle(step)}
        aria-pressed={step.read}
        aria-label={step.read ? `Mark “${step.title}” unread` : `Mark “${step.title}” read`}
        title={step.read ? 'Read: click to undo' : 'Mark as read'}
        className={cn(
          'mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full border font-mono text-[11px] tabular-nums transition-colors',
          step.read ? 'border-accent bg-accent text-on-primary' : 'border-line-strong text-fg-3 hover:border-accent-line hover:text-fg',
        )}
      >
        {step.read ? <Check className="h-3.5 w-3.5" aria-hidden="true" /> : step.position}
      </button>
      <div className="grid min-w-0 flex-1 gap-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          {label && <Chip tone="accent"><BookOpen aria-hidden="true" />{label}</Chip>}
          <span className="font-mono text-[12px] text-fg-3 tabular-nums">{step.year ?? '—'}</span>
          {step.named_method && <Chip>{step.named_method}</Chip>}
          {step.kind === 'survey' && !label && <Chip>Survey</Chip>}
          {step.builds_on.length > 0 && (
            <span className="text-[12px] text-fg-3" title="Earlier papers on this path that it cites">
              builds on {step.builds_on.map((p) => `#${p}`).join(', ')}
            </span>
          )}
          {step.addresses.length > 0 && (
            <span className="text-[12px] text-accent-ink" title="It states a limitation of these earlier papers and takes it on">
              takes on a limitation of {step.addresses.map((p) => `#${p}`).join(', ')}
            </span>
          )}
        </div>
        <div className="flex items-start gap-2">
          <button
            type="button"
            onClick={() => onSelect(step.id)}
            className={cn('text-left text-[14px] leading-snug font-medium hover:underline', step.read ? 'text-fg-2' : 'text-fg')}
            title="Show it in the map"
          >
            {step.title}
          </button>
          <a href={step.url} target="_blank" rel="noopener noreferrer" className="mt-0.5 shrink-0 text-fg-3 hover:text-fg" aria-label={`Open “${step.title}”`}>
            <ExternalLink className="h-3.5 w-3.5" />
          </a>
        </div>
        {step.why ? (
          <p className="max-w-[75ch] text-[13px] leading-relaxed text-fg-2">{step.why}</p>
        ) : step.why === null && pending ? (
          <span className="h-3.5 w-2/3 animate-pulse rounded bg-surface-2" aria-label="Writing the note" />
        ) : null}
        {(step.authors.length > 0 || step.venue) && (
          <p className="truncate text-[12px] text-fg-3">{[step.authors.join(', '), step.venue].filter(Boolean).join(' · ')}</p>
        )}
      </div>
    </li>
  )
}
