import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Archive, ArchiveRestore, Check, FolderInput, FolderKanban, MoreHorizontal, Pencil, Pin, PinOff, Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../api/error'
import { createChat, useChat, useDeleteChat, useUpdateChat, type Chat } from '../api/queries/chats'
import { uploadChatFiles, useProject, useProjects } from '../api/queries/projects'
import { useChatStreams, type Draft } from '../store/chatStore'
import { Button } from '../ui/Button'
import { Notice } from '../ui/Notice'
import { Popover } from '../ui/Popover'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'
import { inputClass } from '../ui/inputClass'
import { ArtifactPanel } from '../features/chat/ArtifactPanel'
import { Composer, type Outgoing } from '../features/chat/Composer'
import { AssistantMessage, UserMessage, type AssistantTurn } from '../features/chat/MessageView'

/** A chat: its messages, the one being answered, and the composer; artifacts open beside it. ``/chats/new``
 * starts one (``?project=`` puts it in a project). */
export function ChatPage() {
  const { id } = useParams()
  const artifactId = useChatStreams((s) => s.artifactId)
  const openArtifact = useChatStreams((s) => s.openArtifact)

  useEffect(() => () => openArtifact(null), [id, openArtifact])

  return (
    <div className={cn('mx-auto w-full transition-[padding]', artifactId && 'xl:pr-[min(46vw,640px)]')}>
      {id && id !== 'new' ? <ChatView key={id} id={id} /> : <NewChat />}
      {artifactId && (
        <ArtifactPanel
          key={artifactId}
          id={artifactId}
          onClose={() => openArtifact(null)}
          className="fixed inset-y-0 right-0 z-40 w-full shadow-pop sm:w-[min(100vw,560px)] xl:w-[min(46vw,640px)] xl:shadow-none"
        />
      )}
    </div>
  )
}

