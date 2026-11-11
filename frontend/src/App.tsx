import { lazy, Suspense, type ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { FeedPage } from './pages/FeedPage'
import { HomePage } from './pages/HomePage'
import { PaperPage } from './pages/PaperPage'
import { ChangePasswordPage, LoginPage, RequireAuth, SetupPage } from './pages/AuthPages'
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

// Projects and chats load on first use.
const ChatPage = lazy(() => import('./pages/ChatPage').then((m) => ({ default: m.ChatPage })))
const ChatsPage = lazy(() => import('./pages/ChatsPage').then((m) => ({ default: m.ChatsPage })))
const ProjectPage = lazy(() => import('./pages/ProjectPage').then((m) => ({ default: m.ProjectPage })))
const ProjectsPage = lazy(() => import('./pages/ProjectsPage').then((m) => ({ default: m.ProjectsPage })))
const ConferencePage = lazy(() =>
  import('./features/conferences/ConferencePage').then((m) => ({ default: m.ConferencePage })))
// Home, the feed and a paper open with the app; every other page arrives when it is first visited, so signing in
// does not download the settings forms, the library or the review reader.
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const LibraryPage = lazy(() => import('./pages/LibraryPage').then((m) => ({ default: m.LibraryPage })))
const ReviewPage = lazy(() => import('./pages/ReviewPage').then((m) => ({ default: m.ReviewPage })))
const SearchPage = lazy(() => import('./pages/SearchPage').then((m) => ({ default: m.SearchPage })))
const InboxPage = lazy(() => import('./pages/InboxPage').then((m) => ({ default: m.InboxPage })))
const RisingPage = lazy(() => import('./pages/RisingPage').then((m) => ({ default: m.RisingPage })))
const ClustersPage = lazy(() => import('./pages/ClustersPage').then((m) => ({ default: m.ClustersPage })))
const ClusterPage = lazy(() => import('./pages/ClusterPage').then((m) => ({ default: m.ClusterPage })))

const loading = (page: ReactNode) => <Suspense fallback={<Spinner label="Loading…" />}>{page}</Suspense>

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
          <Route path="rising" element={loading(<RisingPage />)} />
          {/* Trending became Rising: citation momentum is the one "rising" measure. */}
          <Route path="trending" element={<Navigate to="/rising" replace />} />
          <Route path="clusters" element={loading(<ClustersPage />)} />
          <Route path="clusters/:id" element={loading(<ClusterPage />)} />
          <Route path="evolution" element={evolution} />
          <Route path="evolution/ideas" element={<Suspense fallback={<Spinner label="Loading…" />}><IdeaCheckPage /></Suspense>} />
          <Route path="evolution/:slug" element={evolution} />
          <Route path="library" element={loading(<LibraryPage />)} />
          <Route path="library/:tab" element={loading(<LibraryPage />)} />
          <Route path="library/conferences/:venue" element={loading(<ConferencePage />)} />
          {/* Saved lists became the Library's first tab. */}
          <Route path="saved" element={<Navigate to="/library" replace />} />
          <Route path="reviews/:id" element={loading(<ReviewPage />)} />
          <Route path="projects" element={loading(<ProjectsPage />)} />
          <Route path="projects/:id" element={loading(<ProjectPage />)} />
          <Route path="chats" element={loading(<ChatsPage />)} />
          <Route path="chats/new" element={loading(<ChatPage />)} />
          <Route path="chats/:id" element={loading(<ChatPage />)} />
          <Route path="inbox" element={loading(<InboxPage />)} />
          <Route path="search" element={loading(<SearchPage />)} />
          {/* Research search and the literature review now live on the search page. */}
          <Route path="research" element={<Navigate to="/search" replace />} />
          <Route path="items/:id" element={<PaperPage />} />
          <Route path="settings" element={loading(<SettingsPage />)} />
          <Route path="settings/:tab" element={loading(<SettingsPage />)} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
