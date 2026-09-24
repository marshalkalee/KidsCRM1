import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Children from './pages/Children'
import ChildDetail from './pages/ChildDetail'
import Schedule from './pages/Schedule'
import Groups from './pages/Groups'
import GroupDetail from './pages/GroupDetail'
import Branches from './pages/Branches'
import BranchRooms from './pages/BranchRooms'
import Directions from './pages/Directions'
import OrganizationSettings from './pages/OrganizationSettings'

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
          <Route path="schedule" element={<Schedule />} />
          <Route path="groups" element={<Groups />} />
          <Route path="groups/:id" element={<GroupDetail />} />
          <Route path="branches" element={<Branches />} />
          <Route path="branches/:id/rooms" element={<BranchRooms />} />
          <Route path="directions" element={<Directions />} />
          <Route path="settings/organization" element={<OrganizationSettings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
