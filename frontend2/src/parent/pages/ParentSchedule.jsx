import { useState } from 'react'
import { CalendarDays, CheckCircle2, CloudOff, MapPin, RotateCcw, UserRound, UsersRound } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Skeleton } from '../../ui'
import { locale, t } from '../../i18n'
import portal, { portalError, usePortalData } from '../api'
import { useParent } from '../useParent'

const STATUS = {
  scheduled: { label: 'Запланировано', tone: 'info' },
  cancelled: { label: 'Отменено', tone: 'danger' },
}

const KIND = {
  makeup: { label: 'Отработка', tone: 'brand', icon: RotateCcw },
  trial: { label: 'Пробное', tone: 'warning', icon: CalendarDays },
}

function scheduleUrl(childId) {
  return childId ? `children/${childId}/schedule/` : null
}

function makeupUrl(childId, attendanceId) {
  return childId && attendanceId ? `children/${childId}/makeups/${attendanceId}/` : null
}

function dayKey(value) {
  return value?.slice(0, 10) || ''
}

function dateLabel(value, long = false) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale, long
    ? { weekday: 'long', day: 'numeric', month: 'long' }
    : { weekday: 'short', day: 'numeric', month: 'short' }).format(new Date(value))
}

function timeLabel(value) {
  return value?.slice(11, 16) || '—'
}

function title(row) {
  return row.group_name || row.direction_name || t('Индивидуальное занятие')
}

export default function ParentSchedule() {
  const { child } = useParent()
  const [searchParams] = useSearchParams()
  const makeupId = searchParams.get('makeup')
  const schedule = usePortalData(scheduleUrl(child?.id))
  const makeup = usePortalData(makeupUrl(child?.id, makeupId))

  if (!child) {
    return <Card><EmptyState icon={CalendarDays} title={t('Ребёнок не выбран')} /></Card>
  }

  if (makeupId) {
    return <MakeupBooking child={child} attendanceId={makeupId} options={makeup} />
  }

  const lessons = schedule.data?.results || []
  const next = lessons.find(row => row.status !== 'cancelled') || lessons[0]
  const rest = next ? lessons.filter(row => row.id !== next.id) : []
  const grouped = rest.reduce((result, row) => {
    const key = dayKey(row.starts_at_local)
    if (!result[key]) result[key] = []
    result[key].push(row)
    return result
  }, {})

  return (
    <div className="space-y-4">
      <PageHeader
        title={t('Расписание')}
        description={t('Ближайшие занятия ребёнка: время, место и преподаватель.')}
      />

      {schedule.stale && (
        <p className="flex items-center gap-2 rounded-lg bg-warning-50 px-3 py-2 text-[13px] text-warning-600">
          <CloudOff className="size-4 shrink-0" />
          {t('Показаны сохранённые данные. Они могут быть неактуальны.')}
        </p>
      )}

      {schedule.loading && !schedule.data ? (
        <LoadingState />
      ) : schedule.error ? (
        <Card><ErrorState onRetry={schedule.reload} /></Card>
      ) : lessons.length ? (
        <>
          <section aria-labelledby="next-lesson-title">
            <div className="mb-2 px-1">
              <h2 id="next-lesson-title" className="text-base font-bold text-ink">{t('Ближайшее занятие')}</h2>
            </div>
            <NextLesson row={next} />
          </section>

          {rest.length > 0 && (
            <section aria-labelledby="upcoming-lessons-title">
              <div className="mb-3 px-1">
                <h2 id="upcoming-lessons-title" className="text-base font-bold text-ink">{t('Дальше по расписанию')}</h2>
                <p className="mt-0.5 text-[13px] text-ink-muted">{t('Все запланированные занятия на ближайшие два месяца.')}</p>
              </div>
              <div className="grid items-start gap-3 xl:grid-cols-2">
                {Object.entries(grouped).map(([date, rows]) => (
                  <DayCard key={date} date={date} rows={rows} />
                ))}
              </div>
            </section>
          )}
        </>
      ) : (
        <Card>
          <EmptyState
            icon={CalendarDays}
            title={t('Ближайших занятий пока нет')}
            description={t('Когда центр добавит занятия в расписание, они появятся здесь автоматически.')}
          />
        </Card>
      )}
    </div>
  )
}

