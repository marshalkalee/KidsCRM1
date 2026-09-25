import { forwardRef } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { cn } from './cn'

// Стиль первого React, ярче (TRU-91): главная — градиент с тенью, обычная —
// белая с рамкой 1.5px, как «Импорт» и «Отмена» в первой версии.
const VARIANTS = {
  primary: 'bg-brand-gradient text-white shadow-brand hover:brightness-105 active:brightness-95',
  secondary: 'bg-surface text-ink-muted border-[1.5px] border-line-strong hover:border-brand-300 hover:text-ink',
  ghost: 'text-ink-muted hover:bg-brand-50 hover:text-brand-600',
  danger: 'bg-danger-600 text-white hover:brightness-95',
  'danger-ghost': 'text-danger-600 hover:bg-danger-50',
  success: 'bg-success-50 text-success-600 hover:brightness-95',
}
const SIZES = {
  sm: 'h-8 px-3.5 text-xs gap-1.5',
  md: 'h-[38px] px-[18px] text-[13px] gap-1.5',
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
    'font-btn inline-flex shrink-0 items-center rounded-md font-semibold whitespace-nowrap transition',
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
