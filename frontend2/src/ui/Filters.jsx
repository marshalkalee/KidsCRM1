import { useEffect, useId, useRef, useState } from 'react'
import { Check, ChevronDown, Search, SlidersHorizontal, X } from 'lucide-react'
import { Button } from './Button'
import { cn } from './cn'

/**
 * Фильтры списков как в первом React (TRU-91): строка поиска + кнопка
 * «Фильтры» со счётчиком применённых; под ней панель с выпадающими
 * списками и галочками, «Применить» и «Сбросить». Что считается
 * применённым, решает страница (обычно — параметры в адресе).
 */
export function FilterBar({ search, filtersOpen, onToggleFilters, activeCount = 0, showFilters = true }) {
  return (
    <div className="flex gap-2.5">
      <div className="min-w-0 flex-1">{search}</div>
      {showFilters && (
        <button
          type="button"
          onClick={onToggleFilters}
          aria-expanded={filtersOpen}
          className={cn(
            'font-btn relative flex h-10 shrink-0 items-center gap-2 rounded-[10px] border-[1.5px] px-4 text-[13px] font-semibold transition-colors',
            filtersOpen || activeCount ? 'border-brand-400 bg-brand-50 text-brand-600' : 'border-line bg-surface text-ink-muted hover:text-ink',
          )}
        >
          <SlidersHorizontal className="size-4" />
          <span className="hidden sm:inline">Фильтры</span>
          {activeCount > 0 && (
            <span className="absolute -right-2 -top-2 flex size-[18px] items-center justify-center rounded-full bg-brand-600 text-[10px] font-bold text-white">{activeCount}</span>
          )}
        </button>
      )}
    </div>
  )
}

/** Поле поиска списка — белое, как в первом React. Значение — снаружи. */
export function SearchField({ value, onChange, placeholder }) {
  return (
    <label className="flex h-10 items-center gap-2.5 rounded-[10px] border border-line bg-surface px-3.5 focus-within:border-brand-400 focus-within:ring-3 focus-within:ring-brand-50">
      <Search className="size-4 shrink-0 text-ink-subtle" />
      <input
        type="search"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={placeholder}
        className="w-full bg-transparent text-[13px] text-ink placeholder:text-ink-subtle focus:outline-none"
      />
    </label>
  )
}

export function FilterPanel({ children, checks, onApply, onReset, dirty, canReset }) {
  return (
    <div className="flex flex-col gap-4 rounded-lg border border-line bg-surface px-5 py-4 xl:flex-row xl:items-end">
      <div className="grid gap-2.5 sm:grid-cols-2 md:grid-cols-4 xl:flex xl:flex-nowrap">{children}</div>
      {checks && (
        <>
          <div className="hidden h-[52px] w-px shrink-0 bg-line-strong xl:block" />
          <div className="flex shrink-0 flex-col gap-2.5 whitespace-nowrap pb-0.5">{checks}</div>
        </>
      )}
      <div className="flex gap-1.5 xl:ml-auto xl:flex-col">
        <Button variant="primary" size="sm" onClick={onApply} disabled={!dirty}>Применить</Button>
        {canReset && <Button size="sm" icon={X} onClick={onReset}>Сбросить</Button>}
      </div>
    </div>
  )
}

/** Выпадающий список фильтра (как CustomSelect первого React). options: [[value, label]]. */
export function FilterSelect({ label, value, onChange, options }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const id = useId()

  useEffect(() => {
    if (!open) return undefined
    const onDown = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    const onKey = e => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])

  const selected = options.find(([v]) => String(v) === String(value))
  const active = value !== '' && value != null
  return (
    <div ref={ref} className="relative w-full xl:w-40">
      <p id={id} className="font-btn mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">{label}</p>
      <button
        type="button"
        aria-labelledby={id}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
        className={cn(
          'font-btn flex h-9 w-full items-center justify-between gap-2 rounded-md border-[1.5px] px-2.5 text-xs transition-colors',
          active || open ? 'border-brand-400 bg-brand-50 font-semibold text-brand-600' : 'border-line-strong bg-surface-muted text-ink-muted',
          open && 'ring-3 ring-brand-50',
        )}
      >
        <span className="truncate">{selected ? selected[1] : options[0]?.[1]}</span>
        <ChevronDown className={cn('size-3.5 shrink-0 transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <ul role="listbox" aria-labelledby={id} className="absolute inset-x-0 top-[calc(100%+4px)] z-30 max-h-64 overflow-y-auto rounded-[10px] border-[1.5px] border-line bg-surface py-1 shadow-pop">
          {options.map(([v, l]) => {
            const isSelected = String(v) === String(value)
            return (
              <li key={v || 'all'}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  onClick={() => { onChange(v); setOpen(false) }}
                  className={cn(
                    'font-btn flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs',
                    isSelected ? 'bg-brand-50 font-semibold text-brand-600' : 'text-ink hover:bg-surface-muted',
                  )}
                >
                  <span className="truncate">{l}</span>
                  {isSelected && <Check className="size-3.5 shrink-0" />}
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

/** Галочка фильтра (как CheckboxCard первого React). */
export function FilterCheck({ label, checked, onChange }) {
  return (
    <label className="font-btn flex cursor-pointer select-none items-center gap-2 text-xs font-semibold">
      <input type="checkbox" className="peer sr-only" checked={checked} onChange={e => onChange(e.target.checked)} />
      <span className={cn(
        'flex size-3.5 shrink-0 items-center justify-center rounded border-2 transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand-400',
        checked ? 'border-brand-600 bg-brand-600 text-white' : 'border-line-strong bg-surface',
      )}>
        {checked && <Check className="size-2.5" strokeWidth={4} />}
      </span>
      <span className={checked ? 'text-brand-600' : 'text-ink'}>{label}</span>
    </label>
  )
}
