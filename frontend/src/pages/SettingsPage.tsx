import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Link, NavLink, useParams } from 'react-router-dom'
import { ArrowDownWideNarrow, ArrowUpNarrowWide, Check, Eye, EyeOff, Pencil, RefreshCw, Trash2, X, ExternalLink } from 'lucide-react'
import { apiClient, type Source } from '../api/client'
import { apiErrorMessage } from '../api/error'
import { useCreateUser, useCurrentUser, useIsAdmin, useResetPassword, useUpdateUser, useUsers, type AuthUser, type IssuedUser, type Role } from '../api/queries/auth'
import { useApiKeys, useDeleteApiKey, useModelSettings, useSetApiKey, useTestModels, useUpdateModelSettings, type ModelTestResult } from '../api/queries/app_settings'
import { useClusters, useFetchHealth, useScoringHealth } from '../api/queries/phase4'
import { useAddSource, useSources, useToggleSource, useUpdateSource, type PreviewResponse } from '../api/queries/sources'
import { timeAgo } from '../components/items/format'
import { SyncLog } from '../components/layout/SyncLog'
import { NotificationsSettings } from '../features/inbox/NotificationsSettings'
import { UsageSettings } from '../features/usage/UsageSettings'
import { PasswordForm } from './AuthPages'
import { useAppStore, type Accent } from '../store/appStore'
import { Button } from '../ui/Button'
import { Card } from '../ui/Card'
import { Chip } from '../ui/Chip'
import { Notice } from '../ui/Notice'
import { OwlCoin } from '../ui/OwlCoin'
import { PageHeader } from '../ui/PageHeader'
import { Spinner } from '../ui/Spinner'
import { cn } from '../ui/cn'
import { inputClass } from '../ui/inputClass'

// Admin tabs change Athena for everyone; Account, Notifications, Usage and Appearance are each person's own
// (Usage also shows admins the whole app).
const TABS = [
  { id: 'sources', label: 'Sources', admin: true },
  { id: 'keys', label: 'Models and keys', admin: true },
  { id: 'users', label: 'Users', admin: true },
  { id: 'account', label: 'Account', admin: false },
  { id: 'notifications', label: 'Notifications', admin: false },
  { id: 'usage', label: 'Usage', admin: false },
  { id: 'appearance', label: 'Appearance', admin: false },
  { id: 'clusters', label: 'Clusters', admin: true },
  { id: 'health', label: 'Health', admin: true },
  { id: 'sync', label: 'Sync log', admin: true },
] as const

type Tab = (typeof TABS)[number]['id']


function SectionTitle({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-4 grid gap-1">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description && <p className="max-w-[68ch] text-[13px] text-fg-2">{description}</p>}
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: string }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-[12px] text-fg-3">{label}</p>
      <p className="mt-1 font-mono text-[22px] font-medium tabular-nums text-fg">{value}</p>
      {sub && <p className="mt-0.5 text-[12px] text-fg-3">{sub}</p>}
    </div>
  )
}

/** Your account and how Athena looks; for admins also where it fetches from, its models, users and pipeline. */
export function SettingsPage() {
  const { tab } = useParams<{ tab?: string }>()
  const isAdmin = useIsAdmin()
  const tabs = TABS.filter((t) => isAdmin || !t.admin)
  const active: Tab = tabs.some((t) => t.id === tab) ? (tab as Tab) : isAdmin ? 'sources' : 'account'

  return (
    <div className="mx-auto max-w-[1100px]">
      <PageHeader title="Settings" />
      <div className="grid gap-8 md:grid-cols-[200px_minmax(0,1fr)]">
        <nav className="flex gap-1 overflow-x-auto md:flex-col" aria-label="Settings sections">
          {tabs.map((t) => (
            <NavLink
              key={t.id}
              to={`/settings/${t.id}`}
              className={cn(
                'flex h-8 shrink-0 items-center rounded-lg px-2.5 text-[13.5px] transition-colors',
                active === t.id ? 'bg-surface-2 text-fg shadow-[0_0_0_1px_var(--line)]' : 'text-fg-2 hover:bg-surface-2/60 hover:text-fg',
              )}
            >
              {t.label}
            </NavLink>
          ))}
        </nav>
        <div className="min-w-0">
          {active === 'sources' && <SourcesSection />}
          {active === 'keys' && <KeysSection />}
          {active === 'users' && <UsersSection />}
          {active === 'account' && <AccountSection />}
          {active === 'notifications' && <NotificationsSettings />}
          {active === 'usage' && <UsageSettings />}
          {active === 'appearance' && <AppearanceSection />}
          {active === 'clusters' && <ClustersSection />}
          {active === 'health' && <HealthSection />}
          {active === 'sync' && <SyncSection />}
        </div>
      </div>
    </div>
  )
}

