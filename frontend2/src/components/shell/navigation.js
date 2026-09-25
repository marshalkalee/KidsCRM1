import {
  Building2, CalendarDays, Contact, Home, Settings, Tag, Users, UsersRound,
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
      { to: '/children', get label() { return t('Дети') }, icon: Users },
      { to: '/parents', get label() { return t('Родители') }, icon: Contact },
      { to: '/groups', get label() { return t('Группы') }, icon: UsersRound },
      { to: '/schedule', get label() { return t('Расписание') }, icon: CalendarDays },
    ],
  },
  {
    get label() { return t('Настройки') },
    items: [
      { to: '/branches', get label() { return t('Филиалы') }, icon: Building2, permission: 'can_manage_branches' },
      { to: '/directions', get label() { return t('Направления') }, icon: Tag, permission: 'can_manage_directions' },
      { to: '/settings/organization', get label() { return t('Организация') }, icon: Settings, permission: 'can_manage_org_settings' },
    ],
  },
]

export function visibleSections(can) {
  return NAV_SECTIONS
    .map(section => ({ ...section, items: section.items.filter(item => !item.permission || can(item.permission)) }))
    .filter(section => section.items.length)
}
