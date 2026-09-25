import { cn } from '../../ui'

/** «Занято 8 из 12» с полосой: красная — мест нет, жёлтая — недобор. */
export default function FillBar({ group, className }) {
  const percent = Math.min(100, group.fill_percent ?? 0)
  const full = group.members_count >= group.capacity
  const color = full ? 'bg-danger-600' : group.is_underfilled ? 'bg-warning-600' : 'bg-success-600'
  return (
    <div className={className}>
      <div className="mb-1.5 flex items-baseline justify-between text-[13px]">
        <span className="text-ink-muted">Занято</span>
        <span className="font-semibold text-ink">{group.members_count} <span className="font-normal text-ink-subtle">из {group.capacity}</span></span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-muted">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${Math.max(percent, 3)}%` }} />
      </div>
    </div>
  )
}
