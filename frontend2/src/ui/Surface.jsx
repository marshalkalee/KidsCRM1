import { Link } from 'react-router-dom'
import { ChevronLeft, Inbox, Loader2 } from 'lucide-react'
import { cn } from './cn'

export function Card({ className, children, padded = true, ...rest }) {
  return (
    <div className={cn('rounded-lg border border-line bg-surface shadow-card', padded && 'p-5', className)} {...rest}>
      {children}
    </div>
  )
}

export function CardHeader({ title, description, actions, className }) {
  return (
    <div className={cn('mb-4 flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-bold text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-[13px] text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

const BADGE_TONES = {
  neutral: 'bg-surface-muted text-ink-muted',
  brand: 'bg-brand-50 text-brand-700',
  success: 'bg-success-50 text-success-600',
  warning: 'bg-warning-50 text-warning-600',
  danger: 'bg-danger-50 text-danger-600',
  info: 'bg-info-50 text-info-600',
}

export function Badge({ tone = 'neutral', dot = false, className, children }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold', BADGE_TONES[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

/**
 * Заголовок страницы — единственный на экране (в шапке приложения его нет).
 * back — «хлебная крошка» к родительскому разделу над заголовком
 * (карточка ребёнка: «‹ Дети»). Действия справа, на телефоне — под заголовком.
 */
export function PageHeader({ title, description, actions, back }) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {back && (
          <Link to={back.to} className="-ml-1 mb-1.5 inline-flex items-center gap-0.5 rounded px-1 text-[13px] font-semibold text-ink-muted transition-colors hover:text-brand-700">
            <ChevronLeft className="size-4" />
            {back.label}
          </Link>
        )}
        <h1 className="text-[26px] font-bold leading-tight tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1.5 text-sm text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({ icon: Icon = Inbox, title, description, action, className }) {
  return (
    <div className={cn('flex flex-col items-center justify-center px-6 py-14 text-center', className)}>
      <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-brand-50 text-brand-500">
        <Icon className="size-6" />
      </div>
      <p className="font-semibold text-ink">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-ink-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Spinner({ className, label = 'Загрузка…' }) {
  return (
    <div className={cn('flex items-center justify-center gap-2 py-10 text-sm text-ink-muted', className)} role="status">
      <Loader2 className="size-5 animate-spin text-brand-500" />
      {label}
    </div>
  )
}

export function Skeleton({ className }) {
  return <div className={cn('animate-pulse rounded-md bg-surface-muted', className)} />
}

/** Ошибка загрузки с повтором — вместо пустого экрана или вечного спиннера. */
export function ErrorState({ title = 'Не удалось загрузить данные', onRetry }) {
  return (
    <div className="flex flex-col items-center py-12 text-center">
      <p className="font-semibold text-ink">{title}</p>
      <p className="mt-1 text-sm text-ink-muted">Проверьте соединение и попробуйте ещё раз.</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="mt-4 text-sm font-semibold text-brand-600 hover:text-brand-700">
          Повторить
        </button>
      )}
    </div>
  )
}
