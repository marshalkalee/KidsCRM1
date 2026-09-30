import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { t } from '../../i18n'
import { formatAxis, formatBucket, formatValue } from './format'
import { PALETTE } from './meta'

/**
 * Графики отчётов (TRU-113) на recharts — одна палитра, одни оси и одна
 * подсказка на все отчёты. series — как приходит из API: [{date, value}];
 * granularity — period.granularity (day / week / month).
 */

const AXIS = { fontSize: 11, fill: 'var(--color-ink-subtle)' }

function toRows(series) {
  return (series || []).map(point => ({ date: point.date, value: point.value == null ? null : Number(point.value) }))
}

function ChartTooltip({ active, payload, label, unit, granularity }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-pop">
      <p className="text-ink-subtle">{formatBucket(label, granularity)}</p>
      <p className="mt-0.5 text-sm font-bold text-ink">{formatValue(payload[0].value, unit)}</p>
    </div>
  )
}

function axes(unit, granularity) {
  return [
    <CartesianGrid key="grid" vertical={false} stroke="var(--color-line)" />,
    <XAxis
      key="x"
      dataKey="date"
      tick={AXIS}
      tickLine={false}
      axisLine={false}
      minTickGap={16}
      tickFormatter={value => formatBucket(value, granularity)}
    />,
    <YAxis key="y" tick={AXIS} tickLine={false} axisLine={false} width={56} tickFormatter={value => formatAxis(value, unit)} />,
    <Tooltip key="tip" cursor={{ fill: 'var(--color-surface-muted)' }} content={<ChartTooltip unit={unit} granularity={granularity} />} />,
  ]
}

/** Линия с заливкой — динамика: выручка, доля посещений, долг по снимкам. */
export function TrendChart({ series, unit, granularity, color = PALETTE[0] }) {
  const gradient = `trend-${color.replace(/\W/g, '')}`
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={toRows(series)} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.22} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {axes(unit, granularity)}
        <Area type="monotone" dataKey="value" name={t('Значение')} stroke={color} strokeWidth={2} fill={`url(#${gradient})`} connectNulls dot={false} activeDot={{ r: 4 }} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/** Столбцы — количество по дням/неделям/месяцам: посещения, заявки, оплаты. */
export function BarsChart({ series, unit, granularity, color = PALETTE[0] }) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={toRows(series)} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        {axes(unit, granularity)}
        <Bar dataKey="value" name={t('Значение')} fill={color} radius={[4, 4, 0, 0]} maxBarSize={36} />
      </BarChart>
    </ResponsiveContainer>
  )
}
