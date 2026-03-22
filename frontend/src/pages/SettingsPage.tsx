export function SettingsPage() {
  return (
    <div className="p-6 md:p-12 max-w-4xl mx-auto w-full fade-in">
      <div className="mb-8 border-b border-border pb-6">
        <h1 className="text-3xl font-bold text-white tracking-tight">Settings Workspace</h1>
        <p className="text-textSecondary mt-2">Manage sources, AI models, and clustering behaviors.</p>
      </div>

      <div className="grid md:grid-cols-3 gap-8">
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
        <div className="col-span-1 md:col-span-2 space-y-6">
          <div className="card p-6">
            <h3 className="text-lg font-medium text-white mb-1">Add Custom Source</h3>
            <p className="text-sm text-textSecondary mb-5">Automatically detect RSS feeds or scrape content.</p>
            
            <form className="space-y-4" onSubmit={e => e.preventDefault()}>
              <div>
                <label className="block text-sm font-medium text-zinc-300 mb-1.5">Source URL</label>
                <div className="flex gap-3">
                  <input 
                    type="url" 
                    placeholder="https://news.ycombinator.com"
                    className="flex-1 bg-zinc-900 border border-zinc-700 text-white rounded-md px-4 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-accentPrimary focus:border-transparent transition-shadow"
                  />
                  <button className="btn btn-primary px-6">
                    Detect
                  </button>
                </div>
              </div>
            </form>
          </div>
          
          <div className="card p-6 border-dashed border-zinc-700 bg-zinc-900/30 flex items-center justify-center min-h-[200px]">
            <span className="text-zinc-500 text-sm">Source management UI goes here</span>
          </div>
        </div>
      </div>
    </div>
  )
}
