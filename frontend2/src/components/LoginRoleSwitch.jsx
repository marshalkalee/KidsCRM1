import { Link } from 'react-router-dom'
import { Building2, Users } from 'lucide-react'
import { cn } from '../ui'
import { t } from '../i18n'

const OPTIONS = [
  { key: 'staff', to: '/login', icon: Building2, label: 'Сотрудник центра' },
  { key: 'parent', to: '/parent/login', icon: Users, label: 'Родитель' },
]

/** Один выбор роли для обоих способов входа; меняется только форма ниже. */
export default function LoginRoleSwitch({ value }) {
  return (
    <div className="mb-7">
      <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.07em] text-ink-subtle">
        {t('Кто вы?')}
      </p>
      <div className="grid grid-cols-2 gap-1 rounded-lg bg-surface-muted p-1" role="tablist" aria-label={t('Выберите способ входа')}>
        {OPTIONS.map(option => (
          <Link
            key={option.key}
            to={option.to}
            role="tab"
            aria-selected={value === option.key}
            className={cn(
              'flex min-h-11 items-center justify-center gap-2 rounded-md px-2 text-center text-[13px] font-semibold transition',
              value === option.key
                ? 'border border-line bg-surface text-brand-600 shadow-sm'
                : 'text-ink-muted hover:text-ink',
            )}
          >
            <option.icon className="size-4 shrink-0" />
            <span>{t(option.label)}</span>
          </Link>
        ))}
      </div>
    </div>
  )
}
