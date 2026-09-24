export const WEEKDAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
const MONTH_LABELS = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

export function startOfWeek(date) {
  const d = new Date(date)
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  d.setHours(0, 0, 0, 0)
  return d
}

export function addDays(date, n) {
  const d = new Date(date)
  d.setDate(d.getDate() + n)
  return d
}

export function toISODate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function isSameDay(date, isoDateStr) {
  return toISODate(date) === isoDateStr
}

export function isToday(date) {
  return toISODate(date) === toISODate(new Date())
}

export function formatWeekRange(monday) {
  const sunday = addDays(monday, 6)
  const sameMonth = monday.getMonth() === sunday.getMonth()
  const sameYear = monday.getFullYear() === sunday.getFullYear()
  if (sameMonth) {
    return `${monday.getDate()}–${sunday.getDate()} ${MONTH_LABELS[monday.getMonth()]} ${monday.getFullYear()}`
  }
  if (sameYear) {
    return `${monday.getDate()} ${MONTH_LABELS[monday.getMonth()]} – ${sunday.getDate()} ${MONTH_LABELS[sunday.getMonth()]} ${monday.getFullYear()}`
  }
  return `${monday.getDate()} ${MONTH_LABELS[monday.getMonth()]} ${monday.getFullYear()} – ${sunday.getDate()} ${MONTH_LABELS[sunday.getMonth()]} ${sunday.getFullYear()}`
}

export function formatDayLabel(date) {
  return `${WEEKDAY_LABELS[date.getDay() === 0 ? 6 : date.getDay() - 1]}, ${date.getDate()} ${MONTH_LABELS[date.getMonth()]}`
}

// API отдаёт *_local как ISO-строку с уже посчитанным офсетом организации
// (см. LessonSerializer.get_starts_at_local) — берём дату/время из самой
// строки, а не через new Date(), чтобы не пересчитать в таймзону браузера.
export function localDatePart(isoLocal) {
  return isoLocal.slice(0, 10)
}

export function localTimePart(isoLocal) {
  return isoLocal.slice(11, 16)
}

export function timeToMinutes(hhmm) {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}
