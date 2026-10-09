import { useMemo, useState } from 'react'
import { Info } from 'lucide-react'
import { Card, ErrorState, PageHeader, cn } from '../ui'
import { t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ExportButton, ChartCard, DonutChart, MetricTile, PALETTE, RankBars, TrendChart,
  useAnalyticsCatalog, useAnalyticsFilters, useBreakdown, useMetrics,
} from '../components/analytics'

const TILES = ['revenue', 'payments_count', 'average_check', 'debt_total']
// Шаг графика: «авто» — по длине периода (до месяца дни, до полугода недели).
const STEPS = [
  { value: '', get label() { return t('Авто') } },
  { value: 'day', get label() { return t('Дни') } },
  { value: 'week', get label() { return t('Недели') } },
  { value: 'month', get label() { return t('Месяцы') } },
]
const CLIENT_COLORS = [PALETTE[0], 'var(--color-success-600)']

/**
 * Отчёт «Выручка» (TRU-123 на каркасе TRU-113): по фактическим оплатам,
 * не по проданным абонементам. Разрезы — филиал, направление, тип
 * абонемента, способ оплаты; структура — новые клиенты или продления.
 */
export default function AnalyticsRevenue() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const [step, setStep] = useState('')
  // Шаг касается только графика динамики и выгрузки; разрезы его не знают.
  const stepped = useMemo(
    () => (step ? { ...filters, query: `${filters.query}&granularity=${step}` } : filters),
    [filters, step],
  )
  const { data, loading, error, reload } = useMetrics(TILES, stepped)
  const metrics = data?.metrics || {}
  const common = { loading, error, onRetry: reload, metric: metrics.revenue }

  const clients = useBreakdown('revenue', 'client', filters)
  const methods = useBreakdown('revenue', 'method', filters)
  const branches = useBreakdown('revenue', 'branch', filters)
  const directions = useBreakdown('revenue', 'direction', filters)
  const types = useBreakdown('revenue', 'subscription_type', filters)

  const breakdownCard = (title, description, result, children, extra = {}) => (
    <ChartCard
      autoHeight
      title={title}
      description={description}
      ready={Boolean(result.data)}
      empty={!result.data?.items.length}
      {...common}
      {...extra}
    >
      {children}
    </ChartCard>
  )

  return (
    <>
      <PageHeader title={t('Аналитика')} description={t('Выручка по оплатам')} actions={<ExportButton report="revenue" filters={stepped} />} />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} previous={data?.previous_period} />

      {error && !data ? (
        <Card><ErrorState onRetry={reload} /></Card>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-3 xl:grid-cols-4">
            {TILES.map(name => <MetricTile key={name} name={name} metric={metrics[name]} loading={loading} />)}
          </div>

          <p className="mb-5 flex items-start gap-2 rounded-lg border border-info-50 bg-info-50/40 px-4 py-3 text-[13px] text-ink-muted">
            <Info className="mt-0.5 size-4 shrink-0 text-info-600" />
            {t('Выручка считается по дате оплаты — сколько денег пришло в кассу, а не сколько абонементов продано. Отменённая оплата уменьшает выручку того дня, когда её принимали.')}
          </p>

          <div className="grid gap-4 lg:grid-cols-3">
            <ChartCard
              className="lg:col-span-2"
              title={t('Динамика выручки')}
              description={t('Пунктир — прошлый период той же длины')}
              actions={<StepPicker value={step} onChange={setStep} />}
              {...common}
            >
              <TrendChart series={metrics.revenue?.series} previous={metrics.revenue?.previous_series} unit="money" granularity={data?.period?.granularity} label={t('Выручка')} />
            </ChartCard>
            {breakdownCard(t('Новые клиенты и продления'), t('Откуда деньги'), clients,
              <DonutChart items={clients.data?.items} unit="money" colors={CLIENT_COLORS} centerLabel={t('за период')} />)}
            {breakdownCard(t('По филиалам'), t('Кто приносит больше'), branches,
              <RankBars items={branches.data?.items} unit="money" />)}
            {breakdownCard(t('По направлениям'), t('Какие занятия покупают'), directions,
              <RankBars items={directions.data?.items} unit="money" color={PALETTE[1]} />)}
            {breakdownCard(t('По типам абонементов'), t('Какие абонементы берут'), types,
              <RankBars items={types.data?.items} unit="money" color={PALETTE[2]} />)}
            {breakdownCard(t('Как платят'), t('Способы оплаты'), methods,
              <DonutChart items={methods.data?.items} unit="money" centerLabel={t('за период')} />)}
          </div>
        </>
      )}
    </>
  )
}

function StepPicker({ value, onChange }) {
  return (
    <div role="radiogroup" aria-label={t('Шаг графика')} className="flex gap-1">
      {STEPS.map(option => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'h-8 rounded-md px-2.5 text-[12px] font-semibold transition-colors',
            value === option.value ? 'bg-brand-50 text-brand-700' : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}