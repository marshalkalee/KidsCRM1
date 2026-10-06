import {
  Building2,
  CalendarDays,
  ChartColumn,
  CheckSquare,
  Contact,
  Home,
  Inbox,
  ListChecks,
  ListTodo,
  Megaphone,
  MessageSquareText,
  Newspaper,
  Settings,
  Sparkles,
  UserRoundCog,
  Users,
  UsersRound,
  Wallet,
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
      { to: '/tasks', get label() { return t('Задачи') }, icon: ListTodo },
      { to: '/money', get label() { return t('Деньги') }, icon: Wallet, permission: 'can_view_client_money' },
      { to: '/announcements', get label() { return t('Объявления') }, icon: Megaphone, permission: 'can_manage_announcements' },
      { to: '/parent-requests', get label() { return t('Запросы родителей') }, icon: MessageSquareText, permission: 'can_manage_parent_requests' },
      { to: '/analytics', get label() { return t('Аналитика') }, icon: ChartColumn, permission: 'can_view_analytics' },
      // ai: true — пункт виден, только если ИИ подключён центру (TRU-160).
      { to: '/assistant', get label() { return t('ИИ-помощник') }, icon: Sparkles, permission: 'can_use_ai_chat', ai: true },
      { to: '/digest', get label() { return t('Дайджест недели') }, icon: Newspaper, permission: 'can_view_ai_digest', ai: true },
    ],
  },
  {
    get label() { return t('Настройки') },
    items: [
      { to: '/settings/structure', get label() { return t('Структура центра') }, icon: Building2, permission: 'can_manage_branches' },
      { to: '/settings/staff', get label() { return t('Сотрудники') }, icon: UserRoundCog, permission: 'can_manage_staff' },
      { to: '/settings/sales', get label() { return t('Справочники продаж') }, icon: ListChecks, permission: 'can_manage_lead_dictionaries' },
      { to: '/settings/organization', get label() { return t('Организация') }, icon: Settings, permission: 'can_manage_org_settings' },
    ],
  },
]

export function visibleSections(can, aiEnabled = false) {
  const visible = item => (!item.permission || can(item.permission)) && (!item.ai || aiEnabled)
  return NAV_SECTIONS
    .map(section => ({ ...section, items: section.items.filter(visible) }))
    .filter(section => section.items.length)
}
