import { t } from '../../i18n'

// Статусы воронки — как Lead.Status на бэке (TRU-99). dot — цвет точки
// в заголовке колонки и на бейдже; tone — тон Badge.
export const LEAD_STATUSES = [
  { value: 'new', get label() { return t('Новая') }, dot: 'bg-info-600', tone: 'info' },
  { value: 'contacted', get label() { return t('Связались') }, dot: 'bg-brand-500', tone: 'brand' },
  { value: 'trial_scheduled', get label() { return t('Записан на пробное') }, dot: 'bg-warning-600', tone: 'warning' },
  { value: 'trial_attended', get label() { return t('Пришёл на пробное') }, dot: 'bg-[#8b5cf6]', tone: 'brand' },
  { value: 'purchased', get label() { return t('Купил абонемент') }, dot: 'bg-success-600', tone: 'success' },
  { value: 'thinking', get label() { return t('Думает') }, dot: 'bg-ink-subtle', tone: 'neutral' },
  { value: 'rejected', get label() { return t('Отказ') }, dot: 'bg-danger-600', tone: 'danger' },
]

export const LEAD_STATUS = Object.fromEntries(LEAD_STATUSES.map(s => [s.value, s]))

/** Кого показывать заголовком карточки: ребёнка, если известен, иначе родителя. */
export function leadTitle(lead) {
  return lead.child_name || lead.parent_name
}
