import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, FolderKanban, FolderPlus, Plus } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { apiErrorMessage } from '../../api/error'
import { useAddToProject, useCreateProject, useMembership, useProjects, type ItemToAdd } from '../../api/queries/projects'
import { Button } from '../../ui/Button'
import { Popover } from '../../ui/Popover'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'

/**
 * "Add to project" for a paper, map, review or idea check: the projects that hold it are ticked; pick another to
 * add it, or name a new project. ``membershipRef`` names the thing as projects do (item:<id>, map:<slug>, ...).
 */
export function AddToProjectMenu({ membershipRef, item, compact = false }: { membershipRef: string; item: ItemToAdd; compact?: boolean }) {
  const [open, setOpen] = useState(false)
  const projects = useProjects()
  const membership = useMembership(membershipRef, open)
  const add = useAddToProject()
  const create = useCreateProject()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const holding = new Set(membership.data ?? [])

  const addTo = async (projectId: string) => {
    setError(null)
    try {
      await add.mutateAsync({ projectId, item })
      await qc.invalidateQueries({ queryKey: ['projects', 'membership', membershipRef] })
    } catch (e) {
      setError(apiErrorMessage(e, 'Not added.'))
    }
  }

  return (
    <Popover
      label="Add to a project"
      width={260}
      trigger={({ ref, open: isOpen, toggle }) => (
        <Button
          ref={ref}
          variant={compact ? 'ghost' : 'secondary'}
          size={compact ? 'icon-sm' : 'sm'}
          onClick={() => {
            setOpen(true)
            toggle()
          }}
          aria-expanded={isOpen}
          aria-label="Add to a project"
          title="Add to a project"
          className={cn(isOpen && 'bg-surface-2 text-fg')}
        >
          <FolderPlus />{!compact && ' Add to project'}
        </Button>
      )}
    >
      <p className="border-b border-line px-3 py-2 text-[12px] text-fg-3">Add to a project</p>
      <div className="max-h-56 overflow-y-auto py-1">
        {projects.isLoading || membership.isLoading ? (
          <div className="flex justify-center py-4"><Spinner /></div>
        ) : projects.data?.length ? projects.data.map((p) => {
          const inIt = holding.has(p.id)
          return (
            <div key={p.id} className="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-2">
              <FolderKanban className="h-3.5 w-3.5 shrink-0 text-fg-3" aria-hidden="true" />
              {inIt ? (
                <>
                  <Link to={`/projects/${p.id}`} className="min-w-0 flex-1 truncate text-[13px] text-fg hover:underline">{p.name}</Link>
                  <Check className="h-3.5 w-3.5 text-accent" aria-label="In this project" />
                </>
              ) : (
                <button type="button" disabled={add.isPending} onClick={() => void addTo(p.id)} className="min-w-0 flex-1 truncate text-left text-[13px] text-fg">
                  {p.name}
                </button>
              )}
            </div>
          )
        }) : <p className="px-3 py-2 text-[12.5px] text-fg-3">No projects yet. Name one below.</p>}
      </div>
      <form className="flex gap-1.5 border-t border-line p-2" onSubmit={async (e) => {
        e.preventDefault()
        if (!name.trim()) return
        try {
          const p = await create.mutateAsync({ name: name.trim() })
          setName('')
          await addTo(p.id)
        } catch (err) {
          setError(apiErrorMessage(err, 'The project could not be created.'))
        }
      }}>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New project" aria-label="New project name"
          className="h-7 min-w-0 flex-1 rounded-md border border-line bg-surface-2 px-2 text-[12.5px] text-fg placeholder:text-fg-3 focus:border-accent-line focus:outline-none" />
        <Button type="submit" variant="secondary" size="icon-sm" disabled={!name.trim() || create.isPending} aria-label="Create project and add">
          {create.isPending ? <Spinner className="h-3.5 w-3.5" /> : <Plus />}
        </Button>
      </form>
      {error && <p className="px-3 pb-2 text-[12px] text-bad">{error}</p>}
    </Popover>
  )
}
