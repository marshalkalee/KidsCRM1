import { t } from '../../i18n'
// Общее для страниц групп (TRU-87).

export const GROUP_STATUSES = {
  active: { get label() { return t('Набирает') }, tone: 'success' },
  paused: { get label() { return t('Приостановлена') }, tone: 'warning' },
  closed: { get label() { return t('Закрыта') }, tone: 'neutral' },
}

export const WEEKDAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

/** [{weekday: 0, start_time: '15:00'}, {weekday: 2, …}] → «Пн, Ср · 15:00». */
export function scheduleSummary(slots = []) {
  const byTime = new Map()
  for (const slot of slots) {
    const days = byTime.get(slot.start_time) || []
    days.push(t(WEEKDAYS_SHORT[slot.weekday]))
    byTime.set(slot.start_time, days)
  }
  return [...byTime.entries()].map(([time, days]) => `${days.join(', ')} · ${time}`).join('; ')
}
