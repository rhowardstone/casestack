import { BrowserRouter, Routes, Route } from 'react-router-dom'
import CaseList from './pages/CaseList'
import NewCaseWizard from './pages/NewCaseWizard'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Search from './pages/Search'
import Heatmap from './pages/Heatmap'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CaseList />} />
        <Route path="/new" element={<NewCaseWizard />} />
        <Route path="/case/:slug" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="search" element={<Search />} />
          <Route path="map" element={<Heatmap />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
