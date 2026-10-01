import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/shell/Layout'
import { useLang } from './i18n'
import { RequireAuth, RequirePermission, SessionProvider } from './session/SessionContext'
import { ConfirmProvider, ToastProvider } from './ui'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Signup from './pages/Signup'
import LegacyRedirect from './pages/LegacyRedirect'
import TestPay from './pages/TestPay'
import ChildImport from './pages/ChildImport'
import Onboarding from './pages/Onboarding'
import ParentDetail from './pages/ParentDetail'
import Parents from './pages/Parents'
import Children from './pages/Children'
import ChildDetail from './pages/ChildDetail'
import Schedule from './pages/Schedule'
import AttendanceScreen from './pages/AttendanceScreen'
import Groups from './pages/Groups'
import GroupDetail from './pages/GroupDetail'
import Branches from './pages/Branches'
import BranchRooms from './pages/BranchRooms'
import Directions from './pages/Directions'
import OrganizationSettings from './pages/OrganizationSettings'
import LeadDictionaries from './pages/LeadDictionaries'
import Leads from './pages/Leads'
import Notifications from './pages/Notifications'
import Profile from './pages/Profile'
import StaffDetail from './pages/StaffDetail'
import Staff from './pages/Staff'
import LeadDetail from './pages/LeadDetail'
import Debts from './pages/Debts'
import Renewals from './pages/Renewals'
import Analytics from './pages/Analytics'
import AnalyticsKit from './pages/AnalyticsKit'
import AnalyticsRevenue from './pages/AnalyticsRevenue'
import AnalyticsAttendance from './pages/AnalyticsAttendance'
import AnalyticsFunnel from './pages/AnalyticsFunnel'
import AnalyticsGroups from './pages/AnalyticsGroups'
import AnalyticsSources from './pages/AnalyticsSources'
import AnalyticsTeachers from './pages/AnalyticsTeachers'
import AnalyticsRejections from './pages/AnalyticsRejections'
import AnalyticsBranches from './pages/AnalyticsBranches'
import AnalyticsRisk from './pages/AnalyticsRisk'

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
              <Route path="/pay/test/:id" element={<TestPay />} />
              <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
                <Route index element={<Navigate to="/dashboard" replace />} />
                <Route path="dashboard" element={<Dashboard />} />
                <Route path="onboarding" element={<RequirePermission permission="can_manage_org_settings"><Onboarding /></RequirePermission>} />
                <Route path="leads" element={<RequirePermission permission="can_manage_leads"><Leads /></RequirePermission>} />
                <Route path="leads/:id" element={<RequirePermission permission="can_manage_leads"><LeadDetail /></RequirePermission>} />
                <Route path="notifications" element={<Notifications />} />
                <Route path="profile" element={<Profile />} />
                <Route path="staff" element={<Navigate to="/settings/staff" replace />} />
                <Route path="staff/:id" element={<StaffDetail />} />
                <Route path="children" element={<Children />} />
                <Route path="children/import" element={<RequirePermission permission="can_manage_children"><ChildImport /></RequirePermission>} />
                <Route path="children/:id" element={<ChildDetail />} />
                <Route path="parents" element={<Parents />} />
                <Route path="parents/:id" element={<ParentDetail />} />
                <Route path="schedule" element={<div className="kc-schedule"><Schedule /></div>} />
                <Route path="attendance" element={<AttendanceScreen />} />
                <Route path="debts" element={<RequirePermission permission="can_view_client_money"><Debts /></RequirePermission>} />
                <Route path="renewals" element={<RequirePermission permission="can_view_client_money"><Renewals /></RequirePermission>} />
                <Route path="analytics" element={<RequirePermission permission="can_view_analytics"><Analytics /></RequirePermission>} />
                <Route path="analytics/revenue" element={<RequirePermission permission="can_view_analytics"><AnalyticsRevenue /></RequirePermission>} />
                <Route path="analytics/attendance" element={<RequirePermission permission="can_view_analytics"><AnalyticsAttendance /></RequirePermission>} />
                <Route path="analytics/risk" element={<RequirePermission permission="can_view_analytics"><AnalyticsRisk /></RequirePermission>} />
                <Route path="analytics/funnel" element={<RequirePermission permission="can_view_analytics"><AnalyticsFunnel /></RequirePermission>} />
                <Route path="analytics/groups" element={<RequirePermission permission="can_view_analytics"><AnalyticsGroups /></RequirePermission>} />
                <Route path="analytics/branches" element={<RequirePermission permission="can_view_analytics"><AnalyticsBranches /></RequirePermission>} />
                <Route path="analytics/rejections" element={<RequirePermission permission="can_view_analytics"><AnalyticsRejections /></RequirePermission>} />
                <Route path="analytics/sources" element={<RequirePermission permission="can_view_analytics"><AnalyticsSources /></RequirePermission>} />
                <Route path="analytics/teachers" element={<RequirePermission permission="can_view_analytics"><AnalyticsTeachers /></RequirePermission>} />
                <Route path="analytics/kit" element={<RequirePermission permission="can_view_analytics"><AnalyticsKit /></RequirePermission>} />
                <Route path="groups" element={<Groups />} />
                <Route path="groups/:id" element={<GroupDetail />} />
                <Route path="branches" element={<RequirePermission permission="can_manage_branches"><Branches /></RequirePermission>} />
                <Route path="branches/:id/rooms" element={<BranchRooms />} />
                <Route path="directions" element={<RequirePermission permission="can_manage_directions"><Directions /></RequirePermission>} />
                <Route path="settings/sales" element={<RequirePermission permission="can_manage_lead_dictionaries"><LeadDictionaries /></RequirePermission>} />
                <Route path="settings/staff" element={<RequirePermission permission="can_manage_staff"><Staff /></RequirePermission>} />
                <Route path="settings/organization" element={<RequirePermission permission="can_manage_org_settings"><OrganizationSettings /></RequirePermission>} />
                <Route path="*" element={<LegacyRedirect />} />
              </Route>
            </Routes>
          </SessionProvider>
        </ConfirmProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}

export default App
