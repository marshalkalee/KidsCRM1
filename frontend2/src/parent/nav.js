import { Building2, CalendarDays, CheckSquare, Home, Megaphone, NotebookPen, UserRound, Wallet } from 'lucide-react'
import { t } from '../i18n'

/** Разделы кабинета — одно меню: слева на компьютере, выезжающее на телефоне. */
export const PARENT_NAV = [
  { to: '/parent', end: true, icon: Home, get label() { return t('Главная') } },
  { to: '/parent/schedule', icon: CalendarDays, get label() { return t('Расписание') } },
  { to: '/parent/attendance', icon: CheckSquare, get label() { return t('Посещения') } },
  { to: '/parent/notes', icon: NotebookPen, get label() { return t('Заметки') } },
  { to: '/parent/subscription', icon: Wallet, get label() { return t('Абонемент') } },
  { to: '/parent/announcements', icon: Megaphone, get label() { return t('Объявления') } },
  { to: '/parent/center', icon: Building2, get label() { return t('О центре') } },
  { to: '/parent/profile', icon: UserRound, get label() { return t('Профиль') } },
]
