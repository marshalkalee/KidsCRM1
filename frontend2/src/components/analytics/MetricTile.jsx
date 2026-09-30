import { ArrowDownRight, ArrowUpRight, Hourglass, Minus } from 'lucide-react'
import { Line, LineChart, ResponsiveContainer } from 'recharts'
import { Card, Skeleton, cn } from '../../ui'
import { t } from '../../i18n'
import { daysLabel, formatAxis, formatValue } from './format'
import { METRIC_META, PALETTE, metricLabel } from './meta'

/**
 * Плитка метрики (TRU-113): число, изменение к прошлому периоду и
 * маленький график. Данных мало — число приглушено и честная подпись
 * «нужно ещё N дней», а не стрелка «+300%» по двум точкам.
 *
 * <MetricTile name="revenue" metric={data.metrics.revenue} />
 */
export function MetricTile({ name, metric, loading, onClick }) {
  const meta = METRIC_META[name] || {}
  const Icon = meta.icon
  if (!metric) {
    return (
      <Card className="flex min-h-[120px] flex-col gap-3 sm:min-h-[132px]">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-3 w-40" />
      </Card>
    )
  }
  const thin = !metric.enough_data
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      className={cn(
        'flex min-h-[120px] min-w-0 flex-col rounded-lg border border-line bg-surface p-4 text-left transition-opacity sm:min-h-[132px] sm:p-5',
        onClick && 'hover:shadow-pop',
        loading && 'opacity-60',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-[13px] font-semibold text-ink-muted">{metricLabel(name, metric)}</p>
        {Icon && <Icon className="size-4 shrink-0 text-ink-subtle" />}
      </div>
      <p className={cn('mt-2 truncate text-[19px] font-bold leading-tight tracking-tight sm:text-[26px]', thin ? 'text-ink-subtle' : 'text-ink')}>
        {metric.unit === 'money' ? (
          <>
            {/* На телефоне в плитке пол-экрана: «1,1 млрд ₸», полностью — с планшета. */}
            <span className="sm:hidden">{metric.value == null ? '—' : `${formatAxis(metric.value, 'money')} ₸`}</span>
            <span className="hidden sm:inline">{formatValue(metric.value, metric.unit)}</span>
          </>
        ) : formatValue(metric.value, metric.unit)}
      </p>
      <div className="mt-auto flex items-end justify-between gap-3 pt-2">
        {thin ? <NotEnough metric={metric} /> : <Change metric={metric} goodWhenDown={meta.goodWhenDown} />}
        {!thin && <Sparkline series={metric.series} />}
      </div>
    </Tag>
  )
}

function NotEnough({ metric }) {
  return (
    <p className="flex items-center gap-1.5 text-xs text-ink-subtle">
      <Hourglass className="size-3.5 shrink-0" />
      {metric.data_since
        ? t('Данных пока мало: ещё {days}', { days: daysLabel(metric.days_until_enough) })
        : t('Данных за период нет')}
    </p>
  )
}

/** «▲ 12% к прошлому периоду» — зелёным, если это хорошо, красным — если плохо.
 * compact — без подписи, для таблицы, где она уже в заголовке столбца. */
export function Change({ metric, goodWhenDown = false, compact = false }) {
  if (metric.kind === 'snapshot' && metric.previous == null) {
    return <p className="text-xs text-ink-subtle">{t('Сейчас')}</p>
  }
  const change = metric.change_percent == null ? null : Number(metric.change_percent)
  if (change == null) {
    return <p className="text-xs text-ink-subtle">{t('Не с чем сравнить')}</p>
  }
  const up = change > 0
  const flat = change === 0
  const good = flat ? null : up !== goodWhenDown
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-ink-subtle">
      <span className={cn(
        'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-semibold',
        good == null ? 'bg-surface-muted text-ink-muted' : good ? 'bg-success-50 text-success-600' : 'bg-danger-50 text-danger-600',
      )}>
        <Icon className="size-3.5" />
        {formatValue(Math.abs(change), 'percent')}
      </span>
      {!compact && t('к прошлому периоду')}
    </p>
  )
}

function Sparkline({ series }) {
  if (!series || series.length < 2) return null
  const data = series.map(point => ({ v: point.value == null ? null : Number(point.value) }))
  return (
    <div className="hidden h-8 w-20 shrink-0 sm:block" aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <Line type="monotone" dataKey="v" stroke={PALETTE[0]} strokeWidth={1.75} dot={false} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
