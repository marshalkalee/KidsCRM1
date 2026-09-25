import { t } from '../i18n'
// Рабочие часы филиала — как backend/domains/platform/tenants/working_hours.py.
export const WEEKDAYS = [
  ['mon', 'Пн', 'Понедельник'],
  ['tue', 'Вт', 'Вторник'],
  ['wed', 'Ср', 'Среда'],
  ['thu', 'Чт', 'Четверг'],
  ['fri', 'Пт', 'Пятница'],
  ['sat', 'Сб', 'Суббота'],
  ['sun', 'Вс', 'Воскресенье'],
]

// Как default_working_hours() на бэке: пн–пт 09:00–20:00, выходные закрыты.
export function initialHours(hours) {
  return Object.fromEntries(WEEKDAYS.map(([code]) => {
    const day = hours?.[code]
    const weekend = code === 'sat' || code === 'sun'
    return [code, {
      closed: day ? Boolean(day.closed) : weekend,
      open: day?.open || '09:00',
      close: day?.close || '20:00',
    }]
  }))
}

/** «Пн–Пт 09:00–20:00, Сб 10:00–14:00» — короткая сводка для карточки филиала. */
export function hoursSummary(hours) {
  const days = initialHours(hours)
  const groups = []
  for (const [code, ruShort] of WEEKDAYS) {
    const short = t(ruShort)
    const day = days[code]
    const label = day.closed ? null : `${day.open}–${day.close}`
    const last = groups[groups.length - 1]
    if (last && last.label === label) last.to = short
    else groups.push({ from: short, to: short, label })
  }
  const open = groups.filter(g => g.label)
  if (!open.length) return t('Закрыт всю неделю')
  return open.map(g => `${g.from}${g.to !== g.from ? `–${g.to}` : ''} ${g.label}`).join(', ')
}
