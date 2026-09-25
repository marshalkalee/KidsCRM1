import {
  Building2, CalendarDays, Contact, Home, Settings, Tag, Users, UsersRound,
} from 'lucide-react'

/**
 * Пункты бокового меню. permission — флаг из /users/auth/me/ (те же, что
 * скрывают пункты в старом includes/sidebar.html); без него пункт виден
 * всем. Пункт добавляется сюда, только когда экран реально есть во
 * frontend2 — никаких ссылок в никуда.
 *
 * title — заголовок в шапке для страниц раздела (включая вложенные: /children/:id).
 */
export const NAV_SECTIONS = [
  {
    label: 'Работа',
    items: [
      { to: '/dashboard', label: 'Главная', icon: Home },
      { to: '/children', label: 'Дети', icon: Users },
      { to: '/parents', label: 'Родители', icon: Contact },
      { to: '/groups', label: 'Группы', icon: UsersRound },
      { to: '/schedule', label: 'Расписание', icon: CalendarDays },
    ],
  },
  {
    label: 'Настройки',
    items: [
      { to: '/branches', label: 'Филиалы', icon: Building2, permission: 'can_manage_branches' },
      { to: '/directions', label: 'Направления', icon: Tag, permission: 'can_manage_directions' },
      { to: '/settings/organization', label: 'Организация', icon: Settings, permission: 'can_manage_org_settings' },
    ],
  },
]

export function visibleSections(can) {
  return NAV_SECTIONS
    .map(section => ({ ...section, items: section.items.filter(item => !item.permission || can(item.permission)) }))
    .filter(section => section.items.length)
}

export function sectionTitle(pathname) {
  for (const section of NAV_SECTIONS) {
    for (const item of section.items) {
      if (pathname === item.to || pathname.startsWith(item.to + '/')) return item.label
    }
  }
  return ''
}
