import { lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { FeedPage } from './pages/FeedPage'
import { TrendingPage } from './pages/TrendingPage'
import { SavedPage } from './pages/SavedPage'
import { SettingsPage } from './pages/SettingsPage'
import { SearchResultsPage } from './pages/SearchResultsPage'
import { ClusterBrowserPage } from './pages/ClusterBrowserPage'
import { ClusterViewPage } from './pages/ClusterViewPage'
import { SearchPanel } from './features/search/SearchPanel'
import { Layout } from './components/Layout'
import { useTheme } from './hooks/useTheme'

// Lazy so the graph library (cytoscape) only loads on the Evolution page.
const EvolutionPage = lazy(() =>
  import('./features/evolution/EvolutionPage').then((m) => ({ default: m.EvolutionPage })),
)

function App() {
  useTheme()
  
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<FeedPage />} />
          <Route path="trending" element={<TrendingPage />} />
          <Route path="saved" element={<SavedPage />} />
          <Route path="sources/:sourceId" element={<FeedPage />} />
          <Route path="search" element={<SearchResultsPage />} />
          <Route path="research" element={<SearchPanel />} />
          <Route path="evolution" element={<Suspense fallback={null}><EvolutionPage /></Suspense>} />
          <Route path="evolution/:slug" element={<Suspense fallback={null}><EvolutionPage /></Suspense>} />
          <Route path="clusters" element={<ClusterBrowserPage />} />
          <Route path="clusters/:id" element={<ClusterViewPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="settings/:tab" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
