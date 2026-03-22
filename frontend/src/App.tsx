import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { FeedPage } from './pages/FeedPage'
import { TrendingPage } from './pages/TrendingPage'
import { SettingsPage } from './pages/SettingsPage'
import { SearchResultsPage } from './pages/SearchResultsPage'
import { ClusterBrowserPage } from './pages/ClusterBrowserPage'
import { ClusterViewPage } from './pages/ClusterViewPage'
import { Layout } from './components/Layout'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<FeedPage />} />
          <Route path="trending" element={<TrendingPage />} />
          <Route path="sources/:sourceId" element={<FeedPage />} />
          <Route path="search" element={<SearchResultsPage />} />
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
