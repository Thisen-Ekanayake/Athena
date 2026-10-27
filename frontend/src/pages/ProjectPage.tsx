import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  BookOpen, FileText, GitBranch, Image as ImageIcon, Lightbulb, Library, MessageSquare, MoreHorizontal, NotebookPen, Pin,
  Plus, RefreshCw, ScrollText, Upload, X,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { apiErrorMessage } from '../api/error'
import { useCreateArtifact } from '../api/queries/artifacts'
import { createChat, type ChatSummary } from '../api/queries/chats'
import {
  fileUrl, uploadChatFiles, useDeleteFile, useDeleteProject, useProject, useReindexProject, useRemoveFromProject,
  useUpdateProject, useUploadProjectFiles, type IndexStatus, type ItemKind, type Project,
} from '../api/queries/projects'
import { useChatStreams } from '../store/chatStore'
import { Button } from '../ui/Button'
import { Card, CardHeader } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { Notice } from '../ui/Notice'
import { Popover } from '../ui/Popover'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'
import { inputClass } from '../ui/inputClass'
import { ArtifactPanel } from '../features/chat/ArtifactPanel'
import { ChatActions, HIDE_ON_HOVER, RenameField, SHOW_ON_HOVER } from '../features/chat/ChatActions'
import { Composer, type Outgoing } from '../features/chat/Composer'
import { AddKnowledge } from '../features/projects/AddKnowledge'

const KIND_ICONS: Record<ItemKind, typeof FileText> = { paper: BookOpen, map: GitBranch, review: ScrollText, idea_check: Lightbulb, list: Library }
const KIND_LABELS: Record<ItemKind, string> = { paper: 'Paper', map: 'Map', review: 'Review', idea_check: 'Idea check', list: 'Saved list' }

function IndexChip({ status, error }: { status: IndexStatus; error?: string | null }) {
  if (status === 'pending') return <Chip tone="neutral"><Spinner className="h-3 w-3" />Reading</Chip>
  if (status === 'failed') return <span title={error ?? undefined}><Chip tone="bad">Not searchable</Chip></span>
  return null
}

function Header({ project }: { project: Project }) {
  const update = useUpdateProject(project.id)
  const remove = useDeleteProject()
  const navigate = useNavigate()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState({ name: project.name, description: project.description })

  if (editing) {
    return (
      <form className="grid gap-2 pb-6" onSubmit={(e) => {
        e.preventDefault()
        update.mutate(form, { onSuccess: () => setEditing(false) })
      }}>
        <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} aria-label="Name" className={cn(inputClass, 'h-9 text-[16px] font-medium')} />
        <textarea value={form.description} onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))} aria-label="Description" rows={2} placeholder="What is this project for?" className={cn(inputClass, 'h-auto py-1.5')} />
        <div className="flex gap-2">
          <Button type="submit" variant="primary" size="sm" disabled={!form.name.trim() || update.isPending}>Save</Button>
          <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
        </div>
      </form>
    )
  }
  return (
    <header className="flex items-start gap-3 pb-6">
      <div className="grid min-w-0 flex-1 gap-1">
        <Link to="/projects" className="text-[12px] text-fg-3 hover:text-fg-2">Projects</Link>
        <h1 className="text-[22px] font-semibold tracking-[-0.015em] text-fg">{project.name}</h1>
        {project.description && <p className="max-w-2xl text-fg-2">{project.description}</p>}
      </div>
      <Popover
        label="Project actions"
        width={200}
        trigger={({ ref, open, toggle }) => <Button ref={ref} variant="ghost" size="icon" onClick={toggle} aria-expanded={open} aria-label="Project actions"><MoreHorizontal /></Button>}
      >
        {(close) => (
          <div className="grid py-1 text-[13px]">
            <button type="button" className="px-3 py-1.5 text-left hover:bg-surface-2" onClick={() => {
              setForm({ name: project.name, description: project.description })
              setEditing(true)
              close()
            }}>Rename or describe</button>
            <button type="button" className="px-3 py-1.5 text-left text-bad hover:bg-surface-2" onClick={() => {
              close()
              if (window.confirm(`Delete “${project.name}” with its ${project.counts.chats} chats, files and artifacts? Papers, maps and reviews stay in Athena.`)) {
                remove.mutate(project.id, { onSuccess: () => navigate('/projects') })
              }
            }}>Delete project</button>
          </div>
        )}
      </Popover>
    </header>
  )
}

