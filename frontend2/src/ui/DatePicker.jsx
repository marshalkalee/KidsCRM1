import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from './cn'
import { locale, t } from '../i18n'

const pad = n => String(n).padStart(2, '0')
const toIso = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`
const todayIso = () => {
  const now = new Date()
  return toIso(now.getFullYear(), now.getMonth(), now.getDate())
}

function parseIso(iso) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return null
  const [y, m, d] = iso.split('-').map(Number)
  return { y, m: m - 1, d }
}

// Названия месяцев и дней недели — из Intl на языке интерфейса.
function monthName(m, style = 'long') {
  const name = new Intl.DateTimeFormat(locale, { month: style }).format(new Date(2024, m, 1))
  return name.charAt(0).toUpperCase() + name.slice(1)
}

function weekdayNames() {
  // 1 января 2024 — понедельник; неделя с понедельника, как в Казахстане.
  return Array.from({ length: 7 }, (_, i) => new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(2024, 0, 1 + i)))
}

const POPOVER_HEIGHT = 330
const POPOVER_WIDTH = 288

/**
 * Календарь для выбора даты, в стиле выпадающих списков (TRU-91/92).
 * Открывается порталом под якорем anchorRef; value/onChange — ISO «гггг-мм-дд».
 * Клик по названию месяца — выбор года и месяца (удобно для даты рождения).
 */
export function DatePicker({ anchorRef, value, onChange, onClose, min, max }) {
  const selected = parseIso(value)
  const today = todayIso()
  const start = selected || parseIso(max && max < today ? max : today)
  const [view, setView] = useState('days')
  const [year, setYear] = useState(start.y)
  const [month, setMonth] = useState(start.m)
  const [rect, setRect] = useState(null)
  const popRef = useRef(null)

  const place = useCallback(() => {
    if (anchorRef.current) setRect(anchorRef.current.getBoundingClientRect())
  }, [anchorRef])

  useLayoutEffect(() => { place() }, [place])

  useEffect(() => {
    const onDown = e => {
      if (!popRef.current?.contains(e.target) && !anchorRef.current?.contains(e.target)) onClose()
    }
    // Фаза захвата: Escape закрывает календарь, а не модалку под ним.
    const onKey = e => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      onClose()
    }
    document.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey, true)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey, true)
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [anchorRef, onClose, place])

  if (!rect) return null

  const outOfRange = iso => (min && iso < min) || (max && iso > max)
  const maxYear = max ? Number(max.slice(0, 4)) : null
  const minYear = min ? Number(min.slice(0, 4)) : null

  function shiftMonth(delta) {
    const next = new Date(year, month + delta, 1)
    setYear(next.getFullYear())
    setMonth(next.getMonth())
  }

  function pick(iso) {
    if (outOfRange(iso)) return
    onChange(iso)
    onClose()
  }

  const openUp = window.innerHeight - rect.bottom < POPOVER_HEIGHT + 8 && rect.top > window.innerHeight - rect.bottom
  const left = Math.max(8, Math.min(rect.right - POPOVER_WIDTH, window.innerWidth - POPOVER_WIDTH - 8))
  const style = openUp
    ? { left, bottom: window.innerHeight - rect.top + 6, width: POPOVER_WIDTH }
    : { left, top: rect.bottom + 6, width: POPOVER_WIDTH }

  const navBtn = 'flex size-8 items-center justify-center rounded-md text-ink-muted hover:bg-surface-muted hover:text-ink disabled:opacity-30 disabled:hover:bg-transparent'
  const cellBase = 'flex items-center justify-center rounded-md text-[13px] transition-colors'

  let header
  let body
  if (view === 'days') {
    const first = (new Date(year, month, 1).getDay() + 6) % 7
    const daysInMonth = new Date(year, month + 1, 0).getDate()
    const cells = [...Array(first).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)]
    header = (
      <>
        <button type="button" className={navBtn} onClick={() => shiftMonth(-1)} aria-label={t('Предыдущий месяц')}><ChevronLeft className="size-4" /></button>
        <button type="button" className="rounded-md px-2 py-1 text-sm font-semibold text-ink hover:bg-surface-muted" onClick={() => setView('years')}>
          {monthName(month)} {year}
        </button>
        <button type="button" className={navBtn} onClick={() => shiftMonth(1)} aria-label={t('Следующий месяц')}><ChevronRight className="size-4" /></button>
      </>
    )
    body = (
      <>
        <div className="mb-1 grid grid-cols-7 text-center text-[11px] font-semibold uppercase text-ink-subtle">
          {weekdayNames().map(name => <span key={name} className="py-1">{name}</span>)}
        </div>
        <div className="grid grid-cols-7 gap-0.5">
          {cells.map((d, i) => {
            if (!d) return <span key={`e${i}`} />
            const iso = toIso(year, month, d)
            const isSelected = iso === value
            const disabled = outOfRange(iso)
            return (
              <button
                key={iso}
                type="button"
                disabled={disabled}
                onClick={() => pick(iso)}
                aria-pressed={isSelected}
                className={cn(
                  cellBase, 'h-9',
                  isSelected ? 'bg-brand-gradient font-semibold text-white shadow-sm'
                    : iso === today ? 'font-semibold text-brand-600 ring-1 ring-brand-300 hover:bg-brand-50'
                      : 'text-ink hover:bg-brand-50',
                  disabled && 'cursor-not-allowed text-ink-subtle opacity-40 hover:bg-transparent',
                )}
              >
                {d}
              </button>
            )
          })}
        </div>
      </>
    )
  } else if (view === 'years') {
    const from = Math.floor(year / 12) * 12
    const years = Array.from({ length: 12 }, (_, i) => from + i)
    header = (
      <>
        <button type="button" className={navBtn} onClick={() => setYear(year - 12)} disabled={minYear != null && from <= minYear} aria-label={t('Назад')}><ChevronLeft className="size-4" /></button>
        <span className="text-sm font-semibold text-ink">{from}–{from + 11}</span>
        <button type="button" className={navBtn} onClick={() => setYear(year + 12)} disabled={maxYear != null && from + 11 >= maxYear} aria-label={t('Вперёд')}><ChevronRight className="size-4" /></button>
      </>
    )
    body = (
      <div className="grid grid-cols-3 gap-1.5">
        {years.map(y => {
          const disabled = (maxYear != null && y > maxYear) || (minYear != null && y < minYear)
          return (
            <button
              key={y}
              type="button"
              disabled={disabled}
              onClick={() => { setYear(y); setView('months') }}
              className={cn(cellBase, 'h-11', y === selected?.y ? 'bg-brand-gradient font-semibold text-white' : 'text-ink hover:bg-brand-50', disabled && 'opacity-30 hover:bg-transparent')}
            >
              {y}
            </button>
          )
        })}
      </div>
    )
  } else {
    header = (
      <>
        <button type="button" className={navBtn} onClick={() => setYear(year - 1)} aria-label={t('Назад')}><ChevronLeft className="size-4" /></button>
        <button type="button" className="rounded-md px-2 py-1 text-sm font-semibold text-ink hover:bg-surface-muted" onClick={() => setView('years')}>{year}</button>
        <button type="button" className={navBtn} onClick={() => setYear(year + 1)} aria-label={t('Вперёд')}><ChevronRight className="size-4" /></button>
      </>
    )
    body = (
      <div className="grid grid-cols-3 gap-1.5">
        {Array.from({ length: 12 }, (_, m) => {
          const disabled = (max && toIso(year, m, 1) > max) || (min && toIso(year, m + 1, 0) < min)
          const isSelected = selected && selected.y === year && selected.m === m
          return (
            <button
              key={m}
              type="button"
              disabled={Boolean(disabled)}
              onClick={() => { setMonth(m); setView('days') }}
              className={cn(cellBase, 'h-11', isSelected ? 'bg-brand-gradient font-semibold text-white' : 'text-ink hover:bg-brand-50', disabled && 'opacity-30 hover:bg-transparent')}
            >
              {monthName(m, 'short').replace('.', '')}
            </button>
          )
        })}
      </div>
    )
  }

  return createPortal(
    <div
      ref={popRef}
      role="dialog"
      aria-label={t('Выбор даты')}
      style={style}
      className="fixed z-[70] rounded-xl border border-line bg-surface p-3 shadow-pop"
    >
      <div className="mb-2 flex items-center justify-between">{header}</div>
      {body}
      <div className="mt-2 flex justify-between border-t border-line pt-2">
        <button
          type="button"
          className="rounded-md px-2 py-1 text-[13px] font-semibold text-brand-600 hover:bg-brand-50 disabled:opacity-40"
          disabled={Boolean(outOfRange(today))}
          onClick={() => pick(today)}
        >
          {t('Сегодня')}
        </button>
        {value && (
          <button type="button" className="rounded-md px-2 py-1 text-[13px] text-ink-muted hover:bg-surface-muted" onClick={() => { onChange(''); onClose() }}>
            {t('Очистить')}
          </button>
        )}
      </div>
    </div>,
    document.body,
  )
}