function NewChat() {
  const [params] = useSearchParams()
  const projectId = params.get('project')
  const project = useProject(projectId ?? undefined)
  const navigate = useNavigate()
  const send = useChatStreams((s) => s.send)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const start = async (m: Outgoing) => {
    setBusy(true)
    setError(null)
    try {
      const chat = await createChat({ project_id: projectId, model: m.model, effort: m.effort, context: m.context })
      const files = m.files.length ? await uploadChatFiles(chat.id, m.files) : []
      navigate(`/chats/${chat.id}`, { replace: true })
      void send(chat.id, { content: m.text, model: m.model, effort: m.effort, context: m.context, attachment_ids: files.map((f) => f.id) },
        { question: m.text, attachments: files.map((f) => ({ id: f.id, filename: f.filename, kind: f.kind })) })
    } catch (e) {
      setError(apiErrorMessage(e, 'The chat could not be started.'))
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto grid max-w-3xl gap-6 pt-[12vh]">
      <div className="grid gap-1.5 text-center">
        <h1 className="text-[24px] font-semibold tracking-[-0.015em] text-fg">
          {project.data ? <>New chat in <Link to={`/projects/${project.data.id}`} className="text-accent-ink hover:underline">{project.data.name}</Link></> : 'What are you working on?'}
        </h1>
        <p className="text-fg-2">
          {project.data
            ? 'Answers draw on the project’s papers, maps, files and artifacts, and cite them.'
            : 'Chat with your local models. They can search papers, ask your research maps and write artifacts.'}
        </p>
      </div>
      {error && <Notice tone="error" title="Not started">{error}</Notice>}
      <Composer onSend={start} streaming={busy} autoFocus placeholder={project.data ? `Ask about ${project.data.name}…` : 'Ask anything…'} />
    </div>
  )
}

function ChatHeader({ chat }: { chat: Chat }) {
  const update = useUpdateChat()
  const remove = useDeleteChat()
  const projects = useProjects()
  const navigate = useNavigate()
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState(chat.title)

  return (
    <header className="sticky top-0 z-10 -mx-4 flex items-center gap-2 border-b border-line bg-bg/90 px-4 py-2 backdrop-blur md:-mx-8 md:px-8">
      <div className="min-w-0 flex-1">
        {chat.project_id && (
          <Link to={`/projects/${chat.project_id}`} className="inline-flex items-center gap-1 text-[12px] text-fg-3 hover:text-fg-2">
            <FolderKanban className="h-3 w-3" aria-hidden="true" />{chat.project_name}
          </Link>
        )}
        {renaming ? (
          <form className="flex gap-1.5" onSubmit={(e) => {
            e.preventDefault()
            if (title.trim()) update.mutate({ id: chat.id, title: title.trim() }, { onSuccess: () => setRenaming(false) })
          }}>
            <input value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Chat title" autoFocus className={cn(inputClass, 'flex-1')} />
            <Button type="submit" variant="secondary" size="sm">Save</Button>
            <Button variant="ghost" size="sm" onClick={() => setRenaming(false)}>Cancel</Button>
          </form>
        ) : (
          <h1 className="truncate text-[15px] font-medium text-fg">{chat.title}</h1>
        )}
      </div>
      <Popover
        label="Chat actions"
        width={240}
        trigger={({ ref, open, toggle }) => (
          <Button ref={ref} variant="ghost" size="icon-sm" onClick={toggle} aria-expanded={open} aria-label="Chat actions" title="Chat actions"><MoreHorizontal /></Button>
        )}
      >
        {(close) => (
          <div className="grid py-1 text-[13px]">
            <button type="button" className="flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-2" onClick={() => {
              setTitle(chat.title)
              setRenaming(true)
              close()
            }}><Pencil className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" />Rename</button>
            {!chat.archived && (
              <button type="button" className="flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-2" onClick={() => {
                update.mutate({ id: chat.id, pinned: !chat.pinned })
                close()
              }}>{chat.pinned ? <PinOff className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" /> : <Pin className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" />}{chat.pinned ? 'Unpin' : 'Pin'}</button>
            )}
            <button type="button" className="flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-2" onClick={() => {
              update.mutate({ id: chat.id, archived: !chat.archived })
              close()
            }}>{chat.archived ? <ArchiveRestore className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" /> : <Archive className="h-3.5 w-3.5 text-fg-3" aria-hidden="true" />}{chat.archived ? 'Unarchive' : 'Archive'}</button>
            <p className="mt-1 flex items-center gap-2 border-t border-line px-3 pt-2 pb-1 text-[12px] text-fg-3"><FolderInput className="h-3.5 w-3.5" aria-hidden="true" />Move to</p>
            <div className="max-h-48 overflow-y-auto">
              {[{ id: null as string | null, name: 'No project' }, ...(projects.data ?? [])].map((p) => (
                <button key={p.id ?? 'none'} type="button" className="flex w-full items-center gap-2 px-3 py-1.5 pl-8 text-left hover:bg-surface-2" onClick={() => {
                  update.mutate({ id: chat.id, project_id: p.id })
                  close()
                }}>
                  <span className="min-w-0 flex-1 truncate">{p.name}</span>
                  {chat.project_id === p.id && <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}
                </button>
              ))}
            </div>
            <button type="button" className="mt-1 flex items-center gap-2 border-t border-line px-3 py-2 text-left text-bad hover:bg-surface-2" onClick={() => {
              close()
              if (window.confirm(`Delete “${chat.title}”? Its artifacts stay.`)) {
                remove.mutate(chat.id, { onSuccess: () => navigate(chat.project_id ? `/projects/${chat.project_id}` : '/chats') })
              }
            }}><Trash2 className="h-3.5 w-3.5" aria-hidden="true" />Delete</button>
          </div>
        )}
      </Popover>
    </header>
  )
}

const fromDraft = (d: Draft): AssistantTurn => ({
  id: 'draft', content: d.content, reasoning: d.reasoning || null, reasoningMs: d.reasoningMs, thinking: !!d.thinkingSince && d.streaming,
  steps: d.steps, sources: d.sources, artifacts: d.artifacts, notices: d.notices, status: d.streaming ? 'streaming' : d.error ? 'failed' : 'stopped',
  error: d.error, model: d.model, effort: d.effort, tokens: null, live: d.streaming, loading: d.loading,
})

function ChatView({ id }: { id: string }) {
  const chat = useChat(id)
  const draft = useChatStreams((s) => s.drafts[id])
  const send = useChatStreams((s) => s.send)
  const stop = useChatStreams((s) => s.stop)
  const dismiss = useChatStreams((s) => s.dismiss)
  const openArtifact = useChatStreams((s) => s.openArtifact)
  const [error, setError] = useState<string | null>(null)
  const nearBottom = useRef(true)

  useEffect(() => {
    const onScroll = () => {
      nearBottom.current = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 160
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Follow the answer while the page is at its end; the composer is sticky there, so scroll to the very bottom.
  useLayoutEffect(() => {
    if (nearBottom.current) window.scrollTo({ top: document.documentElement.scrollHeight })
  }, [chat.data?.messages.length, draft?.question, draft?.content, draft?.reasoning, draft?.steps.length])

  if (chat.isLoading) return <Spinner label="Opening the chat…" />
  if (!chat.data) return <Notice tone="error" title="Chat not found">It may have been deleted. <Link to="/chats" className="underline">All chats</Link></Notice>
  const c = chat.data

  // The turn being answered shows from the draft; hide the copies a refetch brings (its question and answer).
  let messages = c.messages
  if (draft) {
    const at = messages.findIndex((m) => m.id === draft.messageId)
    const hidden = new Set(at === -1 ? [] : [messages[at].id, ...(!draft.retry && at > 0 ? [messages[at - 1].id] : [])])
    messages = messages.filter((m) => !hidden.has(m.id) && m.status !== 'streaming')
  }
  if (draft?.retry) {
    while (messages.length && messages[messages.length - 1].role === 'assistant') messages = messages.slice(0, -1)
  }
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const streaming = !!draft?.streaming || c.messages.some((m) => m.status === 'streaming' && !draft)

  const submit = async (m: Outgoing) => {
    setError(null)
    nearBottom.current = true  // follow the new turn, wherever the page was
    try {
      const files = m.files.length ? await uploadChatFiles(id, m.files) : []
      void send(id, { content: m.text, model: m.model, effort: m.effort, context: m.context, attachment_ids: files.map((f) => f.id) },
        { question: m.text, attachments: files.map((f) => ({ id: f.id, filename: f.filename, kind: f.kind })) })
    } catch (e) {
      setError(apiErrorMessage(e, 'The files could not be attached.'))
    }
  }

  const retry = () => {
    nearBottom.current = true
    // The chat keeps the model picked; a message's own is the preset it ran on (a context or vision variant).
    const model = c.model ?? lastAssistant?.model
    void send(id, { retry: true, model: model ?? '', effort: c.effort ?? 'low', context: c.context }, { question: '' })
  }

  return (
    <div className="mx-auto grid max-w-3xl">
      <ChatHeader chat={c} />
      <div className="grid gap-6 py-6">
        {messages.map((m) => (m.role === 'user' ? (
          <UserMessage key={m.id} content={m.content} attachments={m.attachments} />
        ) : (
          <AssistantMessage
            key={m.id}
            projectId={c.project_id}
            onOpenArtifact={openArtifact}
            onRetry={m.id === lastAssistant?.id && !streaming ? retry : undefined}
            turn={{
              id: m.id, content: m.content, reasoning: m.reasoning, reasoningMs: m.reasoning_ms, thinking: false, steps: m.steps,
              sources: m.sources, artifacts: m.artifacts, notices: [], status: m.status, error: m.error, model: m.model,
              effort: m.effort, tokens: m.input_tokens + m.output_tokens || null, live: false, stats: m.stats,
            }}
          />
        )))}
        {draft && !draft.retry && draft.question && <UserMessage content={draft.question} attachments={draft.attachments} />}
        {draft && (
          <>
            <AssistantMessage turn={fromDraft(draft)} projectId={c.project_id} onOpenArtifact={openArtifact} />
            {!draft.streaming && draft.error && !draft.saved && (
              <Button variant="ghost" size="sm" className="justify-self-start" onClick={() => dismiss(id)}>Dismiss</Button>
            )}
          </>
        )}
      </div>
      <div className="sticky bottom-0 -mx-2 bg-gradient-to-t from-bg via-bg to-transparent px-2 pt-6 pb-4">
        {error && <p className="mb-2 text-[12.5px] text-bad">{error}</p>}
        <Composer
          onSend={submit}
          onStop={() => stop(id)}
          streaming={streaming}
          initial={{ model: c.model, effort: c.effort, context: c.context }}
          placeholder={c.project_name ? `Ask about ${c.project_name}…` : 'Reply…'}
        />
        {c.artifacts.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-fg-3">
            Artifacts:
            {c.artifacts.map((a) => (
              <button key={a.id} type="button" onClick={() => openArtifact(a.id)} className="rounded-md border border-line px-1.5 py-0.5 text-fg-2 hover:border-line-strong hover:text-fg">{a.title}</button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
