import { MessageSquareText } from 'lucide-react'
import { t } from '../../i18n'

/** Счётчик комментариев у задачи в списке (TRU-184) — только если они есть. */
export default function CommentsCount({ count, onClick }) {
  if (!count) return null
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-full bg-surface-muted px-2 py-0.5 text-xs font-semibold text-ink-muted hover:text-brand-600"
      aria-label={t('Комментариев: {n}', { n: count })}
    >
      <MessageSquareText className="size-3.5" />
      {count}
    </button>
  )
}
