import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/shell/Layout'
import { useLang } from './i18n'
import { RequireAuth, RequirePermission, SessionProvider } from './session/SessionContext'
import { ConfirmProvider, ToastProvider } from './ui'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Signup from './pages/Signup'
import NotFound from './pages/NotFound'
import ChildImport from './pages/ChildImport'
import Onboarding from './pages/Onboarding'
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
  // Смена языка перемонтирует экраны: подписи, колонки и форматы — на новом языке,
  // сессия и адрес страницы остаются.
  const lang = useLang()
  return (
    <BrowserRouter>
      <ToastProvider>
        <ConfirmProvider>
          <SessionProvider>
            <Routes key={lang}>
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Signup />} />
              <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
                <Route index element={<Navigate to="/dashboard" replace />} />
                <Route path="dashboard" element={<Dashboard />} />
                <Route path="onboarding" element={<RequirePermission permission="can_manage_org_settings"><Onboarding /></RequirePermission>} />
                <Route path="children" element={<Children />} />
                <Route path="children/import" element={<RequirePermission permission="can_manage_children"><ChildImport /></RequirePermission>} />
                <Route path="children/:id" element={<ChildDetail />} />
                <Route path="parents" element={<Parents />} />
                <Route path="parents/:id" element={<ParentDetail />} />
                <Route path="schedule" element={<div className="kc-schedule"><Schedule /></div>} />
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
