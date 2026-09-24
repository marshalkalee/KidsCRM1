import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Children from './pages/Children'
import ChildDetail from './pages/ChildDetail'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="children" element={<Children />} />
          <Route path="children/:id" element={<ChildDetail />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