function MakeupBooking({ child, attendanceId, options }) {
  const [submitting, setSubmitting] = useState(null)
  const [error, setError] = useState('')
  const [booked, setBooked] = useState(null)

  async function book(row) {
    setSubmitting(row.id)
    setError('')
    try {
      await portal.post(makeupUrl(child.id, attendanceId), { lesson_id: row.id })
      setBooked(row)
    } catch (requestError) {
      setError(portalError(requestError, {
        offline: t('Нет связи. Проверьте интернет и попробуйте ещё раз.'),
        other: t('Не удалось записаться на это занятие.'),
      }))
    } finally {
      setSubmitting(null)
    }
  }

  if (booked) {
    return (
      <div className="space-y-4">
        <PageHeader title={t('Запись на отработку')} back={{ to: '/parent/attendance', label: t('Посещения') }} />
        <Card>
          <EmptyState
            icon={CheckCircle2}
            title={t('Ребёнок записан на отработку')}
            description={t('{name} — {date}, {start}–{end}. Занятие уже добавлено в расписание.', {
              name: booked.group_name,
              date: dateLabel(booked.starts_at_local),
              start: timeLabel(booked.starts_at_local),
              end: timeLabel(booked.ends_at_local),
            })}
            action={(
              <div className="flex flex-wrap justify-center gap-2">
                <Button to="/parent/schedule" variant="primary">{t('Открыть расписание')}</Button>
                <Button to="/parent/attendance">{t('Вернуться к посещениям')}</Button>
              </div>
            )}
          />
        </Card>
      </div>
    )
  }

  const rows = options.data?.results || []
  return (
    <div className="space-y-4">
      <PageHeader
        title={t('Запись на отработку')}
        description={t('Выберите свободное занятие того же направления. Новое занятие с абонемента не спишется.')}
        back={{ to: '/parent/attendance', label: t('Посещения') }}
      />

      {options.loading && !options.data ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map(item => <Skeleton key={item} className="h-56" />)}
        </div>
      ) : options.error ? (
        <Card><ErrorState onRetry={options.reload} /></Card>
      ) : rows.length ? (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <p className="text-sm font-semibold text-ink">{t('Подходящие занятия')}</p>
            <Badge tone="info">{t('Отработка действует до {date}', { date: options.data.expires_on })}</Badge>
          </div>
          {error && <p role="alert" className="rounded-lg bg-danger-50 px-4 py-3 text-sm font-semibold text-danger-600">{error}</p>}
          <div className="grid items-stretch gap-3 md:grid-cols-2 xl:grid-cols-3">
            {rows.map(row => (
              <Card key={row.id} className="flex min-h-56 flex-col">
                <div className="flex items-start justify-between gap-3">
                  <span className="flex size-11 items-center justify-center rounded-xl bg-brand-50 text-brand-600">
                    <CalendarDays className="size-5" />
                  </span>
                  <Badge tone="success">{t('Свободно: {count}', { count: row.spots_left })}</Badge>
                </div>
                <div className="mt-4">
                  <p className="font-bold capitalize text-ink">{dateLabel(row.starts_at_local, true)}</p>
                  <p className="mt-1 text-xl font-bold text-ink">{timeLabel(row.starts_at_local)}–{timeLabel(row.ends_at_local)}</p>
                  <p className="mt-2 font-semibold text-ink">{row.group_name}</p>
                  <div className="mt-2 space-y-1 text-[12.5px] text-ink-muted">
                    <p className="flex items-center gap-1.5"><MapPin className="size-4" />{[row.branch_name, row.room_name].filter(Boolean).join(' · ')}</p>
                    {row.teacher_name && <p className="flex items-center gap-1.5"><UserRound className="size-4" />{row.teacher_name}</p>}
                    <p className="flex items-center gap-1.5"><UsersRound className="size-4" />{row.current_count}/{row.capacity}</p>
                  </div>
                </div>
                <Button
                  type="button"
                  variant="primary"
                  className="mt-auto w-full justify-center"
                  loading={submitting === row.id}
                  disabled={Boolean(submitting)}
                  onClick={() => book(row)}
                >
                  {t('Записаться на это занятие')}
                </Button>
              </Card>
            ))}
          </div>
        </>
      ) : (
        <Card>
          <EmptyState
            icon={CalendarDays}
            title={t('Подходящих занятий пока нет')}
            description={t('Попробуйте вернуться позже или свяжитесь с администратором центра.')}
          />
        </Card>
      )}
    </div>
  )
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-44" />
      <div className="grid gap-3 xl:grid-cols-2">
        <Skeleton className="h-48" />
        <Skeleton className="h-48" />
      </div>
    </div>
  )
}

