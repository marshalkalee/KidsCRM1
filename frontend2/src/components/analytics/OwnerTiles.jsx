import { Link, useLocation } from 'react-router-dom'
import { ArrowDownRight, ArrowUpRight, ChevronRight, Minus } from 'lucide-react'
import { Card, Skeleton, cn } from '../../ui'
import { locale, t } from '../../i18n'
import { Change } from './MetricTile'
import { formatAxis, formatValue } from './format'

/**
 * Главный экран дашборда владельца (TRU-129): семь цифр верхнего уровня
 * из analytics/dashboard/. Каждая плитка — ссылка в подробный отчёт с тем
 * же периодом и филиалами; задолженность — на экран «Задолженности»: у
 * неё та же цифра, что итог списка должников.
 *
 * Плитка, которую бэкенд не смог посчитать, приходит пустой (null) —
 * показываем прочерк, остальной экран работает.
 */
export function OwnerTiles({ data, loading }) {
  const { search } = useLocation()
  if (!data) {
    return (
      <div className="mb-5 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3, 4, 5, 6].map(i => <Skeleton key={i} className={cn('h-[132px]', i === 6 && 'col-span-2 lg:col-span-1')} />)}
      </div>
    )
  }
  const { tiles } = data
  const report = path => `${path}${search}`
  return (
    <div className={cn('mb-5 grid grid-cols-2 gap-3 transition-opacity sm:gap-4 lg:grid-cols-4', loading && 'opacity-60')}>
      <RevenueTile tile={tiles.revenue} to={report('/analytics/revenue')} />
      <DebtTile tile={tiles.debt} to="/money?tab=debts" />
      <FillTile tile={tiles.group_fill} to={report('/analytics/groups')} />
      <LeadTile tile={tiles.lead_conversion} to={report('/analytics/funnel')} />
      <RenewalTile tile={tiles.renewal_conversion} to={report('/analytics/renewals')} />
      <RiskTile tile={tiles.risk} to={report('/analytics/risk')} />
      <ForecastTile tile={tiles.forecast} to={report('/analytics/forecast')} className="col-span-2 lg:col-span-1" />
    </div>
  )
}

function Tile({ label, value, muted, tone, footer, hint, progress, to, className }) {
  return (
    <Link to={to} className={cn('group block min-w-0', className)}>
      <Card className="flex h-full min-h-[132px] flex-col px-4 py-4 transition-shadow group-hover:shadow-pop sm:px-5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[13px] font-semibold text-ink-muted">{label}</p>
          <ChevronRight className="size-4 shrink-0 text-ink-subtle transition-transform group-hover:translate-x-0.5" />
        </div>
        <p className={cn('mt-2 truncate text-[19px] font-bold leading-tight tracking-tight sm:text-[26px]', muted ? 'text-ink-subtle' : tone || 'text-ink')}>
          {value}
        </p>
        {progress != null && (
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-muted">
            <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} />
          </div>
        )}
        <div className="mt-auto pt-2">
          {footer}
          {hint && <p className="mt-1 text-[12px] leading-snug text-ink-muted">{hint}</p>}
        </div>
      </Card>
    </Link>
  )
}

/** Деньги: на телефоне коротко («1,2 млн ₸»), с планшета — полностью. */
function Money({ value }) {
  if (value == null) return '—'
  return (
    <>
      <span className="sm:hidden">{`${formatAxis(value, 'money')} ₸`}</span>
      <span className="hidden sm:inline">{formatValue(value, 'money')}</span>
    </>
  )
}

/** «▲ 5 п.п. к прошлому периоду» — для конверсий: разница долей, а не процент от процента. */
function ChangePp({ current, previous, change }) {
  if (change == null) {
    return current != null && previous == null ? <p className="text-xs text-ink-subtle">{t('Не с чем сравнить')}</p> : null
  }
  const value = Number(change)
  const flat = value === 0
  const up = value > 0
  const Icon = flat ? Minus : up ? ArrowUpRight : ArrowDownRight
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-ink-subtle">
      <span className={cn(
        'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-semibold',
        flat ? 'bg-surface-muted text-ink-muted' : up ? 'bg-success-50 text-success-600' : 'bg-danger-50 text-danger-600',
      )}>
        <Icon className="size-3.5" />
        {t('{n} п.п.', { n: formatValue(Math.abs(value), 'count') })}
      </span>
      {t('к прошлому периоду')}
    </p>
  )
}

function Empty({ label, to, className }) {
  return <Tile label={label} value="—" muted hint={t('Не удалось посчитать — откройте отчёт')} to={to} className={className} />
}

function RevenueTile({ tile, to }) {
  const label = t('Выручка')
  if (!tile) return <Empty label={label} to={to} />
  return (
    <Tile
      label={label}
      value={<Money value={tile.value} />}
      muted={!tile.enough_data}
      footer={tile.enough_data
        ? <Change metric={{ ...tile, kind: 'event' }} />
        : <p className="text-xs text-ink-subtle">{tile.data_since ? t('Данных пока мало для сравнения') : t('Данных за период нет')}</p>}
      to={to}
    />
  )
}

