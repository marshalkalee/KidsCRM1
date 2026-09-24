import { forwardRef } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { cn } from './cn'

const VARIANTS = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 shadow-card',
  secondary: 'bg-surface text-ink border border-line-strong hover:bg-surface-muted',
  ghost: 'text-ink-muted hover:bg-surface-muted hover:text-ink',
  danger: 'bg-danger-600 text-white hover:brightness-95 shadow-card',
  'danger-ghost': 'text-danger-600 hover:bg-danger-50',
}
const SIZES = {
  sm: 'h-8 px-3 text-[13px] gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
  icon: 'h-9 w-9 justify-center',
}

/**
 * Кнопка или ссылка-кнопка (to=…). loading — блокирует повторное нажатие
 * (двойной клик не отправит форму дважды) и показывает спиннер.
 */
export const Button = forwardRef(function Button(
  { variant = 'secondary', size = 'md', icon: Icon, loading = false, to, className, children, disabled, type = 'button', ...rest },
  ref,
) {
  const classes = cn(
    'inline-flex shrink-0 items-center rounded-md font-semibold transition-colors',
    'disabled:cursor-not-allowed disabled:opacity-60',
    VARIANTS[variant],
    SIZES[size],
    className,
  )
  const content = (
    <>
      {loading ? <Loader2 className="size-4 animate-spin" /> : Icon && <Icon className="size-4" />}
      {children}
    </>
  )
  if (to) {
    return <Link ref={ref} to={to} className={classes} {...rest}>{content}</Link>
  }
  return (
    <button ref={ref} type={type} className={classes} disabled={disabled || loading} {...rest}>
      {content}
    </button>
  )
})
