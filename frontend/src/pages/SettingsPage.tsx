import { useState } from 'react'
import { useSources, useToggleSource, useAddSource } from '../api/queries/sources'
import { Alert } from '../components/shared/Alert'
import { Check, Orbit, ExternalLink, Shield, Cpu, Activity, Plus } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

export function SettingsPage() {
  const { data: sources, isLoading: sourcesLoading } = useSources()
  const toggleSource = useToggleSource()
  const addSource = useAddSource()

  const [urlInput, setUrlInput] = useState('')
  const [previewData, setPreviewData] = useState<any>(null)
  
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
            <button className="w-full text-left px-4 py-3 rounded-xl bg-accent-primary/10 text-accent-primary font-display font-bold text-[13px] border border-accent-primary/20 shadow-glow-primary transition-all">
              Content Harvest
            </button>
            <button className="w-full text-left px-4 py-3 rounded-xl text-text-muted hover:text-text-primary hover:bg-white/5 transition-all font-display font-bold text-[13px]">
              Logic Clusters
            </button>
            <button className="w-full text-left px-4 py-3 rounded-xl text-text-muted hover:text-text-primary hover:bg-white/5 transition-all font-display font-bold text-[13px]">
              System Core
            </button>
          </nav>
        </div>

        {/* Settings Content Pane */}
        <div className="col-span-1 md:col-span-3 space-y-12">
          
          {/* Add Custom Source */}
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
             <div className="flex items-center gap-3 px-1">
               <Shield className="w-5 h-5 text-accent-primary" />
               <h3 className="text-xl font-display font-bold text-white">Active Reservoirs</h3>
             </div>
             
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
                       {sources.map((source, idx) => (
                         <motion.tr 
                          key={source.id} 
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: idx * 0.05 }}
                          className="hover:bg-white/[0.02] transition-colors"
                         >
                           <td className="px-6 py-5 whitespace-nowrap">
                             <div className="flex flex-col">
                               <span className="text-[15px] font-bold text-white group-hover:text-accent-primary transition-colors">{source.name}</span>
                               <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-[11px] font-mono text-text-ghost hover:text-accent-primary flex items-center gap-1.5 mt-1 transition-colors">
                                 {new URL(source.url).hostname} <ExternalLink className="w-3 h-3" />
                               </a>
                             </div>
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
                             <button
                               onClick={() => toggleSource.mutate({ id: source.id, is_active: !source.is_active })}
                               className={`relative inline-flex h-5 w-10 shrink-0 cursor-pointer items-center justify-center rounded-full transition-all duration-500 focus:outline-none ${source.is_active ? 'bg-accent-primary' : 'bg-void border border-white/10'}`}
                             >
                               <span className="sr-only">Toggle Inertia</span>
                               <span className={`pointer-events-none inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-lg transition-transform duration-500 ease-glass ${source.is_active ? 'translate-x-[10px]' : 'translate-x-[-10px]'}`} />
                             </button>
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
        </div>
      </div>
    </div>
  )
}

