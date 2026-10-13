import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { ClusterPage } from './pages/ClusterPage'
import { ClustersPage } from './pages/ClustersPage'
import { FeedPage } from './pages/FeedPage'
import { HomePage } from './pages/HomePage'
import { PaperPage } from './pages/PaperPage'
import { ChangePasswordPage, LoginPage, RequireAuth, SetupPage } from './pages/AuthPages'
import { InboxPage } from './pages/InboxPage'
import { SavedPage } from './pages/SavedPage'
import { SearchPage } from './pages/SearchPage'
import { SettingsPage } from './pages/SettingsPage'
import { TrendingPage } from './pages/TrendingPage'
import { Spinner } from './ui/Spinner'

// Lazy so the graph library (cytoscape) only loads on the Evolution page.
const EvolutionPage = lazy(() =>
  import('./features/evolution/EvolutionPage').then((m) => ({ default: m.EvolutionPage })),
)

const SharedMapPage = lazy(() =>
  import('./features/evolution/SharedMapPage').then((m) => ({ default: m.SharedMapPage })),
)

const WelcomePage = lazy(() =>
  import('./features/onboarding/WelcomePage').then((m) => ({ default: m.WelcomePage })),
)

const IdeaCheckPage = lazy(() =>
  import('./features/evolution/IdeaCheckPage').then((m) => ({ default: m.IdeaCheckPage })),
)

const evolution = (
  <Suspense fallback={<Spinner label="Loading…" />}>
    <EvolutionPage />
  </Suspense>
)

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/change-password" element={<ChangePasswordPage />} />
        {/* The setup guide, outside the app shell; new accounts are sent here first */}
        <Route path="/welcome" element={<RequireAuth guide><Suspense fallback={<Spinner label="Loading…" />}><WelcomePage /></Suspense></RequireAuth>} />
        {/* A map behind a share link: no account needed */}
        <Route path="/share/:token" element={<Suspense fallback={<Spinner label="Loading…" />}><SharedMapPage /></Suspense>} />
        <Route path="/" element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<HomePage />} />
          <Route path="feed" element={<FeedPage />} />
          <Route path="sources/:sourceId" element={<FeedPage />} />
          <Route path="trending" element={<TrendingPage />} />
          <Route path="clusters" element={<ClustersPage />} />
          <Route path="clusters/:id" element={<ClusterPage />} />
          <Route path="evolution" element={evolution} />
          <Route path="evolution/ideas" element={<Suspense fallback={<Spinner label="Loading…" />}><IdeaCheckPage /></Suspense>} />
          <Route path="evolution/:slug" element={evolution} />
          <Route path="saved" element={<SavedPage />} />
          <Route path="inbox" element={<InboxPage />} />
          <Route path="search" element={<SearchPage />} />
          {/* Research search and the literature review now live on the search page. */}
          <Route path="research" element={<Navigate to="/search" replace />} />
          <Route path="items/:id" element={<PaperPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="settings/:tab" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
