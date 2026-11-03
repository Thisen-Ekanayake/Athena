import { useState, type FormEvent, type ReactNode } from 'react'
import { Check, Copy, Trash2 } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import {
  useAccessTokens, useCreateAccessToken, useRevokeAccessToken, type NewAccessToken,
} from '../../api/queries/tokens'
import { timeAgo } from '../../components/items/format'
import { Button } from '../../ui/Button'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { claudeCommand, clientConfig, mcpUrl } from './connect'

const EXPIRY = [
  { days: null, label: 'Never' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
  { days: 365, label: 'A year' },
] as const

function Title({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-4 grid gap-1">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description && <p className="max-w-[68ch] text-[13px] text-fg-2">{description}</p>}
    </div>
  )
}

function CopyBlock({ label, text }: { label: string; text: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="grid gap-1">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[12px] text-fg-3">{label}</p>
        <Button variant="ghost" size="icon-sm" onClick={() => void copy()} aria-label={`Copy: ${label}`} title="Copy">
          {copied ? <Check /> : <Copy />}
        </Button>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-all rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[12px] text-fg">{text}</pre>
    </div>
  )
}

/** Each person's own: tokens that let an agent use Athena through its MCP server, as this account. */
export function AgentsSettings() {
  const [made, setMade] = useState<NewAccessToken | null>(null)
  return (
    <section className="grid gap-8">
      <div>
        <Title
          title="Agents"
          description={
            <>
              Claude Code and other MCP clients can use Athena as you do here: ask it for a literature review, a map
              of a field, an answer from a map or a chat turn, and Athena does the work with its own model and hands
              back the result. Whatever an agent makes is saved to your account, and your daily allowances apply.
              The server is at <code className="rounded bg-surface-2 px-1 font-mono text-[12px]">{mcpUrl()}</code>.
            </>
          }
        />
        {made ? <NewToken token={made} onDone={() => setMade(null)} /> : <CreateToken onMade={setMade} />}
      </div>
      <TokenList />
    </section>
  )
}

function CreateToken({ onMade }: { onMade: (t: NewAccessToken) => void }) {
  const create = useCreateAccessToken()
  const [name, setName] = useState('Claude Code')
  const [days, setDays] = useState<number | null>(null)
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim()) create.mutate({ name: name.trim(), expires_days: days }, { onSuccess: onMade })
  }
  return (
    <form onSubmit={submit} className="grid gap-3 rounded-xl border border-line bg-surface p-4" aria-label="New access token">
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-[12px] text-fg-3">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} className={cn(inputClass, 'w-56')} />
        </label>
        <label className="grid gap-1 text-[12px] text-fg-3">
          Expires
          <select value={days ?? ''} onChange={(e) => setDays(e.target.value ? Number(e.target.value) : null)} className={cn(inputClass, 'pr-6')}>
            {EXPIRY.map((x) => <option key={x.label} value={x.days ?? ''}>{x.label}</option>)}
          </select>
        </label>
        <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>Make a token</Button>
      </div>
      {create.isError && <Notice tone="error">{apiErrorMessage(create.error, 'The token was not made')}</Notice>}
    </form>
  )
}

function NewToken({ token, onDone }: { token: NewAccessToken; onDone: () => void }) {
  return (
    <div className="grid gap-4 rounded-xl border border-accent-line bg-surface p-4">
      <Notice tone="warn" title={`Copy “${token.name}” now`}>
        Athena keeps only a fingerprint of the token, so it cannot show it again. Anyone with it can use Athena as you;
        revoke it below if it leaks.
      </Notice>
      <CopyBlock label="Token" text={token.token} />
      <CopyBlock label="Add it to Claude Code (run in a terminal)" text={claudeCommand(token.token)} />
      <CopyBlock label="Or in another MCP client's configuration" text={clientConfig(token.token)} />
      <div>
        <Button onClick={onDone}>Done</Button>
      </div>
    </div>
  )
}

function TokenList() {
  const { data: tokens, isLoading, isError, error } = useAccessTokens()
  const revoke = useRevokeAccessToken()
  if (isLoading) return <Spinner label="Loading tokens…" />
  if (isError) return <Notice tone="error">{apiErrorMessage(error, 'Your tokens could not be loaded')}</Notice>
  return (
    <div>
      <Title title="Your tokens" description="Revoking one stops the agent that uses it at its next request." />
      {!tokens?.length ? (
        <p className="text-[13px] text-fg-3">No tokens yet.</p>
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line bg-surface">
          {tokens.map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div className="grid min-w-0 gap-0.5">
                <p className="truncate text-[13.5px] text-fg">{t.name} <span className="font-mono text-[12px] text-fg-3">{t.hint}…</span></p>
                <p className="text-[12px] text-fg-3">
                  {t.last_used_at ? `Used ${timeAgo(t.last_used_at)}` : 'Not used yet'}
                  {t.created_at && ` · made ${timeAgo(t.created_at)}`}
                  {t.expires_at && ` · expires ${new Date(t.expires_at).toLocaleDateString()}`}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Revoke ${t.name}`}
                title="Revoke"
                disabled={revoke.isPending}
                onClick={() => {
                  if (window.confirm(`Revoke “${t.name}”? The agent using it stops working.`)) revoke.mutate(t.id)
                }}
              >
                <Trash2 />
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