function Instructions({ project }: { project: Project }) {
  const update = useUpdateProject(project.id)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(project.instructions)
  return (
    <Card>
      <CardHeader icon={ScrollText} title="Instructions" action={!editing && (
        <Button variant="ghost" size="sm" onClick={() => {
          setText(project.instructions)
          setEditing(true)
        }}>{project.instructions ? 'Edit' : 'Add'}</Button>
      )} />
      <div className="px-4 pb-4">
        {editing ? (
          <div className="grid gap-2">
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={6} autoFocus aria-label="Instructions"
              placeholder="How chats in this project should answer: tone, what to focus on, citation style, what you already know…"
              className={cn(inputClass, 'h-auto py-2 leading-relaxed')} />
            <div className="flex gap-2">
              <Button variant="primary" size="sm" disabled={update.isPending} onClick={() => update.mutate({ instructions: text }, { onSuccess: () => setEditing(false) })}>Save</Button>
              <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
            </div>
          </div>
        ) : project.instructions ? (
          <p className="line-clamp-6 text-[13px] whitespace-pre-wrap text-fg-2">{project.instructions}</p>
        ) : (
          <p className="text-[12.5px] text-fg-3">Tell the model how to work in this project. Every chat here follows them.</p>
        )}
      </div>
    </Card>
  )
}

