import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/shell/Layout'
import { RequireAuth, RequirePermission, SessionProvider } from './session/SessionContext'
import { ConfirmProvider, ToastProvider } from './ui'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import NotFound from './pages/NotFound'
import ParentDetail from './pages/ParentDetail'
import Parents from './pages/Parents'
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
      <ToastProvider>
        <ConfirmProvider>
          <SessionProvider>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
                <Route index element={<Navigate to="/dashboard" replace />} />
                <Route path="dashboard" element={<Dashboard />} />
                <Route path="children" element={<Children />} />
                <Route path="children/:id" element={<ChildDetail />} />
                <Route path="parents" element={<Parents />} />
                <Route path="parents/:id" element={<ParentDetail />} />
                <Route path="schedule" element={<Schedule />} />
                <Route path="groups" element={<Groups />} />
                <Route path="groups/:id" element={<GroupDetail />} />
                <Route path="branches" element={<RequirePermission permission="can_manage_branches"><Branches /></RequirePermission>} />
                <Route path="branches/:id/rooms" element={<BranchRooms />} />
                <Route path="directions" element={<RequirePermission permission="can_manage_directions"><Directions /></RequirePermission>} />
                <Route path="settings/organization" element={<RequirePermission permission="can_manage_org_settings"><OrganizationSettings /></RequirePermission>} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </SessionProvider>
        </ConfirmProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}

export default App
