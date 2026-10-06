import { useEffect, useRef } from 'react'
import { BookOpen, CalendarDays, MessageSquareText, UserRound, Users } from 'lucide-react'
import { Badge, Card, CardHeader, EmptyState, ErrorState, Skeleton, formatDate } from '../../ui'
import { locale, t } from '../../i18n'
import portal, { usePortalData } from '../api'
import { useParent } from '../useParent'

function noteDate(value) {
  return new Date(value).toLocaleDateString(locale, { day: 'numeric', month: 'long', year: 'numeric' })
}

function lessonDate(value) {
  const date = new Date(value)
  return `${date.toLocaleDateString(locale, { day: 'numeric', month: 'long' })}, ${date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })}`
}

export default function ParentNotes() {
  const { child } = useParent()
  const notes = usePortalData(child && `children/${child.id}/notes/`, {
    refreshInterval: 10_000,
    refreshOnFocus: true,
  })
  const reloadNotes = notes.reload
  const marked = useRef(new Set())

  useEffect(() => {
    const unread = (notes.data?.results || []).filter(row => !row.read && !marked.current.has(row.id))
    if (!child || !unread.length) return
    unread.forEach(row => marked.current.add(row.id))
    Promise.all(unread.map(row => portal.post(`children/${child.id}/notes/${row.id}/read/`)))
      .then(() => {
        reloadNotes()
        window.dispatchEvent(new Event('kc-parent-notes-read'))
      })
      .catch(() => {})
  }, [child, notes.data, reloadNotes])

  if (!child) return null
  if (!notes.data && notes.loading) return <div className="space-y-3"><Skeleton className="h-28" /><Skeleton className="h-40" /><Skeleton className="h-40" /></div>
  if (!notes.data) return <Card><ErrorState onRetry={notes.reload} /></Card>

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={t('Заметки и домашние задания')}
          description={t('Рекомендации преподавателя после занятий — общие для группы и лично для ребёнка.')}
        />
        <p className="rounded-lg bg-surface-muted px-3 py-2 text-[13px] text-ink-muted">
          {t('Ответить здесь нельзя. Если нужно уточнение, напишите администратору центра в WhatsApp.')}
        </p>
      </Card>

      {notes.data.results.length === 0 ? (
        <Card><EmptyState icon={MessageSquareText} title={t('Заметок пока нет')} description={t('Когда преподаватель оставит рекомендацию или домашнее задание, оно появится здесь.')} /></Card>
      ) : (
        <div className="grid items-start gap-3 xl:grid-cols-2">
          {notes.data.results.map(row => <NoteCard key={row.id} row={row} />)}
        </div>
      )}
    </div>
  )
}

function NoteCard({ row }) {
  const personal = row.scope === 'child'
  const homework = row.kind === 'homework'
  return (
    <Card className={row.read ? '' : 'border-brand-300 shadow-[0_0_0_1px_rgba(239,90,112,0.08)]'}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={personal ? 'warning' : 'info'}>
          {personal ? <UserRound className="size-3.5" /> : <Users className="size-3.5" />}
          {personal ? t('Лично для ребёнка') : t('Для всей группы')}
        </Badge>
        <Badge tone={homework ? 'brand' : 'neutral'}>
          {homework && <BookOpen className="size-3.5" />}
          {homework ? t('Домашнее задание') : t('Заметка')}
        </Badge>
        {!row.read && <span className="ml-auto rounded-full bg-brand-600 px-2 py-0.5 text-[10px] font-bold text-white">{t('новое')}</span>}
      </div>

      <p className="mt-3 whitespace-pre-line text-[15px] leading-relaxed text-ink">{row.body}</p>

      <div className="mt-4 space-y-1.5 border-t border-line pt-3 text-[12.5px] text-ink-muted">
        <p className="flex items-center gap-1.5"><CalendarDays className="size-4 shrink-0" />{row.lesson.name} · {lessonDate(row.lesson.starts_at)}</p>
        <p className="flex items-center gap-1.5"><UserRound className="size-4 shrink-0" />{row.lesson.teacher}</p>
        <p>{t('Добавлено {date}', { date: noteDate(row.created_at) })}</p>
        {homework && row.valid_until && <p className="font-semibold text-brand-700">{t('Актуально до {date}', { date: formatDate(row.valid_until) })}</p>}
      </div>
    </Card>
  )
}
