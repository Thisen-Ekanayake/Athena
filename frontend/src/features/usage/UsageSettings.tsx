import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { apiErrorMessage } from '../../api/error'
import { useIsAdmin } from '../../api/queries/auth'
import {
  useAppUsage, useMyUsage, useSaveUsageSettings, useUsageSettings,
  type Allowance, type FeatureUsage, type UsageCounts,
} from '../../api/queries/usage'
import { Button } from '../../ui/Button'
import { Card, CardHeader } from '../../ui/Card'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'
import { DailyBars } from './DailyBars'
import { compact, monthName, resetDay, usd } from './format'

function Title({ title, description }: { title: string; description?: ReactNode }) {
  return (
    <div className="mb-4 grid gap-1">
      <h2 className="text-[16px] font-semibold text-fg">{title}</h2>
      {description && <p className="max-w-[68ch] text-[13px] text-fg-2">{description}</p>}
    </div>
  )
}

function Tile({ label, value, sub, children }: { label: string; value: ReactNode; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="grid content-start gap-1 rounded-xl border border-line bg-surface p-4">
      <p className="text-[12px] text-fg-3">{label}</p>
      <p className="text-[22px] font-medium text-fg">{value}</p>
      {children}
      {sub && <p className="text-[12px] text-fg-3">{sub}</p>}
    </div>
  )
}

/** How much of a limit is used: the accent, then warn from 80%, then bad when it is spent. */
function Meter({ used, limit, label }: { used: number; limit: number; label: string }) {
  const share = limit > 0 ? Math.min(used / limit, 1) : 0
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-surface-3" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={limit} aria-valuenow={Math.min(used, limit)}>
      <div className={cn('h-full rounded-full', share >= 1 ? 'bg-bad' : share >= 0.8 ? 'bg-warn' : 'bg-accent')} style={{ width: `${share * 100}%` }} />
    </div>
  )
}

const tokens = (c: UsageCounts) => c.input_tokens + c.output_tokens

