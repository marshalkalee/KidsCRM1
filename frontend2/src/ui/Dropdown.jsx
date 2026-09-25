import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from './cn'

/**
 * Выпадающий список как CustomSelect первого React (TRU-91): выбранное —
 * розовым, в списке — галочка. Список открывается порталом поверх всего,
 * поэтому не обрезается прокруткой модалки.
 *
 * options: [{ value, label, disabled? }]. multiple — value массив, пункты с
 * квадратными галочками (как выбор преподавателей в первой версии).
 */
export function Dropdown({
  id, value, onChange, options, placeholder = 'Выберите…', multiple = false, invalid, disabled,
  size = 'md', ariaLabel, ariaLabelledby, className,
}) {
  const [open, setOpen] = useState(false)
  const [rect, setRect] = useState(null)
  const buttonRef = useRef(null)
  const listRef = useRef(null)

  const values = multiple ? (value || []).map(String) : []
  const selected = multiple ? options.filter(o => values.includes(String(o.value))) : options.find(o => String(o.value) === String(value ?? ''))
  const active = multiple ? values.length > 0 : value !== '' && value != null
  const label = multiple
    ? (selected.length ? selected.map(o => o.label).join(', ') : placeholder)
    : (selected ? selected.label : placeholder)

  const place = useCallback(() => {
    if (buttonRef.current) setRect(buttonRef.current.getBoundingClientRect())
  }, [])

  useLayoutEffect(() => { if (open) place() }, [open, place])

  useEffect(() => {
    if (!open) return undefined
    const onDown = e => {
      if (!buttonRef.current?.contains(e.target) && !listRef.current?.contains(e.target)) setOpen(false)
    }
    // Фаза захвата на window: Escape закрывает список, а не модалку под ним.
    const onKey = e => {
      if (e.key !== 'Escape') return
      e.stopPropagation()
      setOpen(false)
      buttonRef.current?.focus()
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
  }, [open, place])

  function pick(option) {
    if (option.disabled) return
    if (multiple) {
      const key = String(option.value)
      onChange(values.includes(key) ? values.filter(v => v !== key) : [...values, key])
      return
    }
    onChange(option.value)
    setOpen(false)
    buttonRef.current?.focus()
  }

  // Места снизу мало — открываемся вверх.
  const LIST_MAX = 240
  const openUp = rect && window.innerHeight - rect.bottom < Math.min(LIST_MAX, options.length * 40 + 12) && rect.top > window.innerHeight - rect.bottom
  const small = size === 'sm'

  return (
    <>
      <button
        ref={buttonRef}
        id={id}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledby}
        aria-invalid={invalid || undefined}
        onClick={() => setOpen(o => !o)}
        className={cn(
          'font-btn flex w-full items-center justify-between gap-2 rounded-md border-[1.5px] text-left transition-all',
          small ? 'h-9 px-2.5 text-xs' : 'h-[38px] px-3 text-[13px]',
          active || open ? 'border-brand-400 bg-brand-50 font-semibold text-brand-600' : 'border-line-strong bg-surface-muted text-ink-subtle',
          open && 'ring-3 ring-brand-50',
          invalid && 'border-danger-600',
          disabled && 'cursor-not-allowed opacity-60',
          className,
        )}
      >
        <span className="truncate">{label}</span>
        <ChevronDown className={cn('size-3.5 shrink-0 transition-transform', open && 'rotate-180')} />
      </button>
      {open && rect && createPortal(
        <ul
          ref={listRef}
          role="listbox"
          aria-multiselectable={multiple || undefined}
          style={{
            position: 'fixed',
            left: rect.left,
            width: Math.max(rect.width, 180),
            maxHeight: LIST_MAX,
            ...(openUp ? { bottom: window.innerHeight - rect.top + 4 } : { top: rect.bottom + 4 }),
          }}
          className="z-[70] overflow-y-auto rounded-[10px] border-[1.5px] border-line bg-surface py-1 shadow-pop"
        >
          {options.length === 0 && <li className="font-btn px-3.5 py-2.5 text-[13px] text-ink-subtle">Пусто</li>}
          {options.map(option => {
            const isSelected = multiple ? values.includes(String(option.value)) : String(option.value) === String(value ?? '')
            return (
              <li key={String(option.value) || '__empty'}>
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  disabled={option.disabled}
                  onClick={() => pick(option)}
                  className={cn(
                    'font-btn flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] disabled:opacity-50',
                    !multiple && isSelected ? 'bg-brand-50 font-semibold text-brand-600' : 'text-ink hover:bg-surface-muted',
                  )}
                >
                  {multiple && <CheckSquare checked={isSelected} />}
                  <span className="min-w-0 flex-1 truncate">{option.label}</span>
                  {!multiple && isSelected && <Check className="size-3.5 shrink-0" />}
                </button>
              </li>
            )
          })}
        </ul>,
        document.body,
      )}
    </>
  )
}

/** Квадратная галочка первой версии: коралловая, с белой «птичкой». */
export function CheckSquare({ checked, size = 16 }) {
  return (
    <span
      style={{ width: size, height: size }}
      className={cn(
        'flex shrink-0 items-center justify-center rounded border-2',
        checked ? 'border-brand-600 bg-brand-600 text-white' : 'border-[#d1d5db] bg-surface',
      )}
    >
      {checked && <Check className="size-2.5" strokeWidth={4} />}
    </span>
  )
}