function NextLesson({ row }) {
  return (
    <Card className="overflow-hidden border-brand-200 bg-gradient-to-br from-surface via-surface to-brand-50/70 p-0">
      <div className="grid md:grid-cols-[220px_minmax(0,1fr)]">
        <div className="flex flex-col justify-center bg-brand-gradient px-5 py-6 text-white sm:px-7">
          <p className="text-sm font-semibold text-white/80">{dateLabel(row.starts_at_local, true)}</p>
          <p className="mt-2 text-3xl font-bold tracking-tight">
            {timeLabel(row.starts_at_local)}–{timeLabel(row.ends_at_local)}
          </p>
        </div>
        <div className="p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h3 className="text-xl font-bold text-ink">{title(row)}</h3>
              {row.group_name && row.direction_name && (
                <p className="mt-0.5 text-sm text-ink-muted">{row.direction_name}</p>
              )}
            </div>
            <LessonBadges row={row} />
          </div>
          <LessonMeta row={row} className="mt-5 grid gap-2 text-sm sm:grid-cols-2" />
        </div>
      </div>
    </Card>
  )
}

function DayCard({ date, rows }) {
  return (
    <Card className="p-0" padded={false}>
      <div className="border-b border-line px-4 py-3 sm:px-5">
        <h3 className="font-bold capitalize text-ink">{dateLabel(`${date}T12:00:00`)}</h3>
      </div>
      <ul className="divide-y divide-line">
        {rows.map(row => (
          <li key={row.id} className="p-4 sm:p-5">
            <div className="flex items-start gap-4">
              <div className="w-[70px] shrink-0">
                <p className="text-base font-bold text-ink">{timeLabel(row.starts_at_local)}</p>
                <p className="text-xs text-ink-subtle">{t('до {time}', { time: timeLabel(row.ends_at_local) })}</p>
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-bold text-ink">{title(row)}</p>
                    {row.group_name && row.direction_name && <p className="text-[12.5px] text-ink-muted">{row.direction_name}</p>}
                  </div>
                  <LessonBadges row={row} />
                </div>
                <LessonMeta row={row} className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-[12.5px]" />
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function LessonBadges({ row }) {
  const special = KIND[row.enrollment_kind]
  const state = STATUS[row.status]
  return (
    <div className="flex flex-wrap gap-1.5">
      {special && <Badge tone={special.tone}>{t(special.label)}</Badge>}
      {state && row.status === 'cancelled' && <Badge tone={state.tone}>{t(state.label)}</Badge>}
    </div>
  )
}

function LessonMeta({ row, className }) {
  const place = [row.branch_name, row.room_name].filter(Boolean).join(' · ')
  return (
    <div className={className}>
      {place && <span className="inline-flex items-center gap-1.5 text-ink-muted"><MapPin className="size-4 shrink-0" />{place}</span>}
      {row.teacher_name && <span className="inline-flex items-center gap-1.5 text-ink-muted"><UserRound className="size-4 shrink-0" />{row.teacher_name}</span>}
      {row.status === 'cancelled' && row.cancel_reason && <p className="col-span-full text-danger-600">{t('Причина отмены: {reason}', { reason: row.cancel_reason })}</p>}
    </div>
  )
}
