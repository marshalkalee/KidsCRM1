import { Building2, CalendarDays, CheckSquare, Home, Megaphone, NotebookPen, UserRound, Wallet } from 'lucide-react'
import { t } from '../i18n'

/** Разделы кабинета. Главная открывается с логотипа на телефоне, чтобы нижнее меню не теснилось. */
export const PARENT_NAV = [
  { to: '/parent', end: true, mobile: false, icon: Home, get label() { return t('Главная') } },
  { to: '/parent/schedule', icon: CalendarDays, get label() { return t('Расписание') } },
  { to: '/parent/attendance', icon: CheckSquare, get label() { return t('Посещения') } },
  { to: '/parent/notes', icon: NotebookPen, get label() { return t('Заметки') } },
  { to: '/parent/subscription', icon: Wallet, get label() { return t('Абонемент') } },
  { to: '/parent/announcements', icon: Megaphone, get label() { return t('Объявления') } },
  // На телефоне в нижнем меню места нет — «О центре» открывается с главной.
  { to: '/parent/center', mobile: false, icon: Building2, get label() { return t('О центре') } },
  { to: '/parent/profile', icon: UserRound, get label() { return t('Профиль') } },
]
