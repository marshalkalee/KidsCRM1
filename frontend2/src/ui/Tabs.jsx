import { cn } from './cn'
import { Select } from './Field'
import { t } from '../i18n'

/**
 * Вкладки: на десктопе — полоса вкладок, на телефоне — выпадающий список
 * (не уезжает в горизонтальный скролл, ТЗ п. 10.4).
 * tabs: [{ key, label, count? }]
 */
export function Tabs({ tabs, value, onChange, className }) {
  return (
    <div className={className}>
      <div className="sm:hidden">
        <Select aria-label={t('Раздел')} value={value} onChange={e => onChange(e.target.value)}>
          {tabs.map(tab => <option key={tab.key} value={tab.key}>{tab.label}</option>)}
        </Select>
      </div>
      <div role="tablist" className="hidden flex-wrap gap-1 border-b border-line sm:flex">
        {tabs.map(tab => {
          const active = tab.key === value
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(tab.key)}
              className={cn(
                '-mb-px inline-flex items-center gap-2 border-b-2 px-3.5 py-2.5 text-sm font-semibold transition-colors',
                active ? 'border-brand-600 text-brand-600' : 'border-transparent text-ink-muted hover:text-ink',
              )}
            >
              {tab.label}
              {tab.count != null && (
                <span className={cn('rounded-full px-1.5 text-[11px]', active ? 'bg-brand-50 text-brand-600' : 'bg-line text-ink-muted')}>
                  {tab.count}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
