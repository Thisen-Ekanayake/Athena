import { useState, type FormEvent } from 'react'
import { ArrowDown, ArrowUp, Check, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import {
  useAddConfTopic, useConferences, useDeleteConfTopic, useEditConfTopic, useSyncConferences, type ConfTopic,
} from '../../api/queries/conferences'
import { timeAgo } from '../../components/items/format'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { PipelineProgress } from './ConferencesTab'

/** Admin: read the ACL Anthology now, and the topic list papers are sorted into. */
export function ConferenceSettings() {
  const { data, isLoading, error } = useConferences()
  const sync = useSyncConferences()
  if (isLoading) return <Spinner label="Loading…" />
  if (error || !data) return <Notice tone="error">{apiErrorMessage(error, 'The conference settings did not load.')}</Notice>
  return (
    <section className="grid gap-8">
      <div className="grid gap-3">
        <div className="grid gap-1">
          <h2 className="text-[16px] font-semibold text-fg">Conferences</h2>
          <p className="max-w-[68ch] text-[13px] text-fg-2">
            The ACL family's main proceedings, Findings and journals, read from the ACL Anthology every Sunday (only
            when it changed). Papers are embedded and sorted into the topics below as backlog work on the GPU, which
            gives way to chats and pauses with the other background work. Citation counts come from OpenAlex and
            Semantic Scholar: weekly for the last two years' papers, monthly for older ones.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" size="sm" onClick={() => sync.mutate()} disabled={sync.isPending}>
            {sync.isPending ? <Spinner className="h-3.5 w-3.5" /> : <RefreshCw />} Read the Anthology now
          </Button>
          <span className="text-[12.5px] text-fg-3">
            {data.progress.papers.toLocaleString()} papers
            {data.status.last_sync ? ` · last read ${timeAgo(data.status.last_sync)}` : ''}
          </span>
        </div>
        {sync.error && <Notice tone="error">{apiErrorMessage(sync.error, 'The sync did not start.')}</Notice>}
        <PipelineProgress progress={data.progress} status={data.status} />
      </div>
      <TopicList topics={data.topics} />
    </section>
  )
}

function TopicList({ topics }: { topics: ConfTopic[] }) {
  const add = useAddConfTopic()
  const edit = useEditConfTopic()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [editing, setEditing] = useState<number | null>(null)

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim().length < 2) return
    add.mutate({ name: name.trim(), description: description.trim() }, { onSuccess: () => { setName(''); setDescription('') } })
  }
  // Swapping two neighbours' positions; positions may have gaps, so each takes the other's.
  const move = (i: number, by: -1 | 1) => {
    const a = topics[i]
    const b = topics[i + by]
    if (!a || !b) return
    const [pa, pb] = a.position === b.position ? [i + by, i] : [b.position, a.position]
    edit.mutate({ id: a.id, position: pa })
    edit.mutate({ id: b.id, position: pb })
  }

  return (
    <div className="grid gap-3">
      <div className="grid gap-1">
        <h3 className="text-[14px] font-semibold text-fg">Topics</h3>
        <p className="max-w-[68ch] text-[13px] text-fg-2">
          Each paper goes to the topic whose name and description are nearest its title and abstract. A change to a
          name or description, a new topic or a removed one sorts every paper again (a few minutes, nothing is
          embedded again) and rewrites the summaries whose numbers moved. The order is the order of lists.
        </p>
      </div>
      <Card>
        <ul>
          {topics.map((t, i) => (
            <li key={t.id} className="border-b border-line px-3 py-2 last:border-b-0">
              {editing === t.id
                ? <TopicEditor topic={t} onDone={() => setEditing(null)} />
                : (
                  <div className="flex items-start gap-2">
                    <div className="grid min-w-0 flex-1 gap-0.5">
                      <p className="text-[13px] font-medium text-fg">{t.name}</p>
                      {t.description && <p className="text-[12px] text-fg-3">{t.description}</p>}
                    </div>
                    <div className="flex shrink-0 items-center">
                      <Button variant="ghost" size="icon-sm" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move ${t.name} up`}><ArrowUp /></Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => move(i, 1)} disabled={i === topics.length - 1} aria-label={`Move ${t.name} down`}><ArrowDown /></Button>
                      <Button variant="ghost" size="icon-sm" onClick={() => setEditing(t.id)} aria-label={`Edit ${t.name}`}><Pencil /></Button>
                      <DeleteTopic topic={t} />
                    </div>
                  </div>
                )}
            </li>
          ))}
        </ul>
        <form onSubmit={submit} className="grid gap-2 border-t border-line p-3 sm:grid-cols-[14rem_1fr_auto]">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="New topic, e.g. Legal NLP" aria-label="New topic name" maxLength={80} />
          <input className={inputClass} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What it covers, in a few words" aria-label="New topic description" maxLength={400} />
          <Button type="submit" variant="secondary" size="md" disabled={name.trim().length < 2 || add.isPending}>
            {add.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Plus />} Add
          </Button>
        </form>
        {(add.error || edit.error) && <p className="px-3 pb-3 text-[12px] text-bad">{apiErrorMessage(add.error ?? edit.error, 'Not saved.')}</p>}
      </Card>
    </div>
  )
}

function TopicEditor({ topic, onDone }: { topic: ConfTopic; onDone: () => void }) {
  const edit = useEditConfTopic()
  const [name, setName] = useState(topic.name)
  const [description, setDescription] = useState(topic.description)
  const save = (e: FormEvent) => {
    e.preventDefault()
    edit.mutate({ id: topic.id, name: name.trim(), description: description.trim() }, { onSuccess: onDone })
  }
  return (
    <form onSubmit={save} className="grid gap-2">
      <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} aria-label="Topic name" maxLength={80} autoFocus />
      <textarea className={cn(inputClass, 'h-auto min-h-16 py-1.5')} value={description} onChange={(e) => setDescription(e.target.value)} aria-label="Topic description" maxLength={400} />
      <div className="flex items-center gap-2">
        <Button type="submit" variant="secondary" size="sm" disabled={name.trim().length < 2 || edit.isPending}><Check /> Save</Button>
        <Button variant="ghost" size="sm" onClick={onDone}><X /> Cancel</Button>
        {edit.error && <span className="text-[12px] text-bad">{apiErrorMessage(edit.error, 'Not saved.')}</span>}
      </div>
    </form>
  )
}

function DeleteTopic({ topic }: { topic: ConfTopic }) {
  const remove = useDeleteConfTopic()
  const [sure, setSure] = useState(false)
  if (!sure) return <Button variant="ghost" size="icon-sm" onClick={() => setSure(true)} aria-label={`Remove ${topic.name}`}><Trash2 /></Button>
  return (
    <span className="flex items-center gap-1 pl-1 text-[12px] text-fg-2">
      Remove?
      <Button variant="ghost" size="icon-sm" onClick={() => remove.mutate(topic.id)} aria-label={`Yes, remove ${topic.name}`} disabled={remove.isPending}><Check /></Button>
      <Button variant="ghost" size="icon-sm" onClick={() => setSure(false)} aria-label="Keep it"><X /></Button>
    </span>
  )
}