/** Rows of calls, tokens in and out, and cost. */
function CountsTable({ head, rows }: { head: string; rows: { key: string; name: ReactNode; counts: UsageCounts }[] }) {
  if (!rows.length) return <p className="px-4 pb-4 text-[13px] text-fg-3">Nothing yet this month.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-left text-[13px]">
        <thead className="border-y border-line text-[12px] text-fg-3">
          <tr>
            <th className="px-4 py-2 font-medium">{head}</th>
            <th className="px-4 py-2 text-right font-medium">Calls</th>
            <th className="px-4 py-2 text-right font-medium">Tokens in</th>
            <th className="px-4 py-2 text-right font-medium">Tokens out</th>
            <th className="px-4 py-2 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map((r) => (
            <tr key={r.key} className="border-b border-line last:border-0">
              <td className="px-4 py-2.5 text-fg">{r.name}</td>
              <td className="px-4 py-2.5 text-right text-fg-2">{r.counts.calls.toLocaleString()}</td>
              <td className="px-4 py-2.5 text-right text-fg-2">{r.counts.input_tokens.toLocaleString()}</td>
              <td className="px-4 py-2.5 text-right text-fg-2">{r.counts.output_tokens.toLocaleString()}</td>
              <td className="px-4 py-2.5 text-right text-fg-2">{usd(r.counts.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const featureRows = (features: FeatureUsage[]) => features.map((f) => ({ key: f.feature, name: f.label, counts: f }))

/** Each person's model use this month and today's allowances; for admins also the whole app and its limits. */
export function UsageSettings() {
  const isAdmin = useIsAdmin()
  return (
    <section className="grid gap-10">
      <MyUsage />
      {isAdmin && <AppUsage />}
      {isAdmin && <Limits />}
    </section>
  )
}

function MyUsage() {
  const { data, isLoading, isError, error } = useMyUsage()
  if (isLoading) return <Spinner label="Loading your usage…" />
  if (isError || !data) return <Notice tone="error">{apiErrorMessage(error, 'Your usage could not be loaded.')}</Notice>
  const admin = data.role === 'admin'
  const allowances = data.allowances.filter((a) => a.limit !== null)

  return (
    <div className="grid gap-5">
      <Title
        title="Your usage"
        description={`Model calls you started in ${monthName(data.month)}: questions, idea checks, literature reviews and map questions. The month starts again on ${resetDay(data.resets_at)}.`}
      />
      {data.budget_reached && (
        <Notice tone="warn" title="This month's model budget is used up">
          Questions, idea checks, literature reviews and map building are paused until {resetDay(data.resets_at)}. An admin can raise the budget.
        </Notice>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <Tile
          label="Tokens this month"
          value={compact(data.tokens_used)}
          sub={data.token_cap && !admin ? `of ${compact(data.token_cap)} a month` : admin ? 'Admins have no cap' : 'No monthly cap'}
        >
          {data.token_cap && !admin ? <Meter used={data.tokens_used} limit={data.token_cap} label="Tokens used this month" /> : null}
        </Tile>
        <Tile label="Calls" value={data.totals.calls.toLocaleString()} />
        <Tile label="Cost" value={usd(data.totals.cost_usd)} sub={data.totals.cost_usd ? undefined : 'Local models cost nothing'} />
      </div>
      {admin ? (
        <p className="text-[13px] text-fg-3">Admins have no daily allowances.</p>
      ) : (
        <Card>
          <CardHeader title="Today's allowances" action={<span className="text-[12px] text-fg-3">Reset at midnight UTC</span>} />
          <ul className="grid gap-3 px-4 pb-4 sm:grid-cols-2">
            {allowances.map((a) => <AllowanceRow key={a.action} allowance={a} />)}
          </ul>
        </Card>
      )}
      <Card>
        <CardHeader title="By feature" />
        <CountsTable head="Feature" rows={featureRows(data.features)} />
      </Card>
    </div>
  )
}

function AllowanceRow({ allowance: a }: { allowance: Allowance }) {
  const limit = a.limit ?? 0
  const label = a.label.charAt(0).toUpperCase() + a.label.slice(1)
  return (
    <li className="grid gap-1.5">
      <p className="flex items-baseline justify-between gap-2 text-[13px]">
        <span className="text-fg-2">{label}</span>
        <span className="tabular-nums text-fg-3">{a.action.endsWith('_tokens') ? `${compact(a.used)} of ${compact(limit)}` : `${a.used} of ${limit}`}</span>
      </p>
      <Meter used={a.used} limit={limit} label={label} />
    </li>
  )
}

function AppUsage() {
  const { data, isLoading, isError, error } = useAppUsage(true)
  if (isLoading) return <Spinner label="Loading the app's usage…" />
  if (isError || !data) return <Notice tone="error">{apiErrorMessage(error, "The app's usage could not be loaded.")}</Notice>
  const people = data.users.map((u) => ({
    key: u.user_id ?? 'background',
    name: u.user_id ? <span>{u.name} <span className="text-fg-3">{u.email}</span></span> : <span className="text-fg-2">Background work</span>,
    counts: u,
  }))
  const models = data.models.map((m) => ({
    key: `${m.kind}:${m.model}`,
    name: <span className="font-mono text-[12.5px]">{m.model || 'unknown'} <span className="font-sans text-fg-3">{m.kind === 'embed' ? 'embeddings' : 'chat'}</span></span>,
    counts: m,
  }))

  return (
    <div className="grid gap-5">
      <Title
        title="Everyone"
        description={<>Every model call in {monthName(data.month)}, including background work: summaries, map building and embeddings. Costs use the prices in <Link to="/settings/keys" className="text-accent hover:underline">Models and keys</Link>.</>}
      />
      {data.over_budget && (
        <Notice tone="warn" title="The monthly budget is used up">
          Users other than admins can't start model calls, and background summaries are paused until {resetDay(data.resets_at)}.
        </Notice>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <Tile
          label="Spent this month"
          value={usd(data.month_spend_usd)}
          sub={data.budget_usd ? `of a ${usd(data.budget_usd)} budget` : 'No monthly budget'}
        >
          {data.budget_usd ? <Meter used={data.month_spend_usd} limit={data.budget_usd} label="Monthly budget spent" /> : null}
        </Tile>
        <Tile label="Tokens" value={compact(tokens(data.totals))} sub={`${compact(data.totals.input_tokens)} in · ${compact(data.totals.output_tokens)} out`} />
        <Tile label="Calls" value={data.totals.calls.toLocaleString()} />
      </div>
      <Card>
        <CardHeader title="Tokens per day" action={<span className="text-[12px] text-fg-3">UTC</span>} />
        <div className="px-4 pt-6 pb-4">
          <DailyBars month={data.month} daily={data.daily} label={`Tokens per day in ${monthName(data.month)}`} />
        </div>
      </Card>
      <Card>
        <CardHeader title="By person" />
        <CountsTable head="Person" rows={people} />
      </Card>
      <Card>
        <CardHeader title="By feature" />
        <CountsTable head="Feature" rows={featureRows(data.features)} />
      </Card>
      <Card>
        <CardHeader title="By model" />
        <CountsTable head="Model" rows={models} />
      </Card>
    </div>
  )
}

const BUDGET_FIELDS = [
  { key: 'MONTHLY_BUDGET_USD', label: 'Monthly budget (USD)', hint: 'The whole app, a calendar month in UTC. Past it, users other than admins are refused and summaries pause. 0 for none.' },
  { key: 'USER_MONTHLY_TOKENS', label: 'Monthly tokens per person', hint: 'Each user other than an admin. With a local model nothing costs money, so this is the limit that shares the GPU. 0 for none.' },
]

function Limits() {
  const { data } = useUsageSettings(true)
  const save = useSaveUsageSettings()
  const [edits, setEdits] = useState<Record<string, string>>({})
  if (!data) return <Spinner label="Loading the limits…" />
  const form = { ...data.values, ...edits }
  const dirty = Object.keys(edits).length > 0
  const field = (key: string, label: string, hint?: string) => (
    <label key={key} className="grid content-start gap-1">
      <span className="text-[12px] text-fg-3">{label}</span>
      <input
        inputMode="decimal"
        value={form[key] ?? ''}
        onChange={(e) => setEdits((x) => ({ ...x, [key]: e.target.value }))}
        placeholder={data.defaults[key]}
        className={cn(inputClass, 'font-mono')}
      />
      {hint && <span className="text-[11.5px] text-fg-3">{hint}</span>}
    </label>
  )

  return (
    <div>
      <Title title="Budget and limits" description="Admins are never limited. Leave a field empty to use the default shown." />
      <Card className="grid gap-5 p-4">
        <div className="grid gap-3 sm:grid-cols-2">{BUDGET_FIELDS.map((f) => field(f.key, f.label, f.hint))}</div>
        <fieldset className="grid gap-3">
          <legend className="mb-1 text-[13px] font-medium text-fg">Daily allowances per person</legend>
          <div className="grid gap-3 sm:grid-cols-3">
            {Object.entries(data.limit_labels).map(([key, label]) => field(key, label.charAt(0).toUpperCase() + label.slice(1)))}
          </div>
        </fieldset>
        <div className="flex items-center gap-2">
          <Button variant="primary" disabled={!dirty || save.isPending} onClick={() => save.mutate(edits, { onSuccess: () => setEdits({}) })}>
            {save.isPending ? 'Saving…' : 'Save'}
          </Button>
          {dirty && <Button variant="ghost" onClick={() => setEdits({})}>Discard</Button>}
        </div>
        {save.isError && <p className="text-[12px] text-bad">{apiErrorMessage(save.error, 'The limits could not be saved.')}</p>}
      </Card>
    </div>
  )
}
