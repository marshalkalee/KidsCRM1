import { t } from '../../i18n'
import { formatValue } from './format'
import { PALETTE } from './meta'

/**
 * Воронка (TRU-113, для конверсии TRU-115 и продлений TRU-126):
 * этапы сверху вниз, ширина — доля от первого этапа, между этапами —
 * конверсия шага. На телефоне читается так же — это не график, а полосы.
 *
 * stages: [{ label, value }]
 */
export function FunnelChart({ stages }) {
  const first = Number(stages[0]?.value) || 0
  return (
    <ol className="flex flex-col gap-1.5">
      {stages.map((stage, index) => {
        const value = Number(stage.value) || 0
        const share = first ? value / first : 0
        const previous = index ? Number(stages[index - 1].value) || 0 : null
        const step = previous ? Math.round((value / previous) * 100) : null
        return (
          <li key={stage.label}>
            {index > 0 && (
              <p className="py-0.5 pl-1 text-[11px] text-ink-subtle">
                ↓ {step == null ? '—' : t('{percent}% перешли дальше', { percent: step })}
              </p>
            )}
            <div className="flex items-center gap-3">
              <div className="relative h-9 flex-1 overflow-hidden rounded-md bg-surface-muted">
                <div
                  className="absolute inset-y-0 left-0 rounded-md"
                  style={{ width: `${Math.max(share * 100, value ? 2 : 0)}%`, background: PALETTE[0], opacity: 1 - index * 0.12 }}
                />
                <span className="relative flex h-full items-center px-3 text-[13px] font-semibold text-ink">{stage.label}</span>
              </div>
              <div className="w-24 shrink-0 text-right">
                <p className="text-sm font-bold text-ink">{formatValue(value, 'count')}</p>
                <p className="text-[11px] text-ink-subtle">{first ? `${Math.round(share * 100)}%` : '—'}</p>
              </div>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
