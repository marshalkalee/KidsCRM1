import AttendanceTab from './AttendanceTab'
import CommunicationsTab from './CommunicationsTab'
import ContactsTab from './ContactsTab'
import { t } from '../../i18n'

/**
 * Контракт вкладок карточки ребёнка (TRU-82) — замена child_card_tabs.py
 * старого веба. Другие домены подключают вкладку здесь одной строкой, не
 * трогая саму карточку (pages/ChildDetail.jsx):
 *
 *   { key, label, order, component, permission? }
 *
 * - key — в адресе (?tab=key), латиницей, не меняется после выпуска.
 * - component — React-компонент вкладки. Получает props:
 *     child        — ребёнок (ответ ChildSerializer из GET children/<id>/card/),
 *     card         — весь ответ card/ (branches, groups, money, permissions),
 *     permissions  — card.permissions (can_edit, can_manage_contacts, …),
 *     onCountChange(n) — необязательно: число в ярлыке вкладки.
 *   Данные вкладка грузит сама из своего API (своего домена); права на
 *   действия внутри — тоже её забота, API проверяет их повторно.
 *   null — вкладка-заглушка «скоро появится».
 * - permission — флаг из /users/auth/me/ permissions; без него вкладку не
 *   видно (например, деньги — can_view_client_money).
 *
 * Подробнее — docs/contracts.md, раздел «Вкладки карточки ребёнка».
 */
export const CHILD_CARD_TABS = [
  { key: 'contacts', get label() { return t('Контакты') }, order: 10, component: ContactsTab },
  { key: 'communications', get label() { return t('Коммуникации') }, order: 20, component: CommunicationsTab },
  // Деньги (Bekzat, TRU-70) — заглушки до подключения.
  { key: 'subscriptions', label: 'Абонементы', order: 30, component: null, permission: 'can_view_client_money' },
  { key: 'payments', label: 'Оплаты', order: 40, component: null, permission: 'can_view_client_money' },
  // TRU-54: пока только доступные отработки. Полная история посещений —
  // TRU-55, расширит этот же компонент (AttendanceTab), не новую вкладку.
  { key: 'attendance', label: 'Посещения', order: 50, component: AttendanceTab },
]

export function visibleChildCardTabs(can) {
  return CHILD_CARD_TABS
    .filter(tab => !tab.permission || can(tab.permission))
    .sort((a, b) => a.order - b.order)
}
