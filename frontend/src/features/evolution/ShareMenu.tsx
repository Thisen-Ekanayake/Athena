import { useEffect, useRef, useState } from 'react'
import { Check, Copy, Link2, Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { Button } from '../../ui/Button'
import { Segmented } from '../../ui/Segmented'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { shareExpiry, shareUrl, useCreateShare, useRevokeShare, useShares, useSharing } from './api'

const EXPIRY = [
  { value: 'never', label: 'Never' },
  { value: '7', label: '7 days' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
]

/** Copies a link and says so for a moment. */
export function CopyLink({ token }: { token: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(shareUrl(token))
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }
  return (
    <Button variant="ghost" size="icon-sm" onClick={() => void copy()} aria-label="Copy the link" title="Copy the link">
      {copied ? <Check /> : <Copy />}
    </Button>
  )
}

/**
 * Read-only links to this map for people without an account. Shown only while sharing is on; anyone logged in
 * can make one, and sees their own links (admins see everyone's).
 */
export function ShareMenu({ slug, name }: { slug: string; name: string }) {
  const sharing = useSharing()
  const [open, setOpen] = useState(false)
  const [expiry, setExpiry] = useState('never')
  const ref = useRef<HTMLDivElement>(null)
  const shares = useShares(slug, open)
  const create = useCreateShare(slug)
  const revoke = useRevokeShare()

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (!sharing.data) return null
  const links = shares.data?.shares ?? []
  const failure = create.error ?? revoke.error

  return (
    <div ref={ref} className="relative">
      <Button variant="secondary" size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="dialog">
        <Link2 /> Share
      </Button>
      {open && (
        <div role="dialog" aria-label={`Share ${name}`} className="absolute right-0 z-30 mt-1.5 grid w-[340px] gap-3 rounded-xl border border-line bg-surface p-3 text-[13px] shadow-lg">
          <div className="grid gap-1">
            <p className="font-medium text-fg">Share a read-only link</p>
            <p className="text-[12.5px] text-fg-2">
              Anyone with the link can see the map, its reading path, open problems, people and changes, without an account.
              Questions to the map stay with accounts.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-fg-3">Expires</span>
            <Segmented label="Link expires" value={expiry} options={EXPIRY} onChange={setExpiry} />
          </div>
          <Button variant="primary" size="sm" className="justify-self-start" disabled={create.isPending}
            onClick={() => create.mutate(expiry === 'never' ? null : Number(expiry))}>
            {create.isPending ? 'Making the link…' : 'Make a link'}
          </Button>
          {failure && <p className="text-[12px] text-bad" role="alert">{apiErrorMessage(failure, 'That did not work')}</p>}
          <div className="grid gap-1.5 border-t border-line pt-3">
            <p className="text-[11px] font-medium tracking-[0.08em] text-fg-3 uppercase">Active links</p>
            {shares.isLoading ? <Spinner className="h-3.5 w-3.5" /> : links.length === 0 ? (
              <p className="text-[12.5px] text-fg-3">None yet.</p>
            ) : (
              <ul className="grid gap-2">
                {links.map((s) => (
                  <li key={s.id} className={cn('grid gap-0.5 rounded-lg border border-line px-2.5 py-2', create.data?.id === s.id && 'border-accent-line')}>
                    <span className="flex items-center gap-1">
                      <a href={shareUrl(s.token)} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-fg-2 hover:text-fg">
                        {shareUrl(s.token).replace(/^https?:\/\//, '')}
                      </a>
                      <CopyLink token={s.token} />
                      <Button variant="ghost" size="icon-sm" onClick={() => revoke.mutate(s.id)} disabled={revoke.isPending} aria-label="Revoke the link" title="Revoke: the link stops working">
                        <Trash2 />
                      </Button>
                    </span>
                    <span className="text-[11.5px] text-fg-3">
                      {s.creator ?? 'Someone'} · {s.views} {s.views === 1 ? 'view' : 'views'} · {shareExpiry(s)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
