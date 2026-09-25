// Форматирование для экранов: деньги в тенге, даты по-русски, возраст.
import { locale, plural, t } from '../i18n'

// Форматтеры под текущий язык; пересоздаются при смене (setLang).
const formatters = new Map()
function formatter(kind, options) {
  const key = `${kind}:${locale}`
  if (!formatters.has(key)) formatters.set(key, new Intl[kind](locale, options))
  return formatters.get(key)
}

export function money(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${formatter('NumberFormat', { maximumFractionDigits: 0 }).format(number)} ₸`
}

/** '2018-03-12' → '12.03.2018' (без new Date — не сдвигается часовым поясом). */
export function formatDate(iso) {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}.${m}.${y}`
}

export function ageLabel(age) {
  if (age == null) return '—'
  return `${age} ${plural(age, ['год', 'года', 'лет'])}`
}

// Статусы ребёнка — как Child.Status на бэке.
export const CHILD_STATUSES = {
  active: { get label() { return t('Активен') }, tone: 'success' },
  paused: { get label() { return t('Приостановлен') }, tone: 'warning' },
  left: { get label() { return t('Ушёл') }, tone: 'neutral' },
}

const DATE_TIME = {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
}

/** '2026-09-24T10:15:00+05:00' → '24 сент. 2026 г., 10:15' (время браузера). */
export function formatDateTime(iso) {
  if (!iso) return '—'
  return formatter('DateTimeFormat', DATE_TIME).format(new Date(iso))
}

// Роли контакта — как ChildContact.Role на бэке.
export const CONTACT_ROLES = {
  get mother() { return t('Мама') },
  get father() { return t('Папа') },
  get guardian() { return t('Опекун') },
  get grandmother() { return t('Бабушка') },
  get other() { return t('Другое') },
}
