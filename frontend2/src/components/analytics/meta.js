import { Banknote, CalendarCheck, Inbox, Percent, Receipt, UsersRound, Wallet, Baby } from 'lucide-react'
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
  debt_total: { get label() { return t('Задолженность') }, icon: Wallet, goodWhenDown: true },
  visits: { get label() { return t('Посещений') }, icon: CalendarCheck },
  attendance_marks: { get label() { return t('Отметок посещаемости') }, icon: CalendarCheck },
  attendance_rate: { get label() { return t('Доля посещений') }, icon: Percent },
  active_children: { get label() { return t('Ходили на занятия') }, icon: Baby },
  new_leads: { get label() { return t('Новых заявок') }, icon: Inbox },
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
