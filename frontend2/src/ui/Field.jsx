import { Children, forwardRef, isValidElement, useId, useState } from 'react'
import { Calendar } from 'lucide-react'
import { CheckSquare, Dropdown } from './Dropdown'
import { cn } from './cn'
import { t } from '../i18n'

// Поля — как в формах первого React (TRU-91): Manrope 13px, белое поле с
// рамкой 1.5px, подпись 10px капсом.
const control =
  'font-btn w-full rounded-md border-[1.5px] border-line-strong bg-surface px-3 text-[13px] text-ink placeholder:text-ink-subtle ' +
  'transition-colors focus:border-brand-400 focus:outline-none focus:ring-3 focus:ring-brand-50 ' +
  'disabled:cursor-not-allowed disabled:bg-surface-muted disabled:opacity-70'

/**
 * Подпись + поле + подсказка + ошибка сервера. Ошибка от DRF приходит
 * массивом строк — показываем первую.
 */
export function Field({ label, hint, error, required, children, className }) {
  const id = useId()
  const message = Array.isArray(error) ? error[0] : error
  return (
    <div className={cn('flex flex-col gap-[5px]', className)}>
      {label && (
        <label htmlFor={id} id={`${id}-label`} className="font-btn text-[10px] font-bold uppercase tracking-[0.07em] text-ink-subtle">
          {label}
          {required && ' *'}
        </label>
      )}
      {typeof children === 'function' ? children({ id, invalid: Boolean(message), labelId: `${id}-label` }) : children}
      {message ? (
        <p className="font-btn text-xs text-danger-600">{message}</p>
      ) : (
        hint && <p className="font-btn text-[11px] text-ink-subtle">{hint}</p>
      )}
    </div>
  )
}

export const Input = forwardRef(function Input({ className, invalid, ...rest }, ref) {
  return (
    <input
      ref={ref}
      className={cn(control, 'h-[38px]', invalid && 'border-danger-600 focus:ring-danger-50', className)}
      aria-invalid={invalid || undefined}
      {...rest}
    />
  )
})

export const Textarea = forwardRef(function Textarea({ className, invalid, rows = 3, ...rest }, ref) {
  return (
    <textarea
      ref={ref}
      rows={rows}
      className={cn(control, 'resize-y py-[9px]', invalid && 'border-danger-600', className)}
      aria-invalid={invalid || undefined}
      {...rest}
    />
  )
})

function optionsFrom(children) {
  const options = []
  Children.forEach(children, child => {
    if (!isValidElement(child)) return
    if (child.type === 'option') {
      options.push({ value: child.props.value ?? '', label: textOf(child.props.children), disabled: child.props.disabled })
    } else if (child.props?.children) {
      options.push(...optionsFrom(child.props.children))
    }
  })
  return options
}

function textOf(node) {
  if (node == null || node === false) return ''
  if (Array.isArray(node)) return node.map(textOf).join('')
  return String(node)
}

/**
 * Выпадающий список в стиле первого React. API как у нативного <select>:
 * value, onChange(e) с e.target.value, <option>-ы детьми — старый код не
 * меняется. Пункт со значением "" — подсказка («Выберите…»).
 */
export function Select({ id, value, onChange, children, invalid, disabled, required, className, 'aria-label': ariaLabel, name }) {
  const all = optionsFrom(children)
  const empty = all.find(o => o.value === '')
  const options = all.filter(o => o.value !== '' || !required)
  return (
    <div className={cn('relative', className)}>
      <Dropdown
        id={id}
        value={value ?? ''}
        onChange={v => onChange?.({ target: { value: v, name } })}
        options={options}
        placeholder={empty?.label || t('Выберите…')}
        invalid={invalid}
        disabled={disabled}
        ariaLabel={ariaLabel}
        size={className?.includes('h-9') ? 'sm' : 'md'}
      />
      {/* Для проверки формы браузером: обязательный список без значения не даст отправить. */}
      {required && (
        <input tabIndex={-1} aria-hidden="true" className="pointer-events-none absolute inset-x-0 bottom-0 h-px opacity-0" required value={value ?? ''} onChange={() => {}} />
      )}
    </div>
  )
}

/** Выбор нескольких значений — список с галочками (как выбор преподавателей). */
export function MultiSelect({ id, value, onChange, options, placeholder = t('Не выбрано'), invalid }) {
  return <Dropdown id={id} multiple value={value} onChange={onChange} options={options} placeholder={placeholder} invalid={invalid} />
}

/** Галочка первой версии (коралловый квадрат). */
export function Checkbox({ label, className, checked, onChange, disabled, ...rest }) {
  return (
    <label className={cn('font-btn inline-flex cursor-pointer select-none items-center gap-2 text-[13px] text-ink-muted', disabled && 'cursor-not-allowed opacity-60', className)}>
      <input type="checkbox" className="peer sr-only" checked={checked} onChange={onChange} disabled={disabled} {...rest} />
      <span className="rounded peer-focus-visible:ring-2 peer-focus-visible:ring-brand-400"><CheckSquare checked={checked} /></span>
      {label}
    </label>
  )
}

/** Список галочек в сером блоке (как «Доступно в филиалах» в первой версии). */
export function CheckList({ options, value, onChange, empty = t('Пусто') }) {
  if (!options.length) return <p className="font-btn text-xs text-ink-subtle">{empty}</p>
  const values = value.map(String)
  const toggle = v => onChange(values.includes(String(v)) ? values.filter(x => x !== String(v)) : [...values, String(v)])
  return (
    <div className="flex flex-col gap-2 rounded-md border-[1.5px] border-line-strong bg-surface-muted px-3 py-2.5">
      {options.map(o => (
        <Checkbox key={o.value} label={<span className="text-ink">{o.label}</span>} checked={values.includes(String(o.value))} onChange={() => toggle(o.value)} />
      ))}
    </div>
  )
}

/**
 * Дата маской «дд.мм.гггг», как в форме ребёнка первой версии. value/onChange
 * — ISO «гггг-мм-дд» (как ждёт API); пока дата не введена целиком — "".
 */
export function DateInput({ id, value, onChange, invalid, required }) {
  const toDisplay = iso => (iso ? iso.split('-').reverse().join('.') : '')
  const [text, setText] = useState(() => toDisplay(value))
  const [synced, setSynced] = useState(value)
  if (value !== synced) {
    setSynced(value)
    if (value) setText(toDisplay(value))
  }
  function change(raw) {
    let digits = raw.replace(/\D/g, '').slice(0, 8)
    if (digits.length > 4) digits = `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4)}`
    else if (digits.length > 2) digits = `${digits.slice(0, 2)}.${digits.slice(2)}`
    setText(digits)
    const parts = digits.split('.')
    const iso = parts.length === 3 && parts[2].length === 4 ? `${parts[2]}-${parts[1]}-${parts[0]}` : ''
    setSynced(iso)
    onChange(iso)
  }
  return (
    <div className="relative">
      <Input id={id} invalid={invalid} required={required} inputMode="numeric" placeholder={t('дд.мм.гггг')} maxLength={10} value={text} onChange={e => change(e.target.value)} className="pr-9" />
      <Calendar className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-ink-subtle" />
    </div>
  )
}
