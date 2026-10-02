import { CalendarDays, CheckSquare, Home, UserRound, Wallet } from 'lucide-react'
import { t } from '../i18n'

/** Вкладки кабинета родителя (нижняя навигация на телефоне, вкладки на широком экране). */
export const PARENT_NAV = [
  { to: '/parent', end: true, icon: Home, get label() { return t('Главная') } },
  { to: '/parent/schedule', icon: CalendarDays, get label() { return t('Расписание') } },
  { to: '/parent/attendance', icon: CheckSquare, get label() { return t('Посещения') } },
  { to: '/parent/subscription', icon: Wallet, get label() { return t('Абонемент') } },
  { to: '/parent/profile', icon: UserRound, get label() { return t('Профиль') } },
]
