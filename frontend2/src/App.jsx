import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/shell/Layout'
import { t, useLang } from './i18n'
import { RequireAuth, RequirePermission, SessionProvider, useSession } from './session/SessionContext'
import { ConfirmProvider, ToastProvider } from './ui'
import Dashboard from './pages/Dashboard'
import Assistant from './pages/Assistant'
import Digest from './pages/Digest'
import { MessagingJournal, MessagingSettings, MessagingTemplates } from './pages/Messaging'
import Login from './pages/Login'
import Signup from './pages/Signup'
import LegacyRedirect from './pages/LegacyRedirect'
import ParentApp from './parent/ParentApp'
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
import SubscriptionTypes from './pages/SubscriptionTypes'
import OrganizationSettings from './pages/OrganizationSettings'
import AccessSettings from './pages/AccessSettings'
import LeadDictionaries from './pages/LeadDictionaries'
import Leads from './pages/Leads'
import Notifications from './pages/Notifications'
import Profile from './pages/Profile'
import StaffDetail from './pages/StaffDetail'
import Staff from './pages/Staff'
import LeadDetail from './pages/LeadDetail'
import Debts from './pages/Debts'
import Renewals from './pages/Renewals'
import MyTasks from './pages/MyTasks'
import Analytics from './pages/Analytics'
import Announcements from './pages/Announcements'
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
import TaskEscalation from './pages/TaskEscalation'
import ParentRequests from './pages/ParentRequests'
import PageGroup, { TabRedirect } from './components/shell/PageGroup'

function RoleLandingRedirect() {
  const { user } = useSession()
  return <Navigate to={user?.role === 'admin' ? '/tasks' : '/dashboard'} replace />
}
function App() {
  // Кабинет родителя (/parent) — отдельное приложение со своим входом и
  // сессией, CRM сотрудников (SessionProvider) для него не поднимается.
  return (
    <BrowserRouter>
      <ToastProvider>
        <ConfirmProvider>
          <Routes>
            <Route path="/parent/*" element={<ParentApp />} />
            <Route path="*" element={<StaffApp />} />
          </Routes>
        </ConfirmProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}

function StaffApp() {
  // Смена языка перемонтирует экраны: подписи, колонки и форматы — на новом языке,
  // сессия и адрес страницы остаются.
  const lang = useLang()
  return (
          <SessionProvider>
            <Routes key={lang}>
              <Route path="/login" element={<Login />} />
              <Route path="/signup" element={<Signup />} />
              <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
                <Route index element={<RoleLandingRedirect />} />
                <Route path="dashboard" element={<Dashboard />} />
                <Route path="tasks" element={<PageGroup title={t('Задачи')} tabs={[
                  { key: 'mine', label: t('Мои'), element: <MyTasks /> },
                  { key: 'team', label: t('Просроченные у команды'), permission: 'can_manage_staff', element: <TaskEscalation /> },
                ]} />} />
                <Route path="tasks/escalation" element={<TabRedirect to="/tasks" tab="team" />} />
                <Route path="onboarding" element={<RequirePermission permission="can_manage_org_settings"><Onboarding /></RequirePermission>} />
                <Route path="leads" element={<RequirePermission permission="can_manage_leads"><Leads /></RequirePermission>} />
                <Route path="leads/:id" element={<RequirePermission permission="can_manage_leads"><LeadDetail /></RequirePermission>} />
                <Route path="assistant" element={<RequirePermission permission="can_use_ai_chat"><Assistant /></RequirePermission>} />
                <Route path="digest" element={<RequirePermission permission="can_view_ai_digest"><Digest /></RequirePermission>} />
                <Route path="messaging" element={<PageGroup title={t('Рассылки родителям')} tabs={[
                  { key: 'journal', label: t('Журнал'), permission: 'can_manage_children', element: <MessagingJournal /> },
                  { key: 'templates', label: t('Тексты писем'), permission: 'can_manage_org_settings', element: <MessagingTemplates /> },
                  { key: 'settings', label: t('Настройки'), permission: 'can_manage_org_settings', element: <MessagingSettings /> },
                ]} />} />
                <Route path="announcements" element={<RequirePermission permission="can_manage_announcements"><Announcements /></RequirePermission>} />
                <Route path="parent-requests" element={<RequirePermission permission="can_manage_parent_requests"><ParentRequests /></RequirePermission>} />
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
                <Route path="money" element={<RequirePermission permission="can_view_client_money"><PageGroup title={t('Деньги')} tabs={[
                  { key: 'debts', label: t('Долги'), element: <Debts /> },
                  { key: 'renewals', label: t('Продления'), element: <Renewals /> },
                ]} /></RequirePermission>} />
                <Route path="debts" element={<TabRedirect to="/money" tab="debts" />} />
                <Route path="renewals" element={<TabRedirect to="/money" tab="renewals" />} />
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
                <Route path="settings/structure" element={<PageGroup title={t('Структура центра')} tabs={[
                  { key: 'branches', label: t('Филиалы'), permission: 'can_manage_branches', element: <Branches /> },
                  { key: 'directions', label: t('Направления'), permission: 'can_manage_directions', element: <Directions /> },
                  { key: 'subscription-types', label: t('Типы абонементов'), permission: 'can_manage_subscription_types', element: <SubscriptionTypes /> },
                ]} />} />
                <Route path="branches" element={<TabRedirect to="/settings/structure" tab="branches" />} />
                <Route path="branches/:id/rooms" element={<BranchRooms />} />
                <Route path="directions" element={<TabRedirect to="/settings/structure" tab="directions" />} />
                <Route path="subscription-types" element={<TabRedirect to="/settings/structure" tab="subscription-types" />} />
                <Route path="settings/sales" element={<RequirePermission permission="can_manage_lead_dictionaries"><LeadDictionaries /></RequirePermission>} />
                <Route path="settings/staff" element={<RequirePermission permission="can_manage_staff"><Staff /></RequirePermission>} />
                <Route path="settings/organization" element={<RequirePermission permission="can_manage_org_settings"><OrganizationSettings /></RequirePermission>} />
                <Route path="settings/access" element={<RequirePermission permission="can_manage_org_settings"><AccessSettings /></RequirePermission>} />
                <Route path="*" element={<LegacyRedirect />} />
              </Route>
            </Routes>
          </SessionProvider>
  )
}

export default App
