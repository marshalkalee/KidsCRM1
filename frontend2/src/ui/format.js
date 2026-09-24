// Форматирование для экранов: деньги в тенге, даты по-русски, возраст.
const moneyFormat = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 })

export function money(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return `${moneyFormat.format(number)} ₸`
}

/** '2018-03-12' → '12.03.2018' (без new Date — не сдвигается часовым поясом). */
export function formatDate(iso) {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}.${m}.${y}`
}

export function ageLabel(age) {
  if (age == null) return '—'
  const mod10 = age % 10
  const mod100 = age % 100
  if (mod10 === 1 && mod100 !== 11) return `${age} год`
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${age} года`
  return `${age} лет`
}

// Статусы ребёнка — как Child.Status на бэке.
export const CHILD_STATUSES = {
  active: { label: 'Активен', tone: 'success' },
  paused: { label: 'Приостановлен', tone: 'warning' },
  left: { label: 'Ушёл', tone: 'neutral' },
}

const dateTimeFormat = new Intl.DateTimeFormat('ru-RU', {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
})

/** '2026-09-24T10:15:00+05:00' → '24 сент. 2026 г., 10:15' (время браузера). */
export function formatDateTime(iso) {
  if (!iso) return '—'
  return dateTimeFormat.format(new Date(iso))
}

// Роли контакта — как ChildContact.Role на бэке.
export const CONTACT_ROLES = {
  mother: 'Мама',
  father: 'Папа',
  guardian: 'Опекун',
  grandmother: 'Бабушка',
  other: 'Другое',
}
