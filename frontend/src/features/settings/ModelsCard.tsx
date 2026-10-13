import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiErrorMessage } from '../../api/error'
import { useModelSettings, useTestModels, useUpdateModelSettings, type ModelTestResult } from '../../api/queries/app_settings'
import { Button } from '../../ui/Button'
import { Card } from '../../ui/Card'
import { Chip } from '../../ui/Chip'
import { Notice } from '../../ui/Notice'
import { Spinner } from '../../ui/Spinner'
import { cn } from '../../ui/cn'
import { inputClass } from '../../ui/inputClass'

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

/**
 * The chat and embedding endpoints and models, with a test of the saved ones. Settings → Models and keys and the
 * setup guide share it; ``onTested`` hears whether both models answered.
 */
export function ModelsCard({ onTested }: { onTested?: (ok: boolean) => void }) {
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
        <Button variant="secondary" className="ml-auto" disabled={test.isPending || dirty} title={dirty ? 'Save first' : undefined}
          onClick={() => test.mutate(undefined, { onSuccess: (r) => onTested?.(r.chat.ok && r.embed.ok), onError: () => onTested?.(false) })}>
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
