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

// Цвета этапов центра (TRU-154, LeadStage.Color на бэке). Значения по
// умолчанию у основных этапов дают ровно те же точки и бейджи, что были.
export const STAGE_DOT = {
  blue: 'bg-info-600',
  red: 'bg-brand-500',
  amber: 'bg-warning-600',
  violet: 'bg-[#8b5cf6]',
  green: 'bg-success-600',
  gray: 'bg-ink-subtle',
  pink: 'bg-danger-600',
  teal: 'bg-[#14b8a6]',
}
export const STAGE_TONE = {
  blue: 'info', red: 'brand', amber: 'warning', violet: 'brand', green: 'success', gray: 'neutral', pink: 'danger', teal: 'info',
}
export const STAGE_COLORS = [
  { value: 'blue', get label() { return t('Синий') } },
  { value: 'red', get label() { return t('Красный') } },
  { value: 'amber', get label() { return t('Жёлтый') } },
  { value: 'violet', get label() { return t('Фиолетовый') } },
  { value: 'green', get label() { return t('Зелёный') } },
  { value: 'gray', get label() { return t('Серый') } },
  { value: 'pink', get label() { return t('Розовый') } },
  { value: 'teal', get label() { return t('Бирюзовый') } },
]

/** Бейдж этапа заявки — название и цвет центра. */
export function stageBadge(lead) {
  return { tone: STAGE_TONE[lead.stage_color] || 'neutral', label: lead.stage_name || lead.status_label }
}

/** Кого показывать заголовком карточки: ребёнка, если известен, иначе родителя. */
export function leadTitle(lead) {
  return lead.child_name || lead.parent_name
}
