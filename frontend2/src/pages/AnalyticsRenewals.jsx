import { useState } from 'react'
import { Info } from 'lucide-react'
import { Badge, Card, CardHeader, DataTable, ErrorState, PageHeader, Skeleton, Tabs, cn } from '../ui'
import { locale, plural, t } from '../i18n'
import {
  AnalyticsNav, AnalyticsToolbar, ComboChart, ExportButton, PALETTE, formatValue,
  useAnalyticsCatalog, useAnalyticsFilters, useAnalyticsGet,
} from '../components/analytics'

const DIMENSIONS = [
  { key: 'branch', get label() { return t('Филиал') } },
  { key: 'direction', get label() { return t('Направление') } },
  { key: 'group', get label() { return t('Группа') } },
  { key: 'teacher', get label() { return t('Преподаватель') } },
  { key: 'type', get label() { return t('Тип абонемента') } },
  { key: 'age', get label() { return t('Возраст ребёнка') } },
]
const GAP_LABELS = {
  early: () => t('Заранее или в день окончания'),
  week: () => t('1–7 дней'),
  two_weeks: () => t('8–14 дней'),
  month: () => t('15–30 дней'),
  later: () => t('Больше 30 дней'),
}

/**
 * «Продления» (TRU-126, ТЗ п. 5.3): сколько абонементов, закончившихся за
 * период, продлено. Что такое «продлён» — одно определение с прогнозом
 * выручки (subscriptions/renewal_conversion.py), окно — в настройках
 * организации. Пока окно продления идёт, «не продлил» записывать рано:
 * такие абонементы показаны отдельно и в процент не входят. Первые
 * продления — отдельно от последующих. Разрез по преподавателю — не
 * рейтинг: по алфавиту и рядом заполняемость и время занятий групп.
 */
export default function AnalyticsRenewals() {
  const filters = useAnalyticsFilters()
  const catalog = useAnalyticsCatalog()
  const { data, error, loading } = useAnalyticsGet('renewal-conversion', '', filters)
  const [dimension, setDimension] = useState('branch')

  const summary = data?.summary
  const rules = data?.rules

  return (
    <>
      <PageHeader
        title={t('Аналитика')}
        description={t('Сколько абонементов продлили из закончившихся')}
        actions={<ExportButton report="renewal_conversion" filters={filters} />}
      />
      <AnalyticsNav />
      <AnalyticsToolbar filters={filters} catalog={catalog} period={data?.period} />

      {error ? (
        <Card><ErrorState /></Card>
      ) : !summary ? (
        <Skeleton className="h-96" />
      ) : (
        <div className={cn('transition-opacity', loading && 'opacity-60')}>
          <div className="mb-4 grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Tile
              label={t('Конверсия продлений')}
              value={formatValue(summary.rate, 'percent')}
              note={summary.decided ? t('продлили {renewed} из {decided}', { renewed: summary.renewed, decided: summary.decided }) : t('пока не из чего считать')}
            />
            <Tile
              label={t('Первые продления')}
              value={formatValue(summary.first.rate, 'percent')}
              note={t('продлили {renewed} из {decided} — первый абонемент', { renewed: summary.first.renewed, decided: summary.first.decided })}
            />
            <Tile
              label={t('Последующие')}
              value={formatValue(summary.repeat.rate, 'percent')}
              note={t('продлили {renewed} из {decided}', { renewed: summary.repeat.renewed, decided: summary.repeat.decided })}
            />
            <Tile
              label={t('Окно продления идёт')}
              value={formatValue(summary.pending, 'count')}
              note={t('из них уже продлили {n}; в процент войдут, когда пройдут {days} дн.', { days: rules.grace_days, n: summary.pending_renewed })}
            />
          </div>
          <p className="mb-4 flex items-start gap-2 text-[13px] text-ink-muted">
            <Info className="mt-0.5 size-4 shrink-0 text-info-600" />
            {t('Закончилось в периоде: {ended}. Продлён — у ребёнка есть следующий абонемент того же направления, начавшийся не позже {days} дней после окончания, или проданный кнопкой «Продлить». Процент — по абонементам, у которых это окно уже прошло. Окно меняется в «Настройки → Организация».', { ended: summary.ended, days: rules.grace_days })}
          </p>

          <div className="mb-4 grid gap-4 lg:grid-cols-5">
            <Card className="min-w-0 lg:col-span-3">
              <CardHeader title={t('По месяцам')} description={t('Закончилось абонементов и доля продлённых, по месяцу окончания')} />
              <div style={{ height: 280 }}>
                <ComboChart
                  bars={data.trend.map(row => ({ date: row.month, value: row.ended }))}
                  line={data.trend.map(row => ({ date: row.month, value: row.rate }))}
                  granularity="month"
                  barLabel={t('Закончилось')}
                  lineLabel={t('Конверсия')}
                />
              </div>
              <TrendNote trend={data.trend} />
            </Card>
            <Card className="min-w-0 lg:col-span-2">
              <CardHeader title={t('Срок продления')} description={t('На какой день после окончания купили продление')} />
              <GapBars gaps={data.gaps} />
            </Card>
          </div>

          <Card padded={false}>
            <div className="p-5 pb-3">
              <CardHeader title={t('Разрезы')} description={t('Где продлевают лучше и хуже. Меньше {n} абонементов в строке — процент ненадёжен.', { n: rules.min_sample })} />
              <Tabs tabs={DIMENSIONS} value={dimension} onChange={setDimension} />
              {dimension === 'teacher' && (
                <p className="mt-3 flex items-start gap-2 rounded-lg bg-warning-50 px-3 py-2 text-[13px] text-ink">
                  <Info className="mt-0.5 size-4 shrink-0 text-warning-600" />
                  {t('Это не рейтинг преподавателей. Продления зависят и от времени занятий, и от возраста детей, и от заполняемости группы — смотрите рядом. Ребёнок у двух преподавателей учитывается у обоих.')}
                </p>
              )}
            </div>
            <BreakdownTable dimension={dimension} rows={data.breakdowns[dimension]} />
          </Card>
        </div>
      )}
    </>
  )
}

