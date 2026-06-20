import { useState, useMemo } from 'react'
import { useSources, useToggleSource, useAddSource, useUpdateSource } from '../api/queries/sources'
import { useApiKeys, useSetApiKey, useDeleteApiKey } from '../api/queries/app_settings'
import { useClusters, useScoringHealth, useFetchHealth } from '../api/queries/phase4'
import type { Source } from '../api/client'
import { Alert } from '../components/shared/Alert'
import { Check, Orbit, ExternalLink, Shield, Cpu, Activity, Plus, Key, Eye, EyeOff, Trash2, GitBranch, BarChart2, RefreshCw, Pencil, X, ArrowDownUp } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

function safeHostname(url: string): string {
  try { return new URL(url).hostname } catch { return url }
}

type SortKey = 'name' | 'created' | 'health' | 'protocol' | 'inertia'

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: 'name', label: 'Alphabetical' },
  { value: 'created', label: 'Date Created' },
  { value: 'health', label: 'Health Status' },
  { value: 'protocol', label: 'Protocol' },
  { value: 'inertia', label: 'Inertia' },
]

function sortSources(sources: Source[] | undefined, key: SortKey): Source[] {
  if (!sources) return []
  const byName = (a: Source, b: Source) => a.name.localeCompare(b.name)
  const copy = [...sources]
  switch (key) {
    case 'created':
      // Newest first; fall back to name when timestamps are equal/missing.
      return copy.sort((a, b) =>
        (b.created_at || '').localeCompare(a.created_at || '') || byName(a, b))
    case 'health':
      // Worst health first (most consecutive failures), then name.
      return copy.sort((a, b) =>
        (b.consecutive_failures - a.consecutive_failures) || byName(a, b))
    case 'protocol':
      return copy.sort((a, b) => a.type.localeCompare(b.type) || byName(a, b))
    case 'inertia':
      // Active sources first, then name.
      return copy.sort((a, b) =>
        (Number(b.is_active) - Number(a.is_active)) || byName(a, b))
    case 'name':
    default:
      return copy.sort(byName)
  }
}

const KEY_LABELS: Record<string, { label: string; hint: string }> = {
  OPENAI_API_KEY: { label: 'OpenAI API Key', hint: 'Used for embeddings, summarisation, search, and scoring.' },
  SEMANTIC_SCHOLAR_API_KEY: { label: 'Semantic Scholar API Key', hint: 'Used to enrich papers with citation counts. Optional — works without one at lower rate limits.' },
}

