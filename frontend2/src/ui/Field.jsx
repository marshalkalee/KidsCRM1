import { forwardRef, useId } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from './cn'

const control =
  'w-full rounded-md border border-line bg-surface px-3 text-sm text-ink placeholder:text-ink-subtle ' +
  'transition-colors hover:border-line-strong focus:border-brand-400 focus:outline-none focus:ring-3 focus:ring-brand-100 ' +
  'disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-ink-muted'

/**
 * Подпись + поле + подсказка + ошибка сервера. Ошибка от DRF приходит
 * массивом строк — показываем первую.
 */
export function Field({ label, hint, error, required, children, className }) {
  const id = useId()
  const message = Array.isArray(error) ? error[0] : error
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label && (
        <label htmlFor={id} className="text-[13px] font-semibold text-ink">
          {label}
          {required && <span className="ml-0.5 text-danger-600">*</span>}
        </label>
      )}
      {typeof children === 'function' ? children({ id, invalid: Boolean(message) }) : children}
      {message ? (
        <p className="text-xs text-danger-600">{message}</p>
      ) : (
        hint && <p className="text-xs text-ink-subtle">{hint}</p>
      )}
    </div>
  )
}

export const Input = forwardRef(function Input({ className, invalid, ...rest }, ref) {
  return (
    <input
      ref={ref}
      className={cn(control, 'h-10', invalid && 'border-danger-600 focus:ring-danger-50', className)}
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
      className={cn(control, 'py-2', invalid && 'border-danger-600', className)}
      aria-invalid={invalid || undefined}
      {...rest}
    />
  )
})

/** Нативный select (доступный, работает на телефоне) в стиле остальных полей. */
export const Select = forwardRef(function Select({ className, invalid, children, ...rest }, ref) {
  return (
    <div className="relative">
      <select
        ref={ref}
        className={cn(control, 'h-10 appearance-none pr-9', invalid && 'border-danger-600', className)}
        aria-invalid={invalid || undefined}
        {...rest}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 size-4 -translate-y-1/2 text-ink-subtle" />
    </div>
  )
})

export function Checkbox({ label, className, ...rest }) {
  return (
    <label className={cn('inline-flex cursor-pointer items-center gap-2 text-sm text-ink', className)}>
      <input type="checkbox" className="size-4 rounded border-line-strong accent-brand-600" {...rest} />
      {label}
    </label>
  )
}