function Tile({ label, value, note }) {
  return (
    <Card className="min-w-0">
      <p className="text-[13px] font-semibold text-ink-muted">{label}</p>
      <p className="mt-2 truncate text-[20px] font-bold text-ink sm:text-[24px]">{value}</p>
      {note && <p className="mt-1 text-xs text-ink-subtle">{note}</p>}
    </Card>
  )
}

function TrendNote({ trend }) {
  const open = trend.filter(row => !row.complete)
  if (!open.length) return null
  return (
    <p className="mt-2 text-xs text-ink-subtle">
      {t('Последние месяцы дособираются: {months} — окно продления ещё идёт.', { months: open.map(row => formatMonth(row.month)).join(', ') })}
    </p>
  )
}

function GapBars({ gaps }) {
  if (!gaps.renewed) {
    return <p className="py-8 text-center text-sm text-ink-muted">{t('Продлений в периоде нет')}</p>
  }
  const max = Math.max(1, ...gaps.buckets.map(row => row.value))
  return (
    <>
      <ul className="space-y-3">
        {gaps.buckets.map((row, index) => (
          <li key={row.key}>
            <div className="mb-1 flex items-baseline justify-between gap-3 text-[13px]">
              <span className="min-w-0 truncate text-ink">{GAP_LABELS[row.key]?.() || row.label}</span>
              <span className="shrink-0 font-semibold text-ink">
                {formatValue(row.value, 'count')}
                <span className="ml-1.5 text-xs font-normal text-ink-subtle">{formatValue(row.share, 'percent')}</span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
              <div className="h-full rounded-full" style={{ width: `${(row.value / max) * 100}%`, background: index < 2 ? PALETTE[0] : 'var(--color-warning-600)' }} />
            </div>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-xs text-ink-subtle">
        {t('В среднем через {days} дн. Пауза дольше {long} дней — риск потери: {n} из {total}.', {
          days: formatValue(gaps.average_days, 'count'),
          long: gaps.long_pause_days,
          n: gaps.long_pause,
          total: gaps.renewed,
        })}
      </p>
    </>
  )
}

function rowLabel(dimension, row) {
  if (dimension === 'age' && row.key != null) return `${row.key} ${plural(Number(row.key), ['год', 'года', 'лет'])}`
  if (row.key == null) {
    if (dimension === 'group') return t('Без группы')
    if (dimension === 'teacher') return t('Без преподавателя')
    return t('Не указано')
  }
  return row.label
}

function Rate({ value, small }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn('font-semibold', small ? 'text-ink-subtle' : 'text-ink')}>{formatValue(value, 'percent')}</span>
      {small && value != null && <Badge tone="neutral">{t('мало данных')}</Badge>}
    </span>
  )
}

function BreakdownTable({ dimension, rows }) {
  const columns = [
    { key: 'label', header: DIMENSIONS.find(d => d.key === dimension).label, primary: true, render: row => rowLabel(dimension, row) },
    { key: 'ended', header: t('Закончилось'), align: 'right', render: row => formatValue(row.ended, 'count') },
    { key: 'renewed', header: t('Продлили'), align: 'right', render: row => `${formatValue(row.renewed, 'count')} / ${formatValue(row.decided, 'count')}` },
    { key: 'rate', header: t('Конверсия'), align: 'right', mobileAside: true, render: row => <Rate value={row.rate} small={row.small} /> },
    { key: 'first', header: t('Первые'), align: 'right', render: row => formatValue(row.first.rate, 'percent') },
    { key: 'repeat', header: t('Последующие'), align: 'right', render: row => formatValue(row.repeat.rate, 'percent') },
  ]
  if (dimension === 'group' || dimension === 'teacher') {
    columns.push({
      key: 'context',
      header: t('Заполняемость и время занятий'),
      render: row => <GroupsContext context={row.context} />,
    })
  }
  return (
    <DataTable
      columns={columns}
      rows={rows}
      rowKey={row => row.key ?? 'none'}
      empty={<p className="py-8 text-center text-sm text-ink-muted">{t('За этот период абонементы не заканчивались')}</p>}
    />
  )
}

function GroupsContext({ context }) {
  if (!context?.groups.length) return <span className="text-ink-subtle">—</span>
  return (
    <ul className="space-y-0.5 text-xs text-ink-muted">
      {context.groups.map(group => (
        <li key={group.name}>
          <span className="font-semibold text-ink">{group.name}</span>
          {' · '}
          {t('{percent}% ({occupied} из {capacity})', { percent: group.fill_percent, occupied: group.occupied, capacity: group.capacity })}
          {group.slots.length > 0 && ` · ${group.slots.map(slot => `${weekday(slot.weekday)} ${slot.time}`).join(', ')}`}
        </li>
      ))}
    </ul>
  )
}

// 1 января 2024 — понедельник: день недели слота (0 — пн) без своего словаря.
function weekday(index) {
  return new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(2024, 0, 1 + index))
}

function formatMonth(iso) {
  const [y, m] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat(locale, { month: 'short', year: 'numeric' }).format(new Date(y, m - 1, 1))
}