function ApiKeyRow({ keyName }: { keyName: string }) {
  const { data: keys } = useApiKeys()
  const setKey = useSetApiKey()
  const deleteKey = useDeleteApiKey()

  const info = keys?.find(k => k.key === keyName)
  const meta = KEY_LABELS[keyName]

  const [editing, setEditing] = useState(false)
  const [input, setInput] = useState('')
  const [revealed, setRevealed] = useState(false)

  const handleSave = () => {
    if (!input.trim()) return
    setKey.mutate({ key: keyName, value: input }, {
      onSuccess: () => { setEditing(false); setInput('') },
    })
  }

  return (
    <div className="glass-void border border-white/5 rounded-xl p-5 space-y-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-display font-bold text-white">{meta.label}</span>
            {info?.is_set ? (
              <span className="text-[10px] font-mono font-bold text-[#5AE07F] border border-[#5AE07F]/30 px-1.5 py-0.5 rounded uppercase">SET</span>
            ) : (
              <span className="text-[10px] font-mono font-bold text-text-ghost border border-white/10 px-1.5 py-0.5 rounded uppercase">NOT SET</span>
            )}
          </div>
          <p className="text-[11px] text-text-muted mt-0.5">{meta.hint}</p>
          {info?.is_set && !editing && (
            <div className="flex items-center gap-2 mt-2">
              <span className="font-mono text-[12px] text-text-secondary">
                {revealed ? info.masked_value : '••••••••••••••••'}
              </span>
              <button onClick={() => setRevealed(r => !r)} className="text-text-ghost hover:text-text-primary transition-colors">
                {revealed ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              </button>
            </div>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          {info?.is_set && !editing && (
            <button
              onClick={() => deleteKey.mutate(keyName)}
              disabled={deleteKey.isPending}
              className="p-2 rounded-lg glass-base border border-white/5 text-text-ghost hover:text-[#E05A6B] hover:border-[#E05A6B]/30 transition-all"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={() => { setEditing(e => !e); setInput('') }}
            className="px-4 py-2 rounded-lg glass-base border border-white/10 text-text-secondary hover:text-white hover:border-accent-primary/30 transition-all font-display font-bold text-[11px] uppercase tracking-wider"
          >
            {editing ? 'CANCEL' : info?.is_set ? 'UPDATE' : 'SET KEY'}
          </button>
        </div>
      </div>

      <AnimatePresence>
        {editing && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="overflow-hidden"
          >
            <div className="flex gap-2 pt-1">
              <input
                type="password"
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleSave()}
                placeholder={`Paste your ${meta.label}...`}
                autoFocus
                className="flex-1 glass-base border border-white/10 focus:border-accent-primary text-white rounded-xl px-4 py-2.5 text-sm font-mono focus:outline-none transition-all placeholder:text-text-ghost"
              />
              <button
                onClick={handleSave}
                disabled={setKey.isPending || !input.trim()}
                className="px-6 py-2.5 bg-accent-primary text-white rounded-xl font-display font-bold text-[12px] hover:shadow-glow-primary transition-all disabled:opacity-50 disabled:grayscale uppercase"
              >
                {setKey.isPending ? 'SAVING...' : 'SAVE'}
              </button>
            </div>
            {setKey.isError && (
              <p className="text-[11px] text-[#E05A6B] mt-2">{(setKey.error as any)?.message || 'Failed to save key.'}</p>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="glass-void border border-white/5 rounded-xl p-5">
      <div className="text-[10px] font-display font-bold text-text-ghost uppercase tracking-widest mb-2">{label}</div>
      <div className="text-2xl font-display font-bold text-white">{value}</div>
      {sub && <div className="text-[11px] text-text-muted mt-1">{sub}</div>}
    </div>
  )
}

function LogicClustersPanel() {
  const { data: clusters, isLoading } = useClusters()
  const { data: health } = useScoringHealth()

  return (
    <div className="space-y-8">
      <section className="glass-opaque rounded-2xl p-8 border border-white/5 shadow-2xl overflow-hidden relative group">
        <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity">
          <GitBranch className="w-32 h-32 text-accent-primary" />
        </div>
        <h3 className="text-xl font-display font-bold text-white mb-2 flex items-center gap-3">
          <GitBranch className="w-5 h-5 text-accent-primary" />
          Logic Clusters
        </h3>
        <p className="text-sm text-text-secondary mb-8 font-medium">Semantic topic groups auto-generated by the clustering pipeline.</p>

        {health && (
          <div className="grid grid-cols-3 gap-4 mb-8">
            <StatCard label="Total Items" value={health.total_items.toLocaleString()} />
            <StatCard label="Active Clusters" value={clusters?.length ?? '—'} />
            <StatCard label="Trending" value={health.trending_items} sub={`${health.trending_percentage}% of content`} />
          </div>
        )}

        {isLoading ? (
          <div className="flex justify-center py-12">
            <div className="w-8 h-8 rounded-full border-2 border-accent-primary border-t-transparent animate-spin" />
          </div>
        ) : clusters && clusters.length > 0 ? (
          <div className="glass-opaque rounded-2xl overflow-hidden border border-white/5">
            <table className="min-w-full divide-y divide-white/5">
              <thead className="glass-void/50">
                <tr>
                  <th className="px-6 py-4 text-left text-xs font-display font-bold text-text-ghost uppercase tracking-widest">Label</th>
                  <th className="px-6 py-4 text-left text-xs font-display font-bold text-text-ghost uppercase tracking-widest">Summary</th>
                  <th className="px-6 py-4 text-right text-xs font-display font-bold text-text-ghost uppercase tracking-widest">Items</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {clusters.map((c, idx) => (
                  <motion.tr key={c.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: idx * 0.04 }} className="hover:bg-white/[0.02] transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="text-[13px] font-bold text-white">{c.label ?? 'Unlabelled'}</span>
                    </td>
                    <td className="px-6 py-4 max-w-sm">
                      <span className="text-[12px] text-text-secondary line-clamp-2">{c.summary ?? '—'}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <span className="text-[13px] font-mono font-bold text-accent-primary">{c.item_count}</span>
                    </td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex flex-col items-center py-16 opacity-40">
            <GitBranch className="w-12 h-12 text-text-ghost mb-4" />
            <p className="text-sm font-display font-bold text-text-muted uppercase tracking-widest">No clusters yet</p>
            <p className="text-xs text-text-ghost mt-2">Clusters are generated automatically once enough content is ingested.</p>
          </div>
        )}
      </section>
    </div>
  )
}

function SystemCorePanel() {
  const { data: scoring, isLoading: scoringLoading } = useScoringHealth()
  const { data: fetch_, isLoading: fetchLoading } = useFetchHealth()

  return (
    <div className="space-y-8">
      <section className="glass-opaque rounded-2xl p-8 border border-white/5 shadow-2xl overflow-hidden relative group">
        <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity">
          <BarChart2 className="w-32 h-32 text-accent-primary" />
        </div>
        <h3 className="text-xl font-display font-bold text-white mb-2 flex items-center gap-3">
          <BarChart2 className="w-5 h-5 text-accent-primary" />
          Scoring Health
        </h3>
        <p className="text-sm text-text-secondary mb-8 font-medium">Scoring pipeline metrics across all ingested content.</p>
        {scoringLoading ? (
          <div className="flex justify-center py-8"><div className="w-8 h-8 rounded-full border-2 border-accent-primary border-t-transparent animate-spin" /></div>
        ) : scoring ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Items" value={scoring.total_items.toLocaleString()} />
            <StatCard label="Scored" value={scoring.scored_items.toLocaleString()} sub={`${scoring.unscored_items.toLocaleString()} unscored`} />
            <StatCard label="Avg Score" value={scoring.average_score.toFixed(3)} />
            <StatCard label="Queue Depth" value={scoring.scoring_queue_depth} sub="pending jobs" />
          </div>
        ) : null}
      </section>

      <section className="glass-opaque rounded-2xl p-8 border border-white/5 shadow-2xl overflow-hidden relative group">
        <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity">
          <RefreshCw className="w-32 h-32 text-accent-secondary" />
        </div>
        <h3 className="text-xl font-display font-bold text-white mb-2 flex items-center gap-3">
          <RefreshCw className="w-5 h-5 text-accent-secondary" />
          Fetch Health
        </h3>
        <p className="text-sm text-text-secondary mb-8 font-medium">Source harvest pipeline success and failure rates.</p>
        {fetchLoading ? (
          <div className="flex justify-center py-8"><div className="w-8 h-8 rounded-full border-2 border-accent-secondary border-t-transparent animate-spin" /></div>
        ) : fetch_ ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard label="Total Fetches" value={fetch_.total_fetches.toLocaleString()} />
            <StatCard label="Successful" value={fetch_.successful_fetches.toLocaleString()} />
            <StatCard label="Failed" value={fetch_.failed_fetches} />
            <StatCard label="Success Rate" value={`${fetch_.success_rate}%`} />
          </div>
        ) : null}
      </section>
    </div>
  )
}

export function SettingsPage() {
  const { data: sources, isLoading: sourcesLoading } = useSources()
  const toggleSource = useToggleSource()
  const addSource = useAddSource()
  const updateSource = useUpdateSource()

  const [activeSection, setActiveSection] = useState('harvest')
  const [urlInput, setUrlInput] = useState('')
  const [previewData, setPreviewData] = useState<any>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editUrl, setEditUrl] = useState('')
  const [sortBy, setSortBy] = useState<SortKey>('name')

  const sortedSources = useMemo(() => sortSources(sources, sortBy), [sources, sortBy])

  const startEdit = (source: { id: string, name: string, url: string }) => {
    setEditingId(source.id)
    setEditName(source.name)
    setEditUrl(source.url)
    updateSource.reset()
  }

  const cancelEdit = () => {
    setEditingId(null)
    updateSource.reset()
  }

  const saveEdit = (id: string) => {
    updateSource.mutate(
      { id, name: editName.trim(), url: editUrl.trim() },
      { onSuccess: () => setEditingId(null) }
    )
  }

  const handleDetect = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!urlInput) return
    
    addSource.mutate({ url: urlInput }, {
      onSuccess: (data) => {
        setPreviewData(data)
      }
    })
  }

  const handleConfirmAdd = async () => {
    addSource.mutate({ url: urlInput, confirm: true }, {
      onSuccess: () => {
        setUrlInput('')
        setPreviewData(null)
      }
    })
  }

  return (
    <div className="flex-1 flex flex-col min-h-screen">
      <div className="glass-base border-b border-white/5 pt-28 pb-10 px-8">
        <div className="max-w-[1200px] mx-auto">
          <h1 className="text-3xl font-display font-bold text-white tracking-tight">Control <span className="text-accent-primary">Horizon</span></h1>
          <p className="text-sm text-text-muted mt-2 font-medium">Configure harvesting silos, intelligence resonators, and system core parameters.</p>
        </div>
      </div>

      <div className="max-w-[1200px] mx-auto w-full px-6 py-12 md:px-12 grid md:grid-cols-4 gap-12">
        {/* Settings Navigation Sidebar */}
        <div className="col-span-1 space-y-4">
          <div className="text-[10px] font-display font-bold text-text-ghost uppercase tracking-[0.2em] px-3">Subsystems</div>
          <nav className="space-y-1">
            {[
              { id: 'harvest', label: 'Content Harvest' },
              { id: 'apis', label: 'API Keys' },
              { id: 'clusters', label: 'Logic Clusters' },
              { id: 'core', label: 'System Core' },
            ].map(({ id, label }) => (
              <button
                key={id}
                onClick={() => setActiveSection(id)}
                className={`w-full text-left px-4 py-3 rounded-xl font-display font-bold text-[13px] transition-all ${
                  activeSection === id
                    ? 'bg-accent-primary/10 text-accent-primary border border-accent-primary/20 shadow-glow-primary'
                    : 'text-text-muted hover:text-text-primary hover:bg-white/5'
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
        </div>

        {/* Settings Content Pane */}
        <div className="col-span-1 md:col-span-3 space-y-12">

          {/* API Keys */}
          {activeSection === 'apis' && (
            <section className="glass-opaque rounded-2xl p-8 border border-white/5 shadow-2xl overflow-hidden relative group">
              <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity">
                <Key className="w-32 h-32 text-accent-primary" />
              </div>
              <h3 className="text-xl font-display font-bold text-white mb-2 flex items-center gap-3">
                <Key className="w-5 h-5 text-accent-primary" />
                API Keys
              </h3>
              <p className="text-sm text-text-secondary mb-8 font-medium">
                Configure external service credentials. Keys are stored in the database and take precedence over environment variables.
              </p>
              <div className="space-y-4">
                <ApiKeyRow keyName="OPENAI_API_KEY" />
                <ApiKeyRow keyName="SEMANTIC_SCHOLAR_API_KEY" />
              </div>
            </section>
          )}

          {/* Logic Clusters */}
          {activeSection === 'clusters' && <LogicClustersPanel />}

          {/* System Core */}
          {activeSection === 'core' && <SystemCorePanel />}

          {/* Add Custom Source */}
          {activeSection === 'harvest' && <>
          <section className="glass-opaque rounded-2xl p-8 border border-white/5 shadow-2xl overflow-hidden relative group">
             <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity">
               <Orbit className="w-32 h-32 text-accent-primary" />
             </div>
             
             <h3 className="text-xl font-display font-bold text-white mb-2 flex items-center gap-3">
               <Plus className="w-5 h-5 text-accent-primary" />
               Harvest Deployment
             </h3>
             <p className="text-sm text-text-secondary mb-8 font-medium">Instantiate a new intelligence harvesting node from any URL or RSS stream.</p>
             
             <AnimatePresence mode="wait">
               {!previewData ? (
                 <motion.form 
                  key="input"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: 20 }}
                  className="space-y-6" 
                  onSubmit={handleDetect}
                 >
                   <div className="space-y-2">
                     <label className="text-[10px] font-display font-bold text-text-ghost uppercase tracking-[0.15em] ml-1">Universal Resource Locator</label>
                     <div className="flex gap-3">
                       <input 
                         type="url" 
                         value={urlInput}
                         onChange={e => setUrlInput(e.target.value)}
                         placeholder="https://research.deepmind.com/blog"
                         className="flex-1 glass-void border border-white/5 text-white rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-accent-primary transition-all font-medium placeholder:text-text-ghost"
                       />
                       <button 
                         type="submit" 
                         disabled={addSource.isPending || !urlInput}
                         className="px-8 py-3 bg-accent-primary text-white rounded-xl font-display font-bold text-[13px] hover:shadow-glow-primary transition-all disabled:opacity-50 disabled:grayscale"
                       >
                         {addSource.isPending ? 'SCANNING...' : 'MATERIALIZE'}
                       </button>
                     </div>
                   </div>
                   {addSource.isError && (
                     <Alert type="error" title="Ingestion Failed">{(addSource.error as any)?.message || 'Target format unrecognized.'}</Alert>
                   )}
                 </motion.form>
               ) : (
                 <motion.div 
                  key="preview"
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  className="space-y-6"
                 >
                   <div className="glass-void border border-accent-secondary/20 rounded-xl p-6">
                     <div className="flex items-start justify-between mb-6">
                       <div className="flex gap-4">
                         <div className="w-12 h-12 rounded-xl bg-accent-secondary/10 flex items-center justify-center text-accent-secondary border border-accent-secondary/20 shadow-glow-secondary">
                           <Activity className="w-6 h-6" />
                         </div>
                         <div>
                           <h4 className="text-xl font-display font-bold text-white mb-1 flex items-center gap-2">
                             {previewData.source_name}
                           </h4>
                           <span className="text-[10px] font-mono font-bold text-accent-secondary border border-accent-secondary/30 px-2 py-0.5 rounded-md uppercase">
                             Stream Type: {previewData.source_type}
                           </span>
                         </div>
                       </div>
                       <Check className="w-6 h-6 text-green-500" />
                     </div>
                     
                     <div className="space-y-3">
                       <h5 className="text-[10px] font-display font-bold tracking-widest text-text-ghost uppercase flex items-center gap-2">
                         <Orbit className="w-3 h-3" />
                         HARVEST PREVIEW
                       </h5>
                       <div className="grid gap-2">
                         {previewData.sample_items?.slice(0, 2).map((item: any, idx: number) => (
                           <div key={idx} className="glass-base p-3 rounded-lg border border-white/5">
                             <h6 className="text-[13px] font-bold text-text-primary truncate">{item.title}</h6>
                           </div>
                         ))}
                       </div>
                     </div>
                     
                     <div className="mt-8 flex gap-3">
                        <button 
                          onClick={handleConfirmAdd}
                          disabled={addSource.isPending}
                          className="flex-1 py-3 bg-accent-secondary text-white rounded-xl font-display font-bold text-[13px] hover:shadow-glow-secondary transition-all"
                        >
                         {addSource.isPending ? 'DEPLOYING...' : 'CONFIRM DEPLOYMENT'}
                        </button>
                        <button 
                          onClick={() => { setPreviewData(null); addSource.reset() }}
                          className="px-6 py-3 glass-base border border-white/10 text-white rounded-xl font-display font-bold text-[13px] hover:bg-white/5 transition-all"
                        >
                          ABORT
                        </button>
                     </div>
                   </div>
                 </motion.div>
               )}
             </AnimatePresence>
          </section>

          {/* Active Sources Table */}
          <section className="space-y-6">
             <div className="flex items-center justify-between gap-4 px-1 flex-wrap">
               <div className="flex items-center gap-3">
                 <Shield className="w-5 h-5 text-accent-primary" />
                 <h3 className="text-xl font-display font-bold text-white">Active Reservoirs</h3>
                 <span className="text-[10px] font-mono font-bold text-accent-primary bg-accent-primary/10 border border-accent-primary/20 px-2 py-1 rounded-md tracking-wider">
                   {sources?.length ?? 0} SOURCE{(sources?.length ?? 0) === 1 ? '' : 'S'}
                 </span>
               </div>
               <div className="flex items-center gap-2">
                 <ArrowDownUp className="w-3.5 h-3.5 text-text-ghost" />
                 <label htmlFor="source-sort" className="text-[10px] font-display font-bold text-text-ghost uppercase tracking-[0.15em]">Sort</label>
                 <select
                   id="source-sort"
                   value={sortBy}
                   onChange={e => setSortBy(e.target.value as SortKey)}
                   className="glass-void border border-white/10 text-white rounded-lg px-3 py-1.5 text-xs font-display font-bold focus:outline-none focus:border-accent-primary transition-all cursor-pointer"
                 >
                   {SORT_OPTIONS.map(opt => (
                     <option key={opt.value} value={opt.value} className="bg-void text-white">{opt.label}</option>
                   ))}
                 </select>
               </div>
             </div>

             {updateSource.isError && (
               <Alert type="error" title="Update Failed">{(updateSource.error as any)?.response?.data?.detail || 'Could not update this source.'}</Alert>
             )}

             <div className="glass-opaque rounded-2xl overflow-hidden border border-white/5 shadow-xl">
               {sourcesLoading ? (
                 <div className="p-20 flex justify-center">
                   <div className="w-8 h-8 rounded-full border-2 border-accent-primary border-t-transparent animate-spin" />
                 </div>
               ) : sources && sources.length > 0 ? (
                 <div className="overflow-x-auto">
                   <table className="min-w-full divide-y divide-white/5">
                     <thead className="glass-void/50">
                       <tr>
                         <th className="px-6 py-4 text-left text-xs font-display font-bold text-text-ghost uppercase tracking-widest">Materialized Source</th>
                         <th className="px-6 py-4 text-left text-xs font-display font-bold text-text-ghost uppercase tracking-widest">Protocol</th>
                         <th className="px-6 py-4 text-left text-xs font-display font-bold text-text-ghost uppercase tracking-widest">Health State</th>
                         <th className="px-6 py-4 text-right text-xs font-display font-bold text-text-ghost uppercase tracking-widest">Inertia</th>
                       </tr>
                     </thead>
                     <tbody className="divide-y divide-white/5">
                       {sortedSources.map((source, idx) => (
                         <motion.tr 
                          key={source.id} 
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: idx * 0.05 }}
                          className="hover:bg-white/[0.02] transition-colors"
                         >
                           <td className="px-6 py-5 whitespace-nowrap">
                             {editingId === source.id ? (
                               <div className="flex flex-col gap-2 min-w-[280px]">
                                 <input
                                   type="text"
                                   value={editName}
                                   onChange={e => setEditName(e.target.value)}
                                   placeholder="Source name"
                                   className="glass-void border border-white/10 text-white rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:border-accent-primary transition-all font-bold placeholder:text-text-ghost"
                                 />
                                 <input
                                   type="url"
                                   value={editUrl}
                                   onChange={e => setEditUrl(e.target.value)}
                                   placeholder="https://..."
                                   className="glass-void border border-white/10 text-text-secondary rounded-lg px-3 py-1.5 text-[11px] font-mono focus:outline-none focus:border-accent-primary transition-all placeholder:text-text-ghost"
                                 />
                               </div>
                             ) : (
                               <div className="flex flex-col">
                                 <span className="text-[15px] font-bold text-white group-hover:text-accent-primary transition-colors">{source.name}</span>
                                 <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-[11px] font-mono text-text-ghost hover:text-accent-primary flex items-center gap-1.5 mt-1 transition-colors">
                                   {safeHostname(source.url)} <ExternalLink className="w-3 h-3" />
                                 </a>
                               </div>
                             )}
                           </td>
                           <td className="px-6 py-5 whitespace-nowrap">
                             <span className="text-[10px] font-mono font-bold text-text-muted bg-white/5 px-2 py-0.5 rounded border border-white/5 uppercase tracking-wider">{source.type}</span>
                           </td>
                           <td className="px-6 py-5 whitespace-nowrap">
                             {source.consecutive_failures > 0 ? (
                               <div className="flex items-center gap-2 text-xs text-[#E05A6B] font-bold font-display uppercase tracking-widest">
                                 <div className="w-1.5 h-1.5 rounded-full bg-[#E05A6B] shadow-[0_0_8px_#E05A6B]" />
                                 {source.consecutive_failures} DESYNC
                               </div>
                             ) : (
                               <div className="flex items-center gap-2 text-xs text-[#5AE07F] font-bold font-display uppercase tracking-widest">
                                 <div className="w-1.5 h-1.5 rounded-full bg-[#5AE07F] shadow-[0_0_8px_#5AE07F]" />
                                 RESONANT
                               </div>
                             )}
                           </td>
                           <td className="px-6 py-5 whitespace-nowrap text-right">
                             {editingId === source.id ? (
                               <div className="flex items-center justify-end gap-2">
                                 <button
                                   onClick={() => saveEdit(source.id)}
                                   disabled={updateSource.isPending || !editName.trim() || !editUrl.trim()}
                                   title="Save changes"
                                   className="p-2 rounded-lg text-[#5AE07F] hover:bg-[#5AE07F]/10 transition-colors disabled:opacity-40 disabled:hover:bg-transparent"
                                 >
                                   {updateSource.isPending ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                                 </button>
                                 <button
                                   onClick={cancelEdit}
                                   title="Cancel"
                                   className="p-2 rounded-lg text-text-ghost hover:text-white hover:bg-white/5 transition-colors"
                                 >
                                   <X className="w-4 h-4" />
                                 </button>
                               </div>
                             ) : (
                               <div className="flex items-center justify-end gap-4">
                                 <button
                                   onClick={() => startEdit(source)}
                                   title="Edit source"
                                   className="text-text-ghost hover:text-accent-primary transition-colors"
                                 >
                                   <Pencil className="w-4 h-4" />
                                 </button>
                                 <button
                                   onClick={() => toggleSource.mutate({ id: source.id, is_active: !source.is_active })}
                                   className={`relative inline-flex h-5 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full transition-all duration-500 focus:outline-none ${source.is_active ? 'bg-accent-primary' : 'bg-void border border-white/10'}`}
                                 >
                                   <span className="sr-only">Toggle Inertia</span>
                                   <span className={`pointer-events-none inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-lg transition-transform duration-500 ease-glass ${source.is_active ? 'translate-x-[10px]' : 'translate-x-[-10px]'}`} />
                                 </button>
                               </div>
                             )}
                           </td>
                         </motion.tr>
                       ))}
                     </tbody>
                   </table>
                 </div>
               ) : (
                 <div className="p-20 text-center flex flex-col items-center opacity-30">
                   <Cpu className="w-12 h-12 text-text-ghost mb-4 animate-pulse" />
                   <p className="text-sm font-display font-medium text-text-muted uppercase tracking-widest">Harvest Field Depleted</p>
                 </div>
               )}
             </div>
          </section>
          </>}
        </div>
      </div>
    </div>
  )
}

