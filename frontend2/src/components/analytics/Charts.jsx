import {
  Area, Bar, CartesianGrid, Cell, ComposedChart, Line, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { t } from '../../i18n'
import { formatAxis, formatBucket, formatValue } from './format'
import { PALETTE, breakdownLabel } from './meta'

/**
 * Графики отчётов (TRU-113) на recharts — одна палитра, одни оси и одна
 * подсказка на все отчёты. series — как приходит из API: [{date, value}];
 * granularity — period.granularity (day / week / month).
 */

const AXIS = { fontSize: 11, fill: 'var(--color-ink-subtle)' }
const num = value => (value == null ? null : Number(value))

function ChartTooltip({ active, payload, label, granularity, rows }) {
  if (!active || !payload?.length) return null
  return (
    <div className="min-w-36 rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-pop">
      <p className="mb-1 text-ink-subtle">{formatBucket(label, granularity)}</p>
      {payload.map(item => {
        const row = rows?.find(r => r.key === item.dataKey)
        return (
          <p key={item.dataKey} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-ink-muted">
              <span className="size-2 rounded-full" style={{ background: item.color || item.stroke }} />
              {row?.label}
            </span>
            <span className="font-bold text-ink">{formatValue(item.value, row?.unit)}</span>
          </p>
        )
      })}
    </div>
  )
}

function xAxis(granularity) {
  return (
    <XAxis
      dataKey="date"
      tick={AXIS}
      tickLine={false}
      axisLine={false}
      minTickGap={16}
      tickFormatter={value => formatBucket(value, granularity)}
    />
  )
}

/**
 * Динамика с прошлым периодом: текущий — линия с заливкой, прошлый —
 * серый пунктир под ним, точка к точке («1-е число к 1-му»).
 */
export function TrendChart({ series, previous, unit, granularity, color = PALETTE[0], label = t('Сейчас') }) {
  const data = (series || []).map((point, i) => ({
    date: point.date,
    value: num(point.value),
    previous: previous ? num(previous[i]?.value) : undefined,
  }))
  const gradient = `trend-${color.replace(/\W/g, '')}`
  const rows = [
    { key: 'value', label, unit },
    { key: 'previous', label: t('Прошлый период'), unit },
  ]
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.22} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid vertical={false} stroke="var(--color-line)" />
        {xAxis(granularity)}
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={60} tickFormatter={v => formatAxis(v, unit)} />
        <Tooltip content={<ChartTooltip granularity={granularity} rows={rows} />} />
        {previous && (
          <Line type="monotone" dataKey="previous" stroke="var(--color-ink-subtle)" strokeWidth={1.5} strokeDasharray="4 4" dot={false} connectNulls animationDuration={600} />
        )}
        <Area type="monotone" dataKey="value" stroke={color} strokeWidth={2} fill={`url(#${gradient})`} connectNulls dot={false} activeDot={{ r: 4 }} animationDuration={600} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/** Столбцы — количество по дням/неделям/месяцам: заявки, оплаты. */
export function BarsChart({ series, unit, granularity, color = PALETTE[0], label = t('Значение') }) {
  const rows = [{ key: 'value', label, unit }]
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={(series || []).map(p => ({ date: p.date, value: num(p.value) }))} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--color-line)" />
        {xAxis(granularity)}
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={60} tickFormatter={v => formatAxis(v, unit)} />
        <Tooltip cursor={{ fill: 'var(--color-surface-muted)' }} content={<ChartTooltip granularity={granularity} rows={rows} />} />
        <Bar dataKey="value" fill={color} radius={[4, 4, 0, 0]} maxBarSize={36} animationDuration={600} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/**
 * Две величины разной природы на одном графике: столбцы — количество
 * (посещения), линия — доля (процент посещаемости) по правой оси.
 */
export function ComboChart({ bars, line, granularity, barLabel, lineLabel, barUnit = 'count', lineUnit = 'percent' }) {
  const data = (bars || []).map((point, i) => ({ date: point.date, bars: num(point.value), line: num(line?.[i]?.value) }))
  const rows = [
    { key: 'bars', label: barLabel, unit: barUnit },
    { key: 'line', label: lineLabel, unit: lineUnit },
  ]
  return (
    <ResponsiveContainer width="100%" height="100%">
      <ComposedChart data={data} margin={{ top: 8, right: 0, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--color-line)" />
        {xAxis(granularity)}
        <YAxis yAxisId="bars" tick={AXIS} tickLine={false} axisLine={false} width={60} tickFormatter={v => formatAxis(v, barUnit)} />
        <YAxis yAxisId="line" orientation="right" domain={[0, 100]} tick={AXIS} tickLine={false} axisLine={false} width={40} tickFormatter={v => formatAxis(v, lineUnit)} />
        <Tooltip cursor={{ fill: 'var(--color-surface-muted)' }} content={<ChartTooltip granularity={granularity} rows={rows} />} />
        <Bar yAxisId="bars" dataKey="bars" fill={PALETTE[1]} fillOpacity={0.85} radius={[4, 4, 0, 0]} maxBarSize={32} animationDuration={600} />
        <Line yAxisId="line" type="monotone" dataKey="line" stroke={PALETTE[0]} strokeWidth={2.5} dot={false} connectNulls animationDuration={600} />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

// Итог в центре кольца — коротко, иначе «118 605 000 ₸» не влезает в кольцо.
function compact(value, unit) {
  const short = formatAxis(value, unit)
  return unit === 'money' ? `${short} ₸` : short
}

/**
 * Кольцо — из чего состоит целое: способы оплаты, «был / отработка / не
 * был». В центре — итог, справа — доли. items — из API разбивки.
 */
export function DonutChart({ items, unit, colors = PALETTE, centerLabel }) {
  const rows = (items || []).map((item, i) => ({ ...item, name: breakdownLabel(item), value: Number(item.value), color: colors[i % colors.length] }))
  const total = rows.reduce((sum, row) => sum + row.value, 0)
  return (
    <div className="flex flex-col items-center gap-4">
      <div className="relative size-40 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={rows} dataKey="value" nameKey="name" innerRadius="68%" outerRadius="100%" paddingAngle={rows.length > 1 ? 2 : 0} stroke="none" isAnimationActive={false}>
              {rows.map(row => <Cell key={row.key ?? 'none'} fill={row.color} />)}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <p className="px-6 text-[15px] font-bold leading-tight text-ink">{compact(total, unit)}</p>
          {centerLabel && <p className="text-[11px] text-ink-subtle">{centerLabel}</p>}
        </div>
      </div>
      <ul className="w-full min-w-0 space-y-2">
        {rows.map(row => (
          <li key={row.key ?? 'none'} className="flex items-center gap-2 text-[13px]">
            <span className="size-2.5 shrink-0 rounded-full" style={{ background: row.color }} />
            <span className="min-w-0 flex-1 truncate text-ink-muted">{row.name}</span>
            <span className="shrink-0 text-xs text-ink-subtle">{formatValue(row.value, unit)}</span>
            <span className="w-10 shrink-0 text-right font-semibold text-ink">{total ? Math.round((row.value / total) * 100) : 0}%</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * Столбцы по месяцам, сложенные из частей: заявки по источникам. rows —
 * [{ month, key, label, value }], серий не больше top — остальное в «Другие».
 */
export function StackedBars({ rows, top = 5, unit = 'count' }) {
  const totals = {}
  rows.forEach(r => { totals[r.key] = (totals[r.key] || 0) + r.value })
  const leaders = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, top).map(([key]) => key)
  const names = {}
  const byMonth = {}
  rows.forEach(r => {
    const key = leaders.includes(r.key) ? r.key : '__other'
    names[key] = key === '__other' ? t('Другие') : breakdownLabel(r)
    byMonth[r.month] = byMonth[r.month] || { date: r.month }
    byMonth[r.month][key] = (byMonth[r.month][key] || 0) + r.value
  })
  const keys = [...leaders, ...(names.__other ? ['__other'] : [])]
  const data = Object.values(byMonth).sort((a, b) => a.date.localeCompare(b.date))
  const tooltipRows = keys.map(key => ({ key, label: names[key], unit }))
  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--color-line)" />
            {xAxis('month')}
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={40} tickFormatter={v => formatAxis(v, unit)} />
            <Tooltip cursor={{ fill: 'var(--color-surface-muted)' }} content={<ChartTooltip granularity="month" rows={tooltipRows} />} />
            {keys.map((key, i) => (
              <Bar key={key} dataKey={key} stackId="s" fill={key === '__other' ? 'var(--color-ink-subtle)' : PALETTE[i % PALETTE.length]} maxBarSize={48} animationDuration={600} />
            ))}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
        {keys.map((key, i) => (
          <span key={key} className="flex items-center gap-1.5">
            <span className="size-2.5 rounded-sm" style={{ background: key === '__other' ? 'var(--color-ink-subtle)' : PALETTE[i % PALETTE.length] }} />
            {names[key]}
          </span>
        ))}
      </div>
    </div>
  )
}
