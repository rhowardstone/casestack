import { BrowserRouter, Routes, Route } from 'react-router-dom'
import CaseList from './pages/CaseList'
import NewCaseWizard from './pages/NewCaseWizard'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Search from './pages/Search'
import ImageGallery from './pages/ImageGallery'
import Heatmap from './pages/Heatmap'
import EntityViewer from './pages/EntityViewer'
import TranscriptBrowser from './pages/TranscriptBrowser'
import AskAssistant from './pages/AskAssistant'
import CaseSettings from './pages/CaseSettings'
import ProjectDashboard from './pages/ProjectDashboard'
import DocumentBrowser from './pages/DocumentBrowser'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CaseList />} />
        <Route path="/new" element={<NewCaseWizard />} />
        <Route path="/project/:slug" element={<ProjectDashboard />} />
        <Route path="/case/:slug" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="documents" element={<DocumentBrowser />} />
          <Route path="search" element={<Search />} />
          <Route path="images" element={<ImageGallery />} />
          <Route path="entities" element={<EntityViewer />} />
          <Route path="map" element={<Heatmap />} />
          <Route path="transcripts" element={<TranscriptBrowser />} />
          <Route path="ask" element={<AskAssistant />} />
          <Route path="settings" element={<CaseSettings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
