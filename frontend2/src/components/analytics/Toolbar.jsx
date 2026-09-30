import { useState } from 'react'
import { Button, DateInput, Dropdown, cn } from '../../ui'
import { useSession } from '../../session/SessionContext'
import { t } from '../../i18n'
import { PERIODS } from './filters'
import { formatRange } from './format'

/**
 * Панель над каждым отчётом (TRU-113): период и филиалы. Выбор один на все
 * отчёты — лежит в адресе (filters.js). period/previous — из ответа API,
 * чтобы подпись «1–30 сент., сравнение с 1–30 авг.» совпадала с расчётом.
 */
export function AnalyticsToolbar({ filters, catalog, period, previous }) {
  return (
    <div className="mb-5 flex flex-col gap-3 rounded-xl border border-line bg-surface px-4 py-3 sm:px-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <PeriodPicker filters={filters} />
        <BranchPicker filters={filters} catalog={catalog} />
      </div>
      {filters.period === 'custom' && <CustomRange filters={filters} />}
      {period && (
        <p className="text-[12px] text-ink-subtle">
          {formatRange(period)}
          {previous && ` · ${t('сравнение с {range}', { range: formatRange(previous) })}`}
        </p>
      )}
    </div>
  )
}

export function PeriodPicker({ filters }) {
  return (
    <div role="radiogroup" aria-label={t('Период')} className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-0.5">
      {PERIODS.map(option => {
        const active = filters.period === option.value
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => filters.setPeriod(option.value)}
            className={cn(
              'h-9 shrink-0 rounded-md px-3.5 text-[13px] font-semibold transition-colors',
              active ? 'bg-brand-50 text-brand-700' : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}

function CustomRange({ filters }) {
  const [start, setStart] = useState(filters.from)
  const [end, setEnd] = useState(filters.to)
  const invalid = start && end && start > end
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        {t('С')}
        <div className="w-40"><DateInput value={start} onChange={setStart} max={end || undefined} /></div>
      </label>
      <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wide text-ink-subtle">
        {t('По')}
        <div className="w-40"><DateInput value={end} onChange={setEnd} min={start || undefined} /></div>
      </label>
      <Button variant="primary" disabled={!start || !end || invalid} onClick={() => filters.setRange(start, end)}>
        {t('Показать')}
      </Button>
      {invalid && <p className="w-full text-xs text-danger-600">{t('Начало позже конца периода.')}</p>}
    </div>
  )
}

/**
 * Филиалы: несколько или все. Управляющему приходят только его филиалы
 * (catalog с бэка), так что чужой здесь не выбрать. Ничего не выбрано —
 * как в шапке.
 */
export function BranchPicker({ filters, catalog }) {
  const { activeBranch } = useSession()
  const branches = catalog?.branches || []
  if (branches.length < 2) return null
  const everything = catalog.can_see_all_branches ? t('Все филиалы') : t('Мои филиалы')
  return (
    <div className="w-full lg:w-72">
      <Dropdown
        multiple
        size="sm"
        ariaLabel={t('Филиалы')}
        value={filters.branches}
        onChange={filters.setBranches}
        options={branches.map(b => ({ value: String(b.id), label: b.name }))}
        placeholder={activeBranch ? activeBranch.name : everything}
      />
    </div>
  )
}
