import { Route, Routes } from 'react-router-dom'
import { CalendarDays, CheckSquare, Home, Wallet } from 'lucide-react'
import { t, useLang } from '../i18n'
import ParentLayout from './ParentLayout'
import ParentLogin from './ParentLogin'
import { ParentSessionProvider, RequireParent } from './ParentSession'
import ParentProfile from './pages/ParentProfile'
import ParentSoon from './pages/ParentSoon'

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
          <Route index element={<ParentSoon icon={Home} title={t('Главная')} />} />
          <Route path="schedule" element={<ParentSoon icon={CalendarDays} title={t('Расписание')} />} />
          <Route path="attendance" element={<ParentSoon icon={CheckSquare} title={t('Посещения')} />} />
          <Route path="subscription" element={<ParentSoon icon={Wallet} title={t('Абонемент')} />} />
          <Route path="profile" element={<ParentProfile />} />
          <Route path="*" element={<ParentSoon icon={Home} title={t('Страница не найдена')} />} />
        </Route>
      </Routes>
    </ParentSessionProvider>
  )
}
