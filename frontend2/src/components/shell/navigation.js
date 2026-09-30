import {
  Building2, CalendarClock, ChartColumn, CalendarDays, CheckSquare, Contact, Home, Inbox, ListChecks, Settings, Tag, Users, UsersRound, Wallet,
} from 'lucide-react'
import { t } from '../../i18n'

/**
 * Пункты бокового меню. permission — флаг из /users/auth/me/ (те же, что
 * скрывают пункты в старом includes/sidebar.html); без него пункт виден
 * всем. Пункт добавляется сюда, только когда экран реально есть во
 * frontend2 — никаких ссылок в никуда.

 */
export const NAV_SECTIONS = [
  {
    get label() { return t('Работа') },
    items: [
      { to: '/dashboard', get label() { return t('Главная') }, icon: Home },
      { to: '/leads', get label() { return t('Заявки') }, icon: Inbox, permission: 'can_manage_leads' },
      { to: '/children', get label() { return t('Дети') }, icon: Users },
      { to: '/parents', get label() { return t('Родители') }, icon: Contact },
      { to: '/groups', get label() { return t('Группы') }, icon: UsersRound },
      { to: '/schedule', get label() { return t('Расписание') }, icon: CalendarDays },
      { to: '/attendance', get label() { return t('Посещаемость') }, icon: CheckSquare },
      { to: '/renewals', get label() { return t('Продления') }, icon: CalendarClock, permission: 'can_view_client_money' },
      { to: '/debts', get label() { return t('Задолженности') }, icon: Wallet, permission: 'can_view_client_money' },
      { to: '/analytics', get label() { return t('Аналитика') }, icon: ChartColumn, permission: 'can_view_analytics' },
    ],
  },
  {
    get label() { return t('Настройки') },
    items: [
      { to: '/branches', get label() { return t('Филиалы') }, icon: Building2, permission: 'can_manage_branches' },
      { to: '/directions', get label() { return t('Направления') }, icon: Tag, permission: 'can_manage_directions' },
      { to: '/settings/sales', get label() { return t('Справочники продаж') }, icon: ListChecks, permission: 'can_manage_lead_dictionaries' },
      { to: '/settings/organization', get label() { return t('Организация') }, icon: Settings, permission: 'can_manage_org_settings' },
    ],
  },
]

export function visibleSections(can) {
  return NAV_SECTIONS
    .map(section => ({ ...section, items: section.items.filter(item => !item.permission || can(item.permission)) }))
    .filter(section => section.items.length)
}
