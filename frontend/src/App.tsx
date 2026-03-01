import { BrowserRouter, Routes, Route } from 'react-router-dom'
import CaseList from './pages/CaseList'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CaseList />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
