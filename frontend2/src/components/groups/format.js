import { t } from '../../i18n'
// Общее для страниц групп (TRU-87).

export const GROUP_STATUSES = {
  active: { label: t('Набирает'), tone: 'success' },
  paused: { label: t('Приостановлена'), tone: 'warning' },
  closed: { label: t('Закрыта'), tone: 'neutral' },
}

export const WEEKDAYS_SHORT = [t('Пн'), t('Вт'), t('Ср'), t('Чт'), t('Пт'), t('Сб'), t('Вс')]

/** [{weekday: 0, start_time: '15:00'}, {weekday: 2, …}] → «Пн, Ср · 15:00». */
export function scheduleSummary(slots = []) {
  const byTime = new Map()
  for (const slot of slots) {
    const days = byTime.get(slot.start_time) || []
    days.push(WEEKDAYS_SHORT[slot.weekday])
    byTime.set(slot.start_time, days)
  }
  return [...byTime.entries()].map(([time, days]) => `${days.join(', ')} · ${time}`).join('; ')
}
