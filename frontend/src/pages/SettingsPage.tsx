import { useState } from 'react'
import { useSources, useToggleSource, useAddSource } from '../api/queries/sources'
import { Alert } from '../components/shared/Alert'
import { Check, Orbit, ExternalLink } from 'lucide-react'

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
    <div className="p-6 md:p-12 max-w-5xl mx-auto w-full fade-in flex-1 overflow-y-auto">
      <div className="mb-8 border-b border-border pb-6">
        <h1 className="text-3xl font-bold text-white tracking-tight">Settings Workspace</h1>
        <p className="text-textSecondary mt-2">Manage sources, AI models, and clustering behaviors.</p>
      </div>

      <div className="grid md:grid-cols-4 gap-8">
        {/* Settings Navigation Sidebar */}
        <div className="col-span-1 space-y-1">
          <div className="text-sm font-semibold text-zinc-500 uppercase tracking-wider mb-4 px-3">Configuration</div>
          <button className="w-full text-left px-4 py-2.5 rounded-md bg-zinc-800/80 text-white font-medium shadow-sm border border-zinc-700">
            Content Sources
          </button>
          <button className="w-full text-left px-4 py-2.5 rounded-md text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200 transition-colors">
            Trending Clusters
          </button>
          <button className="w-full text-left px-4 py-2.5 rounded-md text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200 transition-colors">
            Intelligence
          </button>
        </div>

        {/* Settings Content Pane */}
        <div className="col-span-1 md:col-span-3 space-y-8">
          
          {/* Add Custom Source */}
          <section className="card p-6 border-zinc-700 bg-zinc-900/40 shadow-lg">
             <h3 className="text-lg font-medium text-white mb-1 flex items-center gap-2">
               <Orbit className="w-5 h-5 text-accentPrimary" />
               Add Custom Source
             </h3>
             <p className="text-sm text-zinc-400 mb-5">Automatically detect RSS feeds or scrape content.</p>
             
             {!previewData ? (
               <form className="space-y-4" onSubmit={handleDetect}>
                 <div>
                   <label className="block text-sm font-medium text-zinc-300 mb-1.5">Source URL</label>
                   <div className="flex gap-3">
                     <input 
                       type="url" 
                       value={urlInput}
                       onChange={e => setUrlInput(e.target.value)}
                       placeholder="https://news.ycombinator.com"
                       className="flex-1 bg-zinc-900 border border-zinc-700 text-white rounded-md px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-accentPrimary transition-shadow"
                     />
                     <button 
                       type="submit" 
                       disabled={addSource.isPending || !urlInput}
                       className="btn btn-primary px-6 whitespace-nowrap"
                     >
                       {addSource.isPending ? 'Detecting...' : 'Detect'}
                     </button>
                   </div>
                 </div>
                 {addSource.isError && (
                   <Alert type="error">{addSource.error?.message || 'Failed to detect source format.'}</Alert>
                 )}
               </form>
             ) : (
               <div className="space-y-4 animate-in fade-in slide-in-from-top-2">
                 <div className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-5">
                   <div className="flex items-start justify-between">
                     <div>
                       <h4 className="text-base font-bold text-white mb-1 flex items-center gap-2">
                         <Check className="w-4 h-4 text-green-400" />
                         Found: {previewData.source_name}
                       </h4>
                       <span className="text-xs font-semibold px-2 py-1 rounded bg-zinc-700 text-zinc-300 uppercase tracking-wide">
                         Type: {previewData.source_type}
                       </span>
                     </div>
                   </div>
                   
                   <div className="mt-4 pt-4 border-t border-zinc-700/50 space-y-3">
                     <h5 className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">Preview Items</h5>
                     {previewData.sample_items?.slice(0, 2).map((item: any, idx: number) => (
                       <article key={idx} className="bg-zinc-900 p-3 rounded border border-zinc-800">
                         <h6 className="text-sm font-semibold text-zinc-200 truncate">{item.title}</h6>
                         {item.summary && <p className="text-xs text-zinc-500 line-clamp-2 mt-1">{item.summary}</p>}
                       </article>
                     ))}
                   </div>
                   
                   <div className="mt-5 flex gap-3">
                      <button 
                        onClick={handleConfirmAdd}
                        disabled={addSource.isPending}
                        className="btn btn-primary px-5 py-2 flex-1"
                      >
                       {addSource.isPending ? 'Adding...' : 'Confirm & Add Source'}
                      </button>
                      <button 
                        onClick={() => { setPreviewData(null); addSource.reset() }}
                        className="btn btn-outline px-5 py-2 flex-1"
                      >
                        Cancel
                      </button>
                   </div>
                 </div>
               </div>
             )}
          </section>

          {/* Active Sources Table */}
          <section className="space-y-4">
             <div className="flex justify-between items-end mb-2">
               <h3 className="text-lg font-medium text-white">Active Sources</h3>
             </div>
             
             <div className="border border-zinc-800 rounded-lg overflow-hidden bg-card">
               {sourcesLoading ? (
                 <div className="p-12 flex justify-center"><div className="w-6 h-6 border-2 border-accentPrimary border-t-transparent rounded-full animate-spin" /></div>
               ) : sources && sources.length > 0 ? (
                 <table className="min-w-full divide-y divide-zinc-800">
                   <thead className="bg-zinc-900/50">
                     <tr>
                       <th className="px-5 py-3.5 text-left text-xs font-semibold text-zinc-400 uppercase tracking-wider">Source</th>
                       <th className="px-5 py-3.5 text-left text-xs font-semibold text-zinc-400 uppercase tracking-wider">Type</th>
                       <th className="px-5 py-3.5 text-left text-xs font-semibold text-zinc-400 uppercase tracking-wider">Health</th>
                       <th className="px-5 py-3.5 text-right text-xs font-semibold text-zinc-400 uppercase tracking-wider">Status</th>
                     </tr>
                   </thead>
                   <tbody className="divide-y divide-zinc-800/50 bg-card">
                     {sources.map(source => (
                       <tr key={source.id} className="hover:bg-zinc-900/50 transition-colors">
                         <td className="px-5 py-4 whitespace-nowrap">
                           <div className="flex flex-col">
                             <span className="text-sm font-medium text-white">{source.name}</span>
                             <a href={source.url} target="_blank" rel="noopener noreferrer" className="text-xs text-zinc-500 hover:text-accentPrimary flex items-center gap-1 mt-0.5">
                               {new URL(source.url).hostname} <ExternalLink className="w-3 h-3" />
                             </a>
                           </div>
                         </td>
                         <td className="px-5 py-4 whitespace-nowrap">
                           <span className="badge badge-neutral tracking-wide uppercase text-[10px]">{source.type}</span>
                         </td>
                         <td className="px-5 py-4 whitespace-nowrap">
                           {source.consecutive_failures > 0 ? (
                              <span className="flex items-center gap-1.5 text-xs text-red-400 font-medium">
                                <div className="w-2 h-2 rounded-full bg-red-500" />
                                {source.consecutive_failures} failures
                              </span>
                           ) : (
                              <span className="flex items-center gap-1.5 text-xs text-green-400 font-medium">
                                <div className="w-2 h-2 rounded-full bg-green-500" />
                                Healthy
                              </span>
                           )}
                         </td>
                         <td className="px-5 py-4 whitespace-nowrap text-right">
                           <button
                             onClick={() => toggleSource.mutate({ id: source.id, is_active: !source.is_active })}
                             className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full focus:outline-none focus:ring-2 focus:ring-accentPrimary focus:ring-offset-2 focus:ring-offset-zinc-900 transition-colors ${source.is_active ? 'bg-accentPrimary' : 'bg-zinc-700'}`}
                           >
                             <span className="sr-only">Toggle source</span>
                             <span className={`pointer-events-none absolute left-0 inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform duration-200 ease-in-out ${source.is_active ? 'translate-x-4' : 'translate-x-0'}`} />
                           </button>
                         </td>
                       </tr>
                     ))}
                   </tbody>
                 </table>
               ) : (
                 <div className="p-8 text-center text-zinc-500 text-sm">No sources added yet.</div>
               )}
             </div>
          </section>
        </div>
      </div>
    </div>
  )
}
