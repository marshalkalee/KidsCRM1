import { locale, plural, t } from '../../i18n'
import { money } from '../../ui'

/** Число метрики по её единице: деньги, штуки, проценты. null — «—». */
export function formatValue(value, unit) {
  if (value == null || value === '') return '—'
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  if (unit === 'money') return money(number)
  if (unit === 'percent') return `${new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(number)}%`
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(number)
}

/** Короткая подпись оси: «2,4 млн», «350 тыс.». Без ₸ — иначе подпись
 * переносится; тенге видно в подсказке и в плитке. */
export function formatAxis(value, unit) {
  const number = Number(value)
  if (unit === 'percent') return `${number}%`
  return new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(number)
}

/** Подпись точки графика по шагу периода: «12 сент.», «нед. 8 сент.», «сент. 2026». */
export function formatBucket(iso, granularity) {
  const [y, m, d] = iso.split('-').map(Number)
  const date = new Date(y, m - 1, d)
  if (granularity === 'month') {
    return new Intl.DateTimeFormat(locale, { month: 'short', year: 'numeric' }).format(date)
  }
  const day = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short' }).format(date)
  return granularity === 'week' ? t('нед. с {day}', { day }) : day
}

/** «1 – 30 сент. 2026» */
export function formatRange(period) {
  if (!period) return ''
  const [sy, sm, sd] = period.start.split('-').map(Number)
  const [ey, em, ed] = period.end.split('-').map(Number)
  const start = new Date(sy, sm - 1, sd)
  const end = new Date(ey, em - 1, ed)
  if (period.start === period.end) {
    return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long', year: 'numeric' }).format(end)
  }
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short', year: 'numeric' }).formatRange(start, end)
}

export function daysLabel(n) {
  return `${n} ${plural(n, ['день', 'дня', 'дней'])}`
}
