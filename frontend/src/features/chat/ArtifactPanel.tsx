import { useState } from 'react'
import { Check, Copy, Download, History, Pencil, Trash2, X } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { apiErrorMessage } from '../../api/error'
import {
  artifactExportUrl, fetchArtifactVersion, useArtifact, useArtifactVersions, useDeleteArtifact, useRestoreArtifact,
  useUpdateArtifact,
} from '../../api/queries/artifacts'
import { Button } from '../../ui/Button'
import { Popover } from '../../ui/Popover'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { Markdown } from '../reviews/Markdown'

/**
 * An artifact beside the chat (give it ``key={id}`` so switching artifacts starts fresh): read it, edit its Markdown, look at earlier versions and bring one back, copy or
 * download it. Every save is a new version; the model's edits are versions too.
 */
export function ArtifactPanel({ id, onClose, className }: { id: string; onClose: () => void; className?: string }) {
  const artifact = useArtifact(id)
  const update = useUpdateArtifact(id)
  const restore = useRestoreArtifact(id)
  const remove = useDeleteArtifact()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ title: '', content: '' })
  const [viewing, setViewing] = useState<{ version: number; title: string; content: string } | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const versions = useArtifactVersions(id, historyOpen)
  const [copied, setCopied] = useState(false)

  const a = artifact.data
  if (artifact.isLoading) return <aside className={cn('grid place-items-center', className)}><Spinner label="Opening…" /></aside>
  if (!a) return <aside className={cn('p-4 text-[13px] text-fg-3', className)}>This artifact is gone. <Button variant="ghost" size="sm" onClick={onClose}>Close</Button></aside>

  const shown = viewing ?? { version: a.version, title: a.title, content: a.content }
  const startEdit = () => {
    setDraft({ title: a.title, content: a.content })
    setViewing(null)
    setEditing(true)
  }

  return (
    <aside className={cn('flex min-h-0 flex-col border-l border-line bg-surface', className)} aria-label="Artifact">
      <header className="flex items-center gap-1 border-b border-line px-3 py-2">
        {editing ? (
          <input value={draft.title} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} aria-label="Title" className={cn(inputClass, 'flex-1')} />
        ) : (
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13.5px] font-medium text-fg">{shown.title}</p>
            <p className="text-[11.5px] text-fg-3">
              {viewing ? `Version ${viewing.version} of ${a.version}` : `Version ${a.version}`} · {a.chars.toLocaleString()} characters
            </p>
          </div>
        )}
        {!editing && (
          <>
            <Popover
              label="Versions"
              width={260}
              trigger={({ ref, open, toggle }) => (
                <Button ref={ref} variant="ghost" size="icon-sm" aria-label="Versions" title="Versions" aria-expanded={open}
                  onClick={() => {
                    setHistoryOpen(true)
                    toggle()
                  }}>
                  <History />
                </Button>
              )}
            >
              {(close) => (
                <div className="max-h-72 overflow-y-auto py-1">
                  {versions.isLoading && <div className="flex justify-center py-3"><Spinner /></div>}
                  {versions.data?.map((v) => (
                    <button key={v.version} type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-2"
                      onClick={async () => {
                        setViewing(v.version === a.version ? null : await fetchArtifactVersion(id, v.version))
                        close()
                      }}>
                      <span className="w-8 font-mono text-[11.5px] text-fg-3">v{v.version}</span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12.5px] text-fg">{v.author === 'model' ? 'Written by the model' : 'Edited by you'}</span>
                        <span className="block text-[11px] text-fg-3">{formatDistanceToNow(new Date(v.created_at), { addSuffix: true })}</span>
                      </span>
                      {shown.version === v.version && <Check className="h-3.5 w-3.5 text-accent" aria-hidden="true" />}
                    </button>
                  ))}
                </div>
              )}
            </Popover>
            <Button variant="ghost" size="icon-sm" aria-label="Copy" title="Copy Markdown" onClick={() => {
              void navigator.clipboard?.writeText(shown.content)
              setCopied(true)
              setTimeout(() => setCopied(false), 1500)
            }}>
              {copied ? <Check /> : <Copy />}
            </Button>
            <a href={artifactExportUrl(id)} className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-fg-2 hover:bg-surface-2 hover:text-fg" aria-label="Download" title="Download as Markdown">
              <Download className="h-3.5 w-3.5" />
            </a>
            <Button variant="ghost" size="icon-sm" aria-label="Edit" title="Edit" onClick={startEdit}><Pencil /></Button>
            <Button variant="ghost" size="icon-sm" aria-label="Delete artifact" title="Delete" onClick={() => {
              if (window.confirm(`Delete “${a.title}” and all its versions?`)) remove.mutate(id, { onSuccess: onClose })
            }}>
              <Trash2 />
            </Button>
          </>
        )}
        <Button variant="ghost" size="icon-sm" aria-label="Close artifact" title="Close" onClick={onClose}><X /></Button>
      </header>
      {viewing && !editing && (
        <div className="flex items-center gap-2 border-b border-line bg-surface-2 px-3 py-1.5 text-[12px] text-fg-2">
          Looking at an earlier version.
          <Button variant="secondary" size="sm" className="ml-auto" disabled={restore.isPending} onClick={() => restore.mutate(viewing.version, { onSuccess: () => setViewing(null) })}>
            Bring it back
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setViewing(null)}>Latest</Button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {editing ? (
          <textarea
            value={draft.content}
            onChange={(e) => setDraft((d) => ({ ...d, content: e.target.value }))}
            aria-label="Markdown"
            className="h-full min-h-[300px] w-full resize-none bg-transparent px-4 py-3 font-mono text-[12.5px] leading-relaxed text-fg focus:outline-none"
          />
        ) : (
          <div className="px-5 py-4"><Markdown text={shown.content || '*Empty*'} /></div>
        )}
      </div>
      {editing && (
        <footer className="flex items-center gap-2 border-t border-line px-3 py-2">
          {update.isError && <span className="text-[12px] text-bad">{apiErrorMessage(update.error, 'Not saved.')}</span>}
          <Button variant="ghost" className="ml-auto" onClick={() => setEditing(false)}>Cancel</Button>
          <Button variant="primary" disabled={update.isPending || !draft.title.trim()} onClick={() => update.mutate(draft, { onSuccess: () => setEditing(false) })}>
            {update.isPending ? 'Saving…' : 'Save as a new version'}
          </Button>
        </footer>
      )}
    </aside>
  )
}
