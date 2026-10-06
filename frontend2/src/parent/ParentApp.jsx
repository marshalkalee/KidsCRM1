import { Navigate, Route, Routes } from 'react-router-dom'
import { useLang } from '../i18n'
import ParentLayout from './ParentLayout'
import ParentLogin from './ParentLogin'
import { ParentSessionProvider, RequireParent } from './ParentSession'
import ParentAttendance from './pages/ParentAttendance'
import ParentHome from './pages/ParentHome'
import ParentNews from './pages/ParentNews'
import ParentNotes from './pages/ParentNotes'
import ParentProfile from './pages/ParentProfile'
import ParentSchedule from './pages/ParentSchedule'
import ParentSubscription from './pages/ParentSubscription'

/*
 * Кабинет родителя — отдельное приложение внутри frontend2 по адресу
 * /parent (TRU-137). Своя сессия и свой вход, CRM сотрудников не
 * подключается. Новый экран: файл в parent/pages и строка здесь
 * (и в PARENT_NAV, если нужна вкладка) — docs/parent-portal.md.
 */
export default function ParentApp() {
  const language = useLang()
  return (
    <ParentSessionProvider>
      <Routes key={language}>
        <Route path="login" element={<ParentLogin />} />
        <Route element={<RequireParent><ParentLayout /></RequireParent>}>
          <Route index element={<ParentHome />} />
          <Route path="schedule" element={<ParentSchedule />} />
          <Route path="attendance" element={<ParentAttendance />} />
          <Route path="notes" element={<ParentNotes />} />
          <Route path="subscription" element={<ParentSubscription />} />
          <Route path="announcements" element={<ParentNews />} />
          <Route path="news" element={<Navigate to="/parent/announcements" replace />} />
          <Route path="profile" element={<ParentProfile />} />
          <Route path="*" element={<Navigate to="/parent" replace />} />
        </Route>
      </Routes>
    </ParentSessionProvider>
  )
}
