import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileText, FolderKanban, MessageSquare, NotebookPen, Plus } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { apiErrorMessage } from '../api/error'
import { useCreateProject, useProjects } from '../api/queries/projects'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { EmptyState } from '../ui/EmptyState'
import { PageHeader } from '../ui/PageHeader'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'
import { inputClass } from '../ui/inputClass'

function NewProject({ onCancel }: { onCancel: () => void }) {
  const create = useCreateProject()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  return (
    <Card className="mb-6 p-4">
      <form className="grid gap-3" onSubmit={(e) => {
        e.preventDefault()
        if (name.trim()) create.mutate({ name: name.trim(), description: description.trim() }, { onSuccess: (p) => navigate(`/projects/${p.id}`) })
      }}>
        <label className="grid gap-1">
          <span className="text-[12px] text-fg-3">Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. Thesis: efficient fine-tuning" className={inputClass} />
        </label>
        <label className="grid gap-1">
          <span className="text-[12px] text-fg-3">What is it for? (optional)</span>
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} placeholder="The question you are working on, so chats know the context"
            className={cn(inputClass, 'h-auto py-1.5')} />
        </label>
        {create.isError && <p className="text-[12px] text-bad">{apiErrorMessage(create.error, 'The project could not be created.')}</p>}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>{create.isPending ? 'Creating…' : 'Create project'}</Button>
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  )
}

/** Your projects: workspaces that gather papers, maps, files, chats and artifacts around one question. */
export function ProjectsPage() {
  const projects = useProjects()
  const [creating, setCreating] = useState(false)

  return (
    <div className="mx-auto grid max-w-5xl">
      <PageHeader
        title="Projects"
        description="Gather papers, maps, reviews, files and chats around one question. Chats in a project read everything in it."
        actions={!creating && <Button variant="primary" onClick={() => setCreating(true)}><Plus /> New project</Button>}
      />
      {creating && <NewProject onCancel={() => setCreating(false)} />}
      {projects.isLoading ? <Spinner label="Loading projects…" /> : projects.data?.length ? (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {projects.data.map((p) => (
            <li key={p.id}>
              <Link to={`/projects/${p.id}`} className="grid h-full content-start gap-2 rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong">
                <span className="flex items-center gap-2">
                  <FolderKanban className="h-4 w-4 shrink-0 text-accent" aria-hidden="true" />
                  <span className="truncate text-[14px] font-medium text-fg">{p.name}</span>
                </span>
                {p.description && <span className="line-clamp-2 text-[12.5px] text-fg-2">{p.description}</span>}
                <span className="mt-auto flex flex-wrap items-center gap-3 pt-1 text-[11.5px] text-fg-3">
                  <span className="inline-flex items-center gap-1"><MessageSquare className="h-3 w-3" aria-hidden="true" />{p.counts.chats}</span>
                  <span className="inline-flex items-center gap-1"><FileText className="h-3 w-3" aria-hidden="true" />{p.counts.items + p.counts.files}</span>
                  <span className="inline-flex items-center gap-1"><NotebookPen className="h-3 w-3" aria-hidden="true" />{p.counts.artifacts}</span>
                  <span className="ml-auto">{formatDistanceToNow(new Date(p.updated_at), { addSuffix: true })}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : !creating && (
        <EmptyState icon={FolderKanban} title="No projects yet" action={<Button variant="secondary" onClick={() => setCreating(true)}><Plus /> Create one</Button>}>
          A project keeps what you need for one piece of work together: papers, maps, reviews, your own files, chats and the documents they write.
        </EmptyState>
      )}
    </div>
  )
}