function Knowledge({ project }: { project: Project }) {
  const upload = useUploadProjectFiles(project.id)
  const removeItem = useRemoveFromProject()
  const removeFile = useDeleteFile()
  const reindex = useReindexProject(project.id)
  const fileRef = useRef<HTMLInputElement>(null)
  const total = project.items.length + project.files.length
  return (
    <Card>
      <CardHeader icon={Library} title={`Knowledge${total ? ` · ${total}` : ''}`} action={
        <div className="flex items-center gap-0.5">
          {total > 0 && <Button variant="ghost" size="icon-sm" title="Read everything again (after a map was rebuilt, say)" aria-label="Read everything again" disabled={reindex.isPending} onClick={() => reindex.mutate()}><RefreshCw /></Button>}
          <input ref={fileRef} type="file" multiple className="hidden" accept=".pdf,.txt,.md,.markdown,.csv,.json,.tex,.bib,.png,.jpg,.jpeg,.webp,.gif,application/pdf,text/*,image/*"
            onChange={(e) => {
              if (e.target.files?.length) upload.mutate(Array.from(e.target.files))
              e.target.value = ''
            }} />
          <Button variant="ghost" size="icon-sm" title="Upload PDFs, text files or images" aria-label="Upload files" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
            {upload.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Upload />}
          </Button>
          <Popover label="Add to the project" width={400} estHeight={420}
            trigger={({ ref, open, toggle }) => <Button ref={ref} variant="ghost" size="icon-sm" onClick={toggle} aria-expanded={open} aria-label="Add papers, maps and more" title="Add papers, maps, reviews…"><Plus /></Button>}>
            <AddKnowledge project={project} />
          </Popover>
        </div>
      } />
      {upload.isError && <p className="px-4 pb-2 text-[12px] text-bad">{apiErrorMessage(upload.error, 'The files could not be uploaded.')}</p>}
      {total === 0 ? (
        <p className="px-4 pb-4 text-[12.5px] text-fg-3">
          Add papers, maps, reviews and your own files. Chats here search them and cite what they use.
        </p>
      ) : (
        <ul className="grid grid-cols-[minmax(0,1fr)] pb-2">
          {project.items.map((i) => {
            const Icon = KIND_ICONS[i.kind]
            const title = i.link ? <Link to={i.link} className="hover:underline">{i.title}</Link>
              : i.url ? <a href={i.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{i.title}</a> : i.title
            return (
              <li key={i.id} className="group flex items-start gap-2.5 px-4 py-1.5 hover:bg-surface-2">
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-3" aria-label={KIND_LABELS[i.kind]} />
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 text-[13px] text-fg">{title}</span>
                  {i.subtitle && <span className="block truncate text-[11.5px] text-fg-3">{i.subtitle}</span>}
                </span>
                <IndexChip status={i.index_status} error={i.index_error} />
                <button type="button" onClick={() => removeItem.mutate({ projectId: project.id, itemId: i.id })} aria-label={`Remove ${i.title}`} title="Remove from the project"
                  className="rounded p-0.5 text-fg-3 opacity-0 group-hover:opacity-100 hover:text-fg focus:opacity-100"><X className="h-3.5 w-3.5" /></button>
              </li>
            )
          })}
          {project.files.map((f) => {
            const Icon = f.kind === 'image' ? ImageIcon : FileText
            return (
              <li key={f.id} className="group flex items-start gap-2.5 px-4 py-1.5 hover:bg-surface-2">
                <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <a href={fileUrl(f.id)} target="_blank" rel="noopener noreferrer" className="block truncate text-[13px] text-fg hover:underline">{f.filename}</a>
                  <span className="block truncate text-[11.5px] text-fg-3">
                    {f.status === 'failed' ? <span className="text-bad">{f.error}</span>
                      : [f.kind === 'pdf' && f.pages ? `${f.pages} pages` : null, f.kind !== 'image' ? `${f.chars.toLocaleString()} characters` : 'Image', `${Math.max(1, Math.round(f.size / 1024))} KB`].filter(Boolean).join(' · ')}
                  </span>
                </span>
                {f.status === 'ready' && <IndexChip status={f.index_status} />}
                <button type="button" onClick={() => removeFile.mutate(f.id)} aria-label={`Delete ${f.filename}`} title="Delete the file"
                  className="rounded p-0.5 text-fg-3 opacity-0 group-hover:opacity-100 hover:text-fg focus:opacity-100"><X className="h-3.5 w-3.5" /></button>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

function Artifacts({ project, onOpen }: { project: Project; onOpen: (id: string) => void }) {
  const create = useCreateArtifact()
  return (
    <Card>
      <CardHeader icon={NotebookPen} title={`Artifacts${project.artifacts.length ? ` · ${project.artifacts.length}` : ''}`} action={
        <Button variant="ghost" size="icon-sm" aria-label="New artifact" title="Write a new artifact yourself" disabled={create.isPending}
          onClick={() => create.mutate({ title: 'Untitled', content: '', project_id: project.id }, { onSuccess: (a) => onOpen(a.id) })}><Plus /></Button>
      } />
      {project.artifacts.length === 0 ? (
        <p className="px-4 pb-4 text-[12.5px] text-fg-3">Documents the model writes in this project’s chats (drafts, notes, tables) collect here.</p>
      ) : (
        <ul className="grid grid-cols-[minmax(0,1fr)] pb-2">
          {project.artifacts.map((a) => (
            <li key={a.id}>
              <button type="button" onClick={() => onOpen(a.id)} className="flex w-full items-center gap-2.5 px-4 py-1.5 text-left hover:bg-surface-2">
                <NotebookPen className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-fg">{a.title}</span>
                  <span className="block text-[11.5px] text-fg-3">v{a.version} · {formatDistanceToNow(new Date(a.updated_at), { addSuffix: true })}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  )
}

/** One of the project's chats. Hovered, its menu (rename, archive, delete) and pin take the date's place. */
function ChatRow({ chat }: { chat: ChatSummary }) {
  const [renaming, setRenaming] = useState(false)
  return (
    <li className="group flex h-12 items-center gap-3 pr-3 hover:bg-surface-2">
      {renaming ? (
        <span className="flex flex-1 items-center gap-3 pl-4">
          <MessageSquare className="h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
          <RenameField chat={chat} onDone={() => setRenaming(false)} className="h-8 text-[13.5px]" />
        </span>
      ) : (
        <Link to={`/chats/${chat.id}`} className="flex h-full min-w-0 flex-1 items-center gap-3 pl-4">
          <MessageSquare className="h-4 w-4 shrink-0 text-fg-3" aria-hidden="true" />
          <span className="min-w-0 flex-1 truncate text-[13.5px] text-fg">{chat.title}</span>
          {chat.pinned && <Pin className="h-3 w-3 shrink-0 text-fg-3" aria-label="Pinned" />}
          <span className={cn('shrink-0 text-[12px] text-fg-3', HIDE_ON_HOVER)}>{formatDistanceToNow(new Date(chat.updated_at), { addSuffix: true })}</span>
        </Link>
      )}
      {!renaming && (
        <span className={cn('shrink-0 items-center gap-0.5', SHOW_ON_HOVER)}>
          <ChatActions chat={chat} size="md" align="end" onRename={() => setRenaming(true)} />
        </span>
      )}
    </li>
  )
}

/** A project: start a chat in it, its chats, and on the side its instructions, knowledge and artifacts. */
export function ProjectPage() {
  const { id } = useParams()
  const project = useProject(id)
  const navigate = useNavigate()
  const send = useChatStreams((s) => s.send)
  const artifactId = useChatStreams((s) => s.artifactId)
  const openArtifact = useChatStreams((s) => s.openArtifact)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => () => openArtifact(null), [id, openArtifact])

  if (project.isLoading) return <Spinner label="Opening the project…" />
  if (!project.data) return <Notice tone="error" title="Project not found">It may have been deleted. <Link to="/projects" className="underline">All projects</Link></Notice>
  const p = project.data

  const start = async (m: Outgoing) => {
    setBusy(true)
    setError(null)
    try {
      const chat = await createChat({ project_id: p.id, model: m.model, effort: m.effort })
      const files = m.files.length ? await uploadChatFiles(chat.id, m.files) : []
      navigate(`/chats/${chat.id}`)
      void send(chat.id, { content: m.text, model: m.model, effort: m.effort, attachment_ids: files.map((f) => f.id) },
        { question: m.text, attachments: files.map((f) => ({ id: f.id, filename: f.filename, kind: f.kind })) })
    } catch (e) {
      setError(apiErrorMessage(e, 'The chat could not be started.'))
      setBusy(false)
    }
  }

  return (
    <div className={cn('mx-auto max-w-6xl', artifactId && 'xl:pr-[min(46vw,640px)]')}>
      <Header project={p} />
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4">
          {error && <Notice tone="error" title="Not started">{error}</Notice>}
          <Composer onSend={start} streaming={busy} placeholder={`Start a chat in ${p.name}…`} />
          {p.chats.length > 0 ? (
            <ul className="grid divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
              {p.chats.map((c) => <ChatRow key={c.id} chat={c} />)}
            </ul>
          ) : (
            <p className="px-1 text-[13px] text-fg-3">No chats in this project yet. Ask something above; the answer will draw on what you add on the right.</p>
          )}
        </div>
        <aside className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4">
          <Instructions project={p} />
          <Knowledge project={p} />
          <Artifacts project={p} onOpen={openArtifact} />
        </aside>
      </div>
      {artifactId && (
        <ArtifactPanel key={artifactId} id={artifactId} onClose={() => openArtifact(null)}
          className="fixed inset-y-0 right-0 z-40 w-full shadow-pop sm:w-[min(100vw,560px)] xl:w-[min(46vw,640px)] xl:shadow-none" />
      )}
    </div>
  )
}
