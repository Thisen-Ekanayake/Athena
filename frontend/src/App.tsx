import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { FeedPage } from './pages/FeedPage'
import { SettingsPage } from './pages/SettingsPage'
import { Layout } from './components/Layout'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<FeedPage />} />
          <Route path="settings/:tab?" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
