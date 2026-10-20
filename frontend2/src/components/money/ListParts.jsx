import { X } from 'lucide-react'
import { Button, FilterBar, cn } from '../../ui'
import { t } from '../../i18n'

/*
 * Общие части списков «Деньги» (долги, продления): карточки-сводка сверху и
 * верхняя строка таблицы — выбрать всех, поиск, фильтры; когда кто-то
 * выбран — массовые действия прямо над таблицей, а не в шапке страницы.
 */

const TONES = {
  danger: 'bg-danger-50 text-danger-600',
  warning: 'bg-warning-50 text-warning-600',
  info: 'bg-info-50 text-info-600',
  brand: 'bg-brand-50 text-brand-600',
  success: 'bg-success-50 text-success-600',
}

export function StatRow({ children }) {
  return <div className="mb-4 grid gap-3 sm:grid-cols-3">{children}</div>
}

/** Карточка с числом. С onClick — быстрый фильтр: нажата — подсвечена. */
export function StatCard({ icon: Icon, tone = 'brand', label, value, hint, active = false, onClick }) {
  const body = (
    <>
      <span className={cn('flex size-11 shrink-0 items-center justify-center rounded-lg', TONES[tone])}><Icon className="size-5" /></span>
      <span className="min-w-0">
        <span className="block text-[13px] text-ink-muted">{label}</span>
        <span className="block text-2xl font-bold text-ink">{value}</span>
        {hint && <span className="block text-[12px] text-ink-subtle">{hint}</span>}
      </span>
    </>
  )
  const base = 'flex items-center gap-4 rounded-lg border bg-surface p-5 text-left shadow-card'
  if (!onClick) return <div className={cn(base, 'border-line')}>{body}</div>
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(base, 'transition', active ? 'border-brand-400 ring-3 ring-brand-50' : 'border-line hover:border-brand-300')}
    >
      {body}
    </button>
  )
}

export function ListToolbar({
  selectedCount, allSelected, onToggleAll, onClearSelection, bulkActions,
  search, filtersOpen, onToggleFilters, activeFilters, filtersPanel, canSelect,
}) {
  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center gap-3">
        {canSelect && (
          <input
            type="checkbox"
            checked={allSelected}
            onChange={onToggleAll}
            aria-label={t('Выбрать все на странице')}
            title={t('Выбрать все на странице')}
            className="size-4 shrink-0 accent-[var(--color-brand-500)]"
          />
        )}
        {selectedCount > 0 ? (
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-ink">{t('Выбрано: {n}', { n: selectedCount })}</span>
            {bulkActions}
            <Button size="sm" variant="ghost" icon={X} onClick={onClearSelection}>{t('Снять выбор')}</Button>
          </div>
        ) : (
          <div className="min-w-0 flex-1">
            <FilterBar search={search} filtersOpen={filtersOpen} onToggleFilters={onToggleFilters} activeCount={activeFilters} />
          </div>
        )}
      </div>
      {filtersOpen && selectedCount === 0 && filtersPanel}
    </div>
  )
}