/* ── Sources ── */

type SortKey = 'name' | 'created' | 'health' | 'type' | 'active'

const SORTS: { value: SortKey; label: string }[] = [
  { value: 'name', label: 'Name' },
  { value: 'created', label: 'Date added' },
  { value: 'health', label: 'Failures' },
  { value: 'type', label: 'Type' },
  { value: 'active', label: 'Active' },
]

const byName = (a: Source, b: Source) => a.name.localeCompare(b.name)
const COMPARE: Record<SortKey, (a: Source, b: Source) => number> = {
  name: byName,
  created: (a, b) => (a.created_at || '').localeCompare(b.created_at || ''),
  health: (a, b) => a.consecutive_failures - b.consecutive_failures,
  type: (a, b) => a.type.localeCompare(b.type),
  active: (a, b) => Number(a.is_active) - Number(b.is_active),
}

function host(url: string) {
  try {
    return new URL(url).hostname
  } catch {
    return url
  }
}

const isPreview = (data: PreviewResponse | Source): data is PreviewResponse => 'sample_items' in data

function SourcesSection() {
  const { data: sources, isLoading } = useSources()
  const toggle = useToggleSource()
  const update = useUpdateSource()
  const add = useAddSource()
  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [sortBy, setSortBy] = useState<SortKey>('name')
  const [asc, setAsc] = useState(true)
  const [editing, setEditing] = useState<{ id: string; name: string; url: string } | null>(null)

  const sorted = useMemo(
    () => [...(sources ?? [])].sort((a, b) => (asc ? 1 : -1) * COMPARE[sortBy](a, b) || byName(a, b)),
    [sources, sortBy, asc],
  )

  const check = (e: FormEvent) => {
    e.preventDefault()
    if (!url) return
    add.mutate({ url }, { onSuccess: (data) => setPreview(isPreview(data) ? data : null) })
  }
  const confirm = () => add.mutate({ url, confirm: true }, { onSuccess: () => { setUrl(''); setPreview(null) } })
  const saveEdit = () => {
    if (!editing) return
    update.mutate({ id: editing.id, name: editing.name.trim(), url: editing.url.trim() }, { onSuccess: () => setEditing(null) })
  }

  return (
    <div className="grid gap-8">
      <section>
        <SectionTitle title="Add a source" description="Paste a blog, RSS feed or site address. Athena works out how to read it and shows a preview first." />
        {!preview ? (
          <form onSubmit={check} className="flex gap-2">
            <input id="source-url" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://deepmind.google/discover/blog/" aria-label="Source address" className={cn(inputClass, 'h-9 flex-1')} />
            <Button type="submit" variant="primary" className="h-9" disabled={!url || add.isPending}>{add.isPending ? 'Checking…' : 'Check'}</Button>
          </form>
        ) : (
          <Card className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[15px] font-medium text-fg">{preview.source_name}</p>
                <p className="text-[12.5px] text-fg-3">Read as {preview.source_type}</p>
              </div>
              <Chip tone="good"><Check /> Readable</Chip>
            </div>
            {preview.sample_items.length > 0 && (
              <ul className="mt-3 grid gap-1 border-t border-line pt-3">
                <li className="text-[12px] text-fg-3">Latest items</li>
                {preview.sample_items.slice(0, 3).map((item, i) => <li key={i} className="truncate text-[13px] text-fg-2">{item.title}</li>)}
              </ul>
            )}
            <div className="mt-4 flex gap-2">
              <Button variant="primary" onClick={confirm} disabled={add.isPending}>{add.isPending ? 'Adding…' : 'Add source'}</Button>
              <Button variant="secondary" onClick={() => { setPreview(null); add.reset() }}>Cancel</Button>
            </div>
          </Card>
        )}
        {add.isError && <Notice tone="error" className="mt-3" title="This address could not be read">{apiErrorMessage(add.error, 'Check the address and try again.')}</Notice>}
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
          <SectionTitle title="Your sources" description={sources ? `${sources.length} sources. Switch one off to stop fetching from it.` : undefined} />
          <div className="mb-4 flex items-center gap-1.5">
            <label htmlFor="source-sort" className="text-[12px] text-fg-3">Sort</label>
            <select id="source-sort" value={sortBy} onChange={(e) => setSortBy(e.target.value as SortKey)} className={cn(inputClass, 'pr-6')}>
              {SORTS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
            <Button variant="secondary" size="icon" onClick={() => setAsc((v) => !v)} aria-label={asc ? 'Ascending; switch to descending' : 'Descending; switch to ascending'}>
              {asc ? <ArrowUpNarrowWide /> : <ArrowDownWideNarrow />}
            </Button>
          </div>
        </div>
        {update.isError && <Notice tone="error" className="mb-3" title="The source could not be updated">{apiErrorMessage(update.error, 'Try again.')}</Notice>}
        {isLoading ? (
          <Spinner label="Loading sources…" />
        ) : (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full min-w-[640px] text-left text-[13px]">
              <thead className="border-b border-line bg-surface text-[12px] text-fg-3">
                <tr>
                  <th className="px-4 py-2.5 font-normal">Source</th>
                  <th className="px-4 py-2.5 font-normal">Type</th>
                  <th className="px-4 py-2.5 font-normal">Status</th>
                  <th className="px-4 py-2.5 font-normal">Last fetched</th>
                  <th className="px-4 py-2.5 text-right font-normal">Active</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {sorted.map((s) => (
                  <tr key={s.id} className="bg-bg hover:bg-surface/60">
                    <td className="px-4 py-3">
                      {editing?.id === s.id ? (
                        <div className="grid gap-1.5">
                          <input id={`source-name-${s.id}`} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} aria-label="Name" className={inputClass} />
                          <input id={`source-url-${s.id}`} type="url" value={editing.url} onChange={(e) => setEditing({ ...editing, url: e.target.value })} aria-label="Address" className={cn(inputClass, 'font-mono text-[12px]')} />
                        </div>
                      ) : (
                        <div className="grid">
                          <Link to={`/sources/${s.id}`} className="w-fit font-medium text-fg hover:underline" title="Show this source's items">{s.name}</Link>
                          <a href={s.url} target="_blank" rel="noopener noreferrer" className="inline-flex w-fit items-center gap-1 font-mono text-[11.5px] text-fg-3 hover:text-fg">
                            {host(s.url)} <ExternalLink className="h-3 w-3" aria-hidden="true" />
                          </a>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3"><Chip>{s.type}</Chip></td>
                    <td className="px-4 py-3">
                      {s.consecutive_failures > 0 ? (
                        <span className="inline-flex items-center gap-1.5 text-bad"><span className="h-1.5 w-1.5 rounded-full bg-bad" />{s.consecutive_failures} failed {s.consecutive_failures === 1 ? 'fetch' : 'fetches'}</span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-fg-2"><span className="h-1.5 w-1.5 rounded-full bg-good" />OK</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-fg-3">{timeAgo(s.last_fetched_at) || 'Never'}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {editing?.id === s.id ? (
                          <>
                            <Button variant="ghost" size="icon-sm" onClick={saveEdit} disabled={update.isPending || !editing.name.trim() || !editing.url.trim()} aria-label="Save"><Check /></Button>
                            <Button variant="ghost" size="icon-sm" onClick={() => { setEditing(null); update.reset() }} aria-label="Cancel"><X /></Button>
                          </>
                        ) : (
                          <>
                            <Button variant="ghost" size="icon-sm" onClick={() => setEditing({ id: s.id, name: s.name, url: s.url })} aria-label={`Edit ${s.name}`}><Pencil /></Button>
                            <button
                              type="button"
                              role="switch"
                              aria-checked={s.is_active}
                              aria-label={`Fetch from ${s.name}`}
                              onClick={() => toggle.mutate({ id: s.id, is_active: !s.is_active })}
                              className={cn('relative h-[18px] w-[30px] rounded-full transition-colors', s.is_active ? 'bg-accent' : 'bg-line-strong')}
                            >
                              <span className={cn('absolute top-[2px] left-[2px] h-[14px] w-[14px] rounded-full bg-fg shadow transition-transform', s.is_active && 'translate-x-[12px]')} />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

/* ── Models and keys ── */

const KEYS: { key: string; label: string; hint: string }[] = [
  { key: 'LLM_API_KEY', label: 'Chat model', hint: 'Only for a hosted API such as OpenAI. The local model server needs no key.' },
  { key: 'EMBED_API_KEY', label: 'Embedding model', hint: 'Only when embeddings come from a different hosted API than chat.' },
  { key: 'SEMANTIC_SCHOLAR_API_KEY', label: 'Semantic Scholar', hint: 'Adds citation counts and live paper search. Optional: without it, requests are slower and rate-limited.' },
]

type Field = { key: string; label: string; placeholder?: string; hint?: string; wide?: boolean }

const CHAT_FIELDS: Field[] = [
  { key: 'LLM_BASE_URL', label: 'Server address', hint: 'Any OpenAI-compatible endpoint, ending in /v1.', wide: true },
  { key: 'LLM_CHAT_MODEL', label: 'Model' },
  { key: 'LLM_SERVER', label: 'Server type', placeholder: 'auto', hint: 'llama.cpp or other. Auto treats OpenAI as other and anything else as llama.cpp.' },
  { key: 'LLM_SUMMARY_MODEL', label: 'Summaries', placeholder: 'same model' },
  { key: 'LLM_QA_MODEL', label: 'Q&A', placeholder: 'same model' },
  { key: 'LLM_LIT_REVIEW_MODEL', label: 'Literature reviews', placeholder: 'same model' },
  { key: 'LLM_PRICE_IN_PER_M', label: 'Input price', hint: 'USD per million tokens, for Settings → Usage and the budget. 0 for local models.' },
  { key: 'LLM_PRICE_OUT_PER_M', label: 'Output price', hint: 'USD per million tokens.' },
]

const EMBED_FIELDS: Field[] = [
  { key: 'EMBED_BASE_URL', label: 'Server address', placeholder: 'same as chat', wide: true },
  { key: 'EMBED_MODEL', label: 'Model' },
  { key: 'EMBED_DIMENSIONS', label: 'Dimensions', placeholder: "model's own", hint: 'Only for models that shorten vectors themselves (OpenAI text-embedding-3). Athena keeps 1024.' },
  { key: 'EMBED_PRICE_PER_M', label: 'Price', hint: 'USD per million tokens. 0 for local models.' },
]

function ModelFields({ title, fields, form, defaults, onChange }: {
  title: string
  fields: Field[]
  form: Record<string, string>
  defaults: Record<string, string>
  onChange: (key: string, value: string) => void
}) {
  return (
    <fieldset className="grid gap-3">
      <legend className="mb-1 text-[13px] font-medium text-fg">{title}</legend>
      <div className="grid gap-3 sm:grid-cols-3">
        {fields.map((f) => (
          <label key={f.key} className={cn('grid content-start gap-1', f.wide && 'sm:col-span-3')}>
            <span className="text-[12px] text-fg-3">{f.label}</span>
            <input
              value={form[f.key] ?? ''}
              onChange={(e) => onChange(f.key, e.target.value)}
              placeholder={f.placeholder ?? defaults[f.key] ?? ''}
              className={cn(inputClass, 'font-mono')}
            />
            {f.hint && <span className="text-[11.5px] text-fg-3">{f.hint}</span>}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function TestLine({ label, result }: { label: string; result?: ModelTestResult }) {
  if (!result) return null
  return (
    <p className="flex flex-wrap items-center gap-2 text-[12.5px]">
      <span className="text-fg-2">{label}</span>
      {result.ok ? <Chip tone="good">Ready</Chip> : <Chip tone="bad">Failed</Chip>}
      <span className="font-mono text-fg-3">{result.model ?? ''} · {result.latency_ms} ms{result.dimensions ? ` · ${result.dimensions} dims` : ''}</span>
      {result.error && <span className="w-full text-bad">{result.error}</span>}
    </p>
  )
}

function ModelsCard() {
  const { data } = useModelSettings()
  const update = useUpdateModelSettings()
  const test = useTestModels()
  const [edits, setEdits] = useState<Record<string, string>>({})
  if (!data) return <Card className="p-4"><Spinner label="Loading model settings…" /></Card>

  const form = { ...data.values, ...edits }
  const dirty = Object.keys(edits).length > 0
  const embedModel = (form.EMBED_MODEL || data.defaults.EMBED_MODEL).trim()
  const stale = Object.entries(data.embed_spaces).filter(([, made]) => made && made !== embedModel)

  return (
    <Card className="grid gap-5 p-4">
      <ModelFields title="Chat" fields={CHAT_FIELDS} form={form} defaults={data.defaults} onChange={(k, v) => setEdits((e) => ({ ...e, [k]: v }))} />
      <ModelFields title="Embeddings" fields={EMBED_FIELDS} form={form} defaults={data.defaults} onChange={(k, v) => setEdits((e) => ({ ...e, [k]: v }))} />
      {stale.length > 0 && (
        <Notice tone="warn" title="Stored vectors come from another model">
          {stale.map(([space, made]) => `${space === 'feed' ? 'Feed' : 'Evolution'} vectors were made by ${made}`).join('; ')}.
          {' '}Searches compare like with like, so re-embed after switching: <span className="font-mono">scripts/backfill_embeddings.py --reset</span>.
        </Notice>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="primary" disabled={!dirty || update.isPending} onClick={() => update.mutate(edits, { onSuccess: () => setEdits({}) })}>
          {update.isPending ? 'Saving…' : 'Save'}
        </Button>
        {dirty && <Button variant="ghost" onClick={() => setEdits({})}>Discard</Button>}
        <Button variant="secondary" className="ml-auto" disabled={test.isPending || dirty} onClick={() => test.mutate()} title={dirty ? 'Save first' : undefined}>
          <RefreshCw className={cn(test.isPending && 'animate-spin')} /> {test.isPending ? 'Testing…' : 'Test models'}
        </Button>
      </div>
      {update.isError && <p className="text-[12px] text-bad">{apiErrorMessage(update.error, 'The settings could not be saved.')}</p>}
      {test.isError && <p className="text-[12px] text-bad">{apiErrorMessage(test.error, 'The test could not run.')}</p>}
      {test.data && (
        <div className="grid gap-1.5">
          <TestLine label="Chat" result={test.data.chat} />
          <TestLine label="Embeddings" result={test.data.embed} />
        </div>
      )}
    </Card>
  )
}

function KeyRow({ keyName, label, hint }: { keyName: string; label: string; hint: string }) {
  const { data: keys } = useApiKeys()
  const setKey = useSetApiKey()
  const deleteKey = useDeleteApiKey()
  const info = keys?.find((k) => k.key === keyName)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [revealed, setRevealed] = useState(false)

  const save = (e: FormEvent) => {
    e.preventDefault()
    if (!value.trim()) return
    setKey.mutate({ key: keyName, value }, { onSuccess: () => { setEditing(false); setValue('') } })
  }

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1">
          <p className="flex items-center gap-2 text-[14px] font-medium text-fg">
            {label} {info?.is_set ? <Chip tone="good">Set</Chip> : <Chip>Not set</Chip>}
          </p>
          <p className="text-[12.5px] text-fg-3">{hint}</p>
          {info?.is_set && !editing && (
            <p className="flex items-center gap-2 font-mono text-[12px] text-fg-2">
              {revealed ? info.masked_value : '••••••••••••••••'}
              <Button variant="ghost" size="icon-sm" onClick={() => setRevealed((v) => !v)} aria-label={revealed ? 'Hide key' : 'Show key'}>
                {revealed ? <EyeOff /> : <Eye />}
              </Button>
            </p>
          )}
        </div>
        <div className="flex gap-1.5">
          {info?.is_set && !editing && (
            <Button variant="ghost" size="icon" onClick={() => deleteKey.mutate(keyName)} disabled={deleteKey.isPending} aria-label={`Remove the ${label} key`}><Trash2 /></Button>
          )}
          <Button variant="secondary" size="sm" onClick={() => { setEditing((v) => !v); setValue('') }}>
            {editing ? 'Cancel' : info?.is_set ? 'Replace' : 'Add key'}
          </Button>
        </div>
      </div>
      {editing && (
        <form onSubmit={save} className="mt-3 flex gap-2">
          <input id={`key-${keyName}`} type="password" autoFocus value={value} onChange={(e) => setValue(e.target.value)} placeholder={`Paste your ${label} key`} aria-label={`${label} key`} className={cn(inputClass, 'h-9 flex-1 font-mono')} />
          <Button type="submit" variant="primary" className="h-9" disabled={setKey.isPending || !value.trim()}>{setKey.isPending ? 'Saving…' : 'Save'}</Button>
        </form>
      )}
      {setKey.isError && <p className="mt-2 text-[12px] text-bad">{apiErrorMessage(setKey.error, 'The key could not be saved.')}</p>}
    </Card>
  )
}

function KeysSection() {
  return (
    <section className="grid gap-8">
      <div>
        <SectionTitle
          title="Models"
          description="Every AI feature talks to an OpenAI-compatible server. By default that is the local llama-server router (config/llama-router.ini); point it at OpenAI or another provider to switch. Values saved here override your environment file; leave a field empty to use the default shown."
        />
        <ModelsCard />
      </div>
      <div>
        <SectionTitle title="Keys" description="Keys saved here are stored in the database and override the ones in your environment file." />
        <div className="grid gap-3">
          {KEYS.map((k) => <KeyRow key={k.key} keyName={k.key} label={k.label} hint={k.hint} />)}
        </div>
      </div>
    </section>
  )
}

/* ── Account ── */

function AccountSection() {
  const user = useCurrentUser()
  if (!user) return null
  return (
    <section className="grid gap-8">
      <div>
        <SectionTitle title="Account" />
        <Card className="grid gap-1 p-4 text-[13px]">
          <p className="flex items-center gap-2 text-[14px] font-medium text-fg">
            {user.display_name} <Chip tone={user.role === 'admin' ? 'accent' : 'neutral'}>{user.role === 'admin' ? 'Admin' : 'User'}</Chip>
          </p>
          <p className="text-fg-2">{user.email}</p>
          {user.last_login_at && <p className="text-[12px] text-fg-3">Last login {timeAgo(user.last_login_at)}</p>}
        </Card>
      </div>
      <div>
        <SectionTitle title="Password" description="Changing it logs out your other sessions. Forgot it? Your admin can issue a temporary one." />
        <Card className="max-w-[420px] p-4"><PasswordForm /></Card>
      </div>
    </section>
  )
}

/* ── Users ── */

/** A temporary password is only ever shown once, right after it is made. */
function IssuedPassword({ issued, onClose }: { issued: IssuedUser; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = () => {
    navigator.clipboard?.writeText(issued.temporary_password).then(() => setCopied(true)).catch(() => {})
  }
  return (
    <Notice tone="warn" title={`Temporary password for ${issued.email}`}>
      <div className="mt-1 grid gap-2">
        <p className="flex flex-wrap items-center gap-2">
          <code className="rounded-md border border-line bg-surface-2 px-2 py-1 font-mono text-[13px] text-fg">{issued.temporary_password}</code>
          <Button variant="secondary" size="sm" onClick={copy}>{copied ? <><Check /> Copied</> : 'Copy'}</Button>
        </p>
        <p>Give it to them privately. It is not shown again; they choose their own password when they first log in.</p>
        <div><Button variant="ghost" size="sm" onClick={onClose}>Done</Button></div>
      </div>
    </Notice>
  )
}

function UsersSection() {
  const me = useCurrentUser()
  const { data: users, isLoading, isError, error } = useUsers()
  const create = useCreateUser()
  const updateUser = useUpdateUser()
  const reset = useResetPassword()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<Role>('user')
  const [issued, setIssued] = useState<IssuedUser | null>(null)

  const add = (e: FormEvent) => {
    e.preventDefault()
    create.mutate({ email, display_name: name, role }, {
      onSuccess: (made) => {
        setIssued(made)
        setEmail('')
        setName('')
        setRole('user')
      },
    })
  }
  const resetFor = (u: AuthUser) => {
    if (!window.confirm(`Reset the password of ${u.email}? Their sessions end and they get a new temporary password.`)) return
    reset.mutate(u.id, { onSuccess: setIssued })
  }
  const failure = updateUser.error ?? reset.error

  return (
    <section className="grid gap-6">
      <SectionTitle
        title="Users"
        description={<>There is no public sign-up: add people here and pass on their temporary password. Users can read everything, save lists, ask questions and build maps up to a daily limit; admins can also change sources, models, users and maps. What each person has used, and the limits, are under <Link to="/settings/usage" className="text-accent hover:underline">Usage</Link>.</>}
      />
      <Card className="p-4">
        <form onSubmit={add} className="grid gap-3 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto_auto] sm:items-end">
          <label className="grid gap-1">
            <span className="text-[12px] text-fg-3">Email</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={cn(inputClass, 'h-9')} />
          </label>
          <label className="grid gap-1">
            <span className="text-[12px] text-fg-3">Name</span>
            <input required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} className={cn(inputClass, 'h-9')} />
          </label>
          <label className="grid gap-1">
            <span className="text-[12px] text-fg-3">Role</span>
            <select value={role} onChange={(e) => setRole(e.target.value as Role)} className={cn(inputClass, 'h-9 pr-6')}>
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </label>
          <Button type="submit" variant="primary" className="h-9" disabled={create.isPending}>{create.isPending ? 'Adding…' : 'Add user'}</Button>
        </form>
        {create.isError && <p className="mt-2 text-[12px] text-bad">{apiErrorMessage(create.error, 'The account could not be created.')}</p>}
      </Card>
      {issued && <IssuedPassword issued={issued} onClose={() => setIssued(null)} />}
      {failure && <Notice tone="error">{apiErrorMessage(failure, 'That change could not be made.')}</Notice>}
      {isLoading ? <Spinner label="Loading users…" /> : isError ? (
        <Notice tone="error">{apiErrorMessage(error, 'The users could not be loaded.')}</Notice>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[640px] text-left text-[13px]">
            <thead className="border-b border-line bg-surface text-[12px] text-fg-3">
              <tr>
                <th className="px-4 py-2.5 font-medium">Name</th>
                <th className="px-4 py-2.5 font-medium">Role</th>
                <th className="px-4 py-2.5 font-medium">Last login</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {(users ?? []).map((u) => {
                const self = u.id === me?.id
                return (
                  <tr key={u.id} className="border-b border-line last:border-0">
                    <td className="px-4 py-3">
                      <p className="text-fg">{u.display_name}{self && <span className="text-fg-3"> (you)</span>}</p>
                      <p className="text-[12px] text-fg-3">{u.email}</p>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={u.role}
                        disabled={self || updateUser.isPending}
                        onChange={(e) => updateUser.mutate({ id: u.id, role: e.target.value as Role })}
                        aria-label={`Role of ${u.email}`}
                        className={cn(inputClass, 'pr-6')}
                      >
                        <option value="user">User</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td className="px-4 py-3 text-fg-2">{u.last_login_at ? timeAgo(u.last_login_at) : 'Never'}</td>
                    <td className="px-4 py-3">
                      {!u.is_active ? <Chip tone="bad">Deactivated</Chip> : u.must_change_password ? <Chip tone="warn">Temporary password</Chip> : <Chip tone="good">Active</Chip>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-1.5">
                        <Button variant="ghost" size="sm" onClick={() => resetFor(u)} disabled={self || reset.isPending}>Reset password</Button>
                        <Button variant="secondary" size="sm" onClick={() => updateUser.mutate({ id: u.id, is_active: !u.is_active })} disabled={self || updateUser.isPending}>
                          {u.is_active ? 'Deactivate' : 'Reactivate'}
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/* ── Appearance ── */

const LOOKS: { value: Accent; label: string; note: string }[] = [
  { value: 'gold', label: 'Gold', note: 'Warm bronze and starlight, like a temple at night.' },
  { value: 'indigo', label: 'Indigo', note: 'Cool silver and violet, a more technical feel.' },
]

function AppearanceSection() {
  const accent = useAppStore((s) => s.accent)
  const setAccent = useAppStore((s) => s.setAccent)
  return (
    <section>
      <SectionTitle title="Appearance" description="Athena has one dark look in two accents. The change applies everywhere straight away." />
      <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Accent colour">
        {LOOKS.map((look) => (
          <button
            key={look.value}
            type="button"
            role="radio"
            aria-checked={accent === look.value}
            data-accent={look.value}
            onClick={() => setAccent(look.value)}
            className={cn(
              'flex items-center gap-4 rounded-xl border bg-surface p-4 text-left transition-colors',
              accent === look.value ? 'border-accent-line shadow-[0_0_0_3px_var(--accent-soft)]' : 'border-line hover:border-line-strong',
            )}
          >
            <OwlCoin size={52} full />
            <span className="grid gap-0.5">
              <span className="text-[14px] font-medium text-fg">{look.label}</span>
              <span className="text-[12.5px] text-fg-3">{look.note}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}

/* ── Clusters ── */

function ClustersSection() {
  const { data: clusters, isLoading } = useClusters()
  const { data: health } = useScoringHealth()
  return (
    <section className="grid gap-5">
      <SectionTitle title="Clusters" description="Groups the clustering job builds from item embeddings. Small groups are hidden on the Clusters page." />
      {health && (
        <div className="grid gap-3 sm:grid-cols-3">
          <Stat label="Items" value={health.total_items.toLocaleString()} />
          <Stat label="Clusters" value={clusters?.length ?? '—'} />
          <Stat label="Trending" value={health.trending_items} sub={`${health.trending_percentage}% of items`} />
        </div>
      )}
      {isLoading ? (
        <Spinner label="Loading clusters…" />
      ) : clusters?.length ? (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full min-w-[560px] text-left text-[13px]">
            <thead className="border-b border-line bg-surface text-[12px] text-fg-3">
              <tr>
                <th className="px-4 py-2.5 font-normal">Label</th>
                <th className="px-4 py-2.5 font-normal">Summary</th>
                <th className="px-4 py-2.5 text-right font-normal">Items</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {clusters.map((c) => (
                <tr key={c.id} className="bg-bg">
                  <td className="px-4 py-3 font-medium whitespace-nowrap text-fg">{c.label ?? 'Unnamed'}</td>
                  <td className="px-4 py-3 text-fg-2"><span className="line-clamp-2">{c.summary ?? '—'}</span></td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums text-fg-2">{c.item_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Notice title="No clusters yet">They are built automatically once enough items have been fetched.</Notice>
      )}
    </section>
  )
}

/* ── Health ── */

function HealthSection() {
  const { data: scoring, isLoading: scoringLoading } = useScoringHealth()
  const { data: fetches, isLoading: fetchLoading } = useFetchHealth()
  return (
    <section className="grid gap-6">
      <div>
        <SectionTitle title="Scoring" description="How much of the library has a relevance score." />
        {scoringLoading ? <Spinner /> : scoring && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Items" value={scoring.total_items.toLocaleString()} />
            <Stat label="Scored" value={scoring.scored_items.toLocaleString()} sub={`${scoring.unscored_items.toLocaleString()} waiting`} />
            <Stat label="Average score" value={scoring.average_score.toFixed(2)} />
            <Stat label="Queue" value={scoring.scoring_queue_depth} sub="jobs waiting" />
          </div>
        )}
      </div>
      <div>
        <SectionTitle title="Fetching" description="How often fetching from sources succeeds." />
        {fetchLoading ? <Spinner /> : fetches && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Fetches" value={fetches.total_fetches.toLocaleString()} />
            <Stat label="Succeeded" value={fetches.successful_fetches.toLocaleString()} />
            <Stat label="Failed" value={fetches.failed_fetches.toLocaleString()} />
            <Stat label="Success rate" value={`${fetches.success_rate}%`} />
          </div>
        )}
      </div>
    </section>
  )
}

/* ── Sync ── */

function SyncSection() {
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const start = async () => {
    setStarting(true)
    setError(null)
    try {
      await apiClient.post('/sync')
    } catch (e) {
      setError(apiErrorMessage(e, 'The sync could not be started.'))
    } finally {
      setStarting(false)
    }
  }
  return (
    <section>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionTitle title="Sync log" description="Live output from the worker while it fetches from your sources. A sync also runs on its own schedule." />
        <Button variant="secondary" onClick={start} disabled={starting}><RefreshCw className={starting ? 'animate-spin' : undefined} /> Sync now</Button>
      </div>
      {error && <Notice tone="error" className="mb-3" title={error}>Check that the API and the Celery worker are running.</Notice>}
      <SyncLog />
    </section>
  )
}