function DebtTile({ tile, to }) {
  const label = t('Задолженность')
  if (!tile) return <Empty label={label} to={to} />
  const owes = Number(tile.value) > 0
  return (
    <Tile
      label={label}
      value={<Money value={tile.value} />}
      tone={owes ? 'text-danger-600' : 'text-success-600'}
      footer={<Change metric={{ ...tile, kind: 'snapshot' }} goodWhenDown />}
      hint={tile.previous == null
        ? t('История долга копится с первого ночного снимка')
        : t('На конец прошлого периода: {sum}', { sum: formatValue(tile.previous, 'money') })}
      to={to}
    />
  )
}

function FillTile({ tile, to }) {
  const label = t('Заполняемость групп')
  if (!tile) return <Empty label={label} to={to} />
  const hint = tile.capacity
    ? [
      t('{members} детей на {capacity} мест', { members: tile.members, capacity: tile.capacity }),
      tile.underfilled ? t('с недобором: {n}', { n: tile.underfilled }) : null,
    ].filter(Boolean).join(' · ')
    : t('Активных групп нет')
  return (
    <Tile
      label={label}
      value={formatValue(tile.value, 'percent')}
      muted={tile.value == null}
      progress={tile.value == null ? null : Number(tile.value)}
      footer={tile.previous == null ? null : <Change metric={{ ...tile, kind: 'snapshot' }} />}
      hint={hint}
      to={to}
    />
  )
}

function LeadTile({ tile, to }) {
  const label = t('Конверсия заявок')
  if (!tile) return <Empty label={label} to={to} />
  return (
    <Tile
      label={label}
      value={formatValue(tile.value, 'percent')}
      muted={tile.value == null}
      footer={<ChangePp current={tile.value} previous={tile.previous} change={tile.change_pp} />}
      hint={tile.leads
        ? t('Купили {n} из {total} новых заявок', { n: tile.purchased, total: tile.leads })
        : t('Новых заявок за период нет')}
      to={to}
    />
  )
}

function RenewalTile({ tile, to }) {
  const label = t('Конверсия продлений')
  if (!tile) return <Empty label={label} to={to} />
  // В начале месяца у всех закончившихся окно продления ещё идёт, и цифры
  // за период нет: показываем прошлый период той же длины с пометкой, а не
  // пустую плитку каждое утро первых двух недель.
  const fallback = tile.value == null && tile.pending > 0 && tile.previous != null
  let hint
  if (fallback) {
    hint = t('За прошлый период: окно продления текущего ещё идёт ({n})', { n: tile.pending })
  } else if (tile.decided) {
    hint = t('Продлили {n} из {total}', { n: tile.renewed, total: tile.decided })
    if (tile.small) hint = `${hint} · ${t('мало данных')}`
  } else if (tile.pending) {
    hint = t('Окно продления ещё идёт: {n} абонементов', { n: tile.pending })
  } else {
    hint = t('За период абонементы не заканчивались')
  }
  return (
    <Tile
      label={label}
      value={formatValue(fallback ? tile.previous : tile.value, 'percent')}
      muted={fallback || tile.value == null || tile.small}
      footer={fallback ? null : <ChangePp current={tile.value} previous={tile.previous} change={tile.change_pp} />}
      hint={hint}
      to={to}
    />
  )
}

function RiskTile({ tile, to }) {
  const label = t('В зоне риска ухода')
  if (!tile) return <Empty label={label} to={to} />
  return (
    <Tile
      label={label}
      value={formatValue(tile.value, 'count')}
      tone={tile.urgent ? 'text-danger-600' : null}
      hint={tile.value
        ? t('Срочно: {n} · {share}% активных детей', { n: tile.urgent, share: formatValue(tile.share_percent, 'count') })
        : t('Сигналов ухода нет')}
      to={to}
    />
  )
}

function ForecastTile({ tile, to, className }) {
  const label = t('Прогноз выручки')
  if (!tile) return <Empty label={label} to={to} className={className} />
  const [y, m] = tile.month.split('-').map(Number)
  const month = new Intl.DateTimeFormat(locale, { month: 'long' }).format(new Date(y, m - 1, 1))
  let value
  let hint
  if (tile.status === 'hidden') {
    value = '—'
    hint = t('Мало данных: нужно ещё {n} закончившихся абонементов', { n: tile.need_more })
  } else if (tile.status === 'range') {
    value = `${formatAxis(tile.low, 'money')} – ${formatAxis(tile.high, 'money')} ₸`
    hint = t('Продления на {month}: только диапазон, данных пока мало', { month })
  } else {
    value = <Money value={tile.value} />
    hint = t('Продления на {month}, скорее всего {low} – {high} ₸', { month, low: formatAxis(tile.low, 'money'), high: formatAxis(tile.high, 'money') })
  }
  return <Tile label={label} value={value} muted={tile.status === 'hidden'} hint={hint} to={to} className={className} />
}
