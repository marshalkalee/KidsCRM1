import { Banknote, BadgePercent, CalendarCheck, CalendarX, CircleCheck, Hourglass, Inbox, Percent, Receipt, Scale, ShoppingBag, UsersRound, Wallet, Baby } from 'lucide-react'
import { t } from '../../i18n'

/**
 * Как показывать метрику на фронте: подпись (переводится здесь, а не
 * берётся русской с бэка), иконка и какое направление — хорошее. Долг
 * вырос — плохо, выручка выросла — хорошо. Новую метрику отчёт добавляет
 * сюда же; без записи плитка покажет подпись с бэка.
 */
export const METRIC_META = {
  revenue: { get label() { return t('Выручка') }, icon: Banknote },
  payments_count: { get label() { return t('Оплат') }, icon: Receipt },
  average_check: { get label() { return t('Средний чек') }, icon: Receipt },
  // Чек и долги (TRU-124): медиана и долг на конец периода — цифры отчёта, не метрики реестра.
  median_check: { get label() { return t('Медиана чека') }, icon: Scale },
  sales_count: { get label() { return t('Продано абонементов') }, icon: ShoppingBag },
  sales_amount: { get label() { return t('Продано на сумму') }, icon: ShoppingBag },
  discount_total: { get label() { return t('Скидки') }, icon: BadgePercent },
  debt_end: { get label() { return t('Долг на конец периода') }, icon: Wallet, goodWhenDown: true },
  debt_age_0_30: { get label() { return t('Долг до 30 дней') }, icon: Hourglass, goodWhenDown: true },
  debt_age_31_60: { get label() { return t('Долг 31–60 дней') }, icon: Hourglass, goodWhenDown: true },
  debt_age_over_60: { get label() { return t('Долг больше 60 дней') }, icon: Hourglass, goodWhenDown: true },
  debtors_share: { get label() { return t('Доля должников') }, icon: Percent, goodWhenDown: true },
  debt_repaid: { get label() { return t('Погашено старых долгов') }, icon: CircleCheck },
  debt_total: { get label() { return t('Задолженность') }, icon: Wallet, goodWhenDown: true },
  visits: { get label() { return t('Посещений') }, icon: CalendarCheck },
  attendance_marks: { get label() { return t('Отметок посещаемости') }, icon: CalendarCheck },
  attendance_rate: { get label() { return t('Доля посещений') }, icon: Percent },
  active_children: { get label() { return t('Ходили на занятия') }, icon: Baby },
  new_leads: { get label() { return t('Новых заявок') }, icon: Inbox },
  absences: { get label() { return t('Пропусков') }, icon: CalendarX, goodWhenDown: true },
  group_fill: { get label() { return t('Заполняемость групп') }, icon: UsersRound },
}

export function metricLabel(name, metric) {
  return METRIC_META[name]?.label || metric?.label || name
}

/**
 * Цвета графиков — из токенов темы (index.css), одна палитра на все
 * отчёты: первая серия — фирменный, дальше — различимые на белом.
 */
export const PALETTE = [
  'var(--color-brand-600)',
  'var(--color-info-600)',
  'var(--color-success-600)',
  'var(--color-warning-600)',
  'var(--color-brand-300)',
  'var(--color-ink-subtle)',
]

// Подписи ключей разбивок, которые приходят кодом: способ оплаты, статус
// посещения. Филиалы, направления и источники приходят именем из базы.
const KEY_LABELS = {
  kaspi_transfer: () => t('Kaspi'),
  cash: () => t('Наличные'),
  card: () => t('Карта'),
  other: () => t('Другое'),
  present: () => t('Был'),
  absent: () => t('Не был'),
  makeup: () => t('Отработка'),
  illness: () => t('Болезнь'),
  family: () => t('Семейные обстоятельства'),
  no_reason: () => t('Без причины'),
  new: () => t('Новые клиенты'),
  renewal: () => t('Продления'),
  large_family: () => t('Многодетная семья'),
  second_child: () => t('Второй ребёнок'),
  promotion: () => t('Акция'),
  staff: () => t('Сотрудник'),
  '0_30': () => t('до 30 дней'),
  '31_60': () => t('31–60 дней'),
  over_60: () => t('больше 60 дней'),
}

export function breakdownLabel(item) {
  if (item.key == null) return t('Не указан')
  return KEY_LABELS[item.key]?.() || item.label || item.key
}

// Отчёты раздела «Аналитика». Новый отчёт M3 — строка здесь и маршрут в App.jsx.
export const REPORTS = [
  { key: '/analytics', get label() { return t('Обзор') } },
  { key: '/analytics/revenue', get label() { return t('Выручка') } },
  { key: '/analytics/check-debt', get label() { return t('Чек и долги') } },
  { key: '/analytics/attendance', get label() { return t('Посещаемость') } },
  { key: '/analytics/risk', get label() { return t('Зона ухода') } },
  { key: '/analytics/groups', get label() { return t('Группы') } },
  { key: '/analytics/teachers', get label() { return t('Преподаватели') } },
  { key: '/analytics/funnel', get label() { return t('Воронка продаж') } },
  { key: '/analytics/sources', get label() { return t('Источники') } },
  { key: '/analytics/rejections', get label() { return t('Отказы') } },
  { key: '/analytics/branches', get label() { return t('Филиалы') } },
]
