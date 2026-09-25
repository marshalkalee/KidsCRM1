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
    label: t('Работа'),
    items: [
      { to: '/dashboard', label: t('Главная'), icon: Home },
      { to: '/children', label: t('Дети'), icon: Users },
      { to: '/parents', label: t('Родители'), icon: Contact },
      { to: '/groups', label: t('Группы'), icon: UsersRound },
      { to: '/schedule', label: t('Расписание'), icon: CalendarDays },
    ],
  },
  {
    label: t('Настройки'),
    items: [
      { to: '/branches', label: t('Филиалы'), icon: Building2, permission: 'can_manage_branches' },
      { to: '/directions', label: t('Направления'), icon: Tag, permission: 'can_manage_directions' },
      { to: '/settings/organization', label: t('Организация'), icon: Settings, permission: 'can_manage_org_settings' },
    ],
  },
]

export function visibleSections(can) {
  return NAV_SECTIONS
    .map(section => ({ ...section, items: section.items.filter(item => !item.permission || can(item.permission)) }))
    .filter(section => section.items.length)
}
