import { useState } from 'react'
import { ArrowRight, CalendarDays, CheckCircle2, ChevronLeft, ChevronRight, CloudOff, MapPin, RotateCcw, Send, UserRound, UsersRound } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Skeleton, Textarea } from '../../ui'
import { locale, t } from '../../i18n'
import portal, { portalError, usePortalData } from '../api'
import { useParent } from '../useParent'

const STATUS = {
  scheduled: { label: 'Запланировано', tone: 'info' },
  cancelled: { label: 'Отменено', tone: 'danger' },
  rescheduled: { label: 'Перенесено', tone: 'warning' },
  completed: { label: 'Проведено', tone: 'neutral' },
}

const KIND = {
  makeup: { label: 'Отработка', tone: 'brand', icon: RotateCcw },
  trial: { label: 'Пробное', tone: 'warning', icon: CalendarDays },
}

const CANCEL_REASONS = [
  ['illness', 'Болезнь'],
  ['family', 'Семейные обстоятельства'],
  ['other', 'Другое'],
]

function scheduleUrl(childId, period) {
  if (!childId) return null
  const query = new URLSearchParams({ date_from: period.from, date_to: period.to })
  return `children/${childId}/schedule/?${query}`
}

function makeupUrl(childId, attendanceId) {
  return childId && attendanceId ? `children/${childId}/makeups/${attendanceId}/` : null
}

function requestsUrl(childId) {
  return childId ? `children/${childId}/lesson-requests/` : null
}

function requestOptionsUrl(childId) {
  return childId ? `children/${childId}/lesson-request-options/` : null
}

function dayKey(value) {
  return value?.slice(0, 10) || ''
}

function isoDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function addDays(date, count) {
  const result = new Date(date)
  result.setDate(result.getDate() + count)
  return result
}

function periodFor(view, anchor) {
  if (view === 'month') {
    const from = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
    const to = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0)
    return { from: isoDate(from), to: isoDate(to), fromDate: from, toDate: to }
  }
  const weekday = anchor.getDay() || 7
  const from = addDays(anchor, 1 - weekday)
  const to = addDays(from, 6)
  return { from: isoDate(from), to: isoDate(to), fromDate: from, toDate: to }
}

function periodTitle(view, period) {
  if (view === 'month') {
    return new Intl.DateTimeFormat(locale, { month: 'long', year: 'numeric' }).format(period.fromDate)
  }
  const formatter = new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'short' })
  return `${formatter.format(period.fromDate)} – ${formatter.format(period.toDate)}`
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
  const [view, setView] = useState('week')
  const [anchor, setAnchor] = useState(() => new Date())
  const makeupId = searchParams.get('makeup')
  const period = periodFor(view, anchor)
  const schedule = usePortalData(scheduleUrl(child?.id, period), {
    refreshInterval: 10_000,
    refreshOnFocus: true,
  })
  const makeup = usePortalData(makeupUrl(child?.id, makeupId))
  const requests = usePortalData(requestsUrl(child?.id), {
    refreshInterval: 10_000,
    refreshOnFocus: true,
  })
  const options = usePortalData(requestOptionsUrl(child?.id))
  const [requestDialog, setRequestDialog] = useState(null)

  if (!child) {
    return <Card><EmptyState icon={CalendarDays} title={t('Ребёнок не выбран')} /></Card>
  }

  if (makeupId) {
    return <MakeupBooking child={child} attendanceId={makeupId} options={makeup} />
  }

  const lessons = schedule.data?.results || []
  const next = lessons.find(row => row.status === 'scheduled' && new Date(row.starts_at_local) > new Date())
  const rest = next ? lessons.filter(row => row.id !== next.id) : []
  const periodRows = next ? rest : lessons
  const grouped = periodRows.reduce((result, row) => {
    const key = dayKey(row.starts_at_local)
    if (!result[key]) result[key] = []
    result[key].push(row)
    return result
  }, {})

  function movePeriod(direction) {
    setAnchor(current => view === 'month'
      ? new Date(current.getFullYear(), current.getMonth() + direction, 1)
      : addDays(current, direction * 7))
  }

  function changeView(nextView) {
    setView(nextView)
    setAnchor(new Date())
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title={t('Расписание')}
        description={t('Ближайшие занятия ребёнка: время, место и преподаватель.')}
        actions={(
          <div className="flex flex-wrap gap-2">
            <Button to="/parent/attendance">{t('История посещений')}</Button>
            <Button variant="primary" onClick={() => setRequestDialog({ type: 'enroll' })}>{t('Запросить запись')}</Button>
          </div>
        )}
      />

      <SchedulePeriodControls
        view={view}
        title={periodTitle(view, period)}
        onView={changeView}
        onPrevious={() => movePeriod(-1)}
        onNext={() => movePeriod(1)}
        onToday={() => setAnchor(new Date())}
      />

      <RequestHistory data={requests.data} loading={requests.loading} />

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
          {next && <section aria-labelledby="next-lesson-title">
            <div className="mb-2 px-1">
              <h2 id="next-lesson-title" className="text-base font-bold text-ink">{t('Ближайшее занятие')}</h2>
            </div>
            <NextLesson row={next} onCancel={() => setRequestDialog({ type: 'cancel', row: next })} />
          </section>}

          {periodRows.length > 0 && (
            <section aria-labelledby="upcoming-lessons-title">
              <div className="mb-3 px-1">
                <h2 id="upcoming-lessons-title" className="text-base font-bold text-ink">{next ? t('Дальше по расписанию') : t('Занятия за период')}</h2>
                <p className="mt-0.5 text-[13px] text-ink-muted">{t('Прошедшие отметки и списания находятся в истории посещений.')}</p>
              </div>
              <div className="grid items-start gap-3 xl:grid-cols-2">
                {Object.entries(grouped).map(([date, rows]) => (
                  <DayCard key={date} date={date} rows={rows} onCancel={row => setRequestDialog({ type: 'cancel', row })} />
                ))}
              </div>
            </section>
          )}
        </>
      ) : (
        <Card>
          <EmptyState
            icon={CalendarDays}
            title={t('За выбранный период занятий нет')}
            description={t('Переключите неделю или месяц либо вернитесь к сегодняшней дате.')}
          />
        </Card>
      )}

      {requestDialog && (
        <LessonRequestModal
          child={child}
          request={requestDialog}
          options={options}
          onClose={() => setRequestDialog(null)}
          onCreated={() => {
            setRequestDialog(null)
            requests.reload()
          }}
        />
      )}
    </div>
  )
}

function MakeupBooking({ child, attendanceId, options }) {
  const [submitting, setSubmitting] = useState(null)
  const [error, setError] = useState('')
  const [booked, setBooked] = useState(null)
  const [comment, setComment] = useState('')

  async function book(row) {
    setSubmitting(row.id)
    setError('')
    try {
      await portal.post(makeupUrl(child.id, attendanceId), { lesson_id: row.id, comment })
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
            title={t('Запрос отправлен')}
            description={t('{name} — {date}, {start}–{end}. Администратор рассмотрит запрос. Место пока не забронировано.', {
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
        description={t('Выберите свободное занятие того же направления. Администратор подтвердит запись отдельно.')}
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
          <Field label={t('Комментарий')} hint={t('Необязательно. Администратор увидит его вместе с запросом.')}>
            {({ id }) => <Textarea id={id} value={comment} onChange={event => setComment(event.target.value)} maxLength={1000} rows={2} />}
          </Field>
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
                  {t('Отправить запрос')}
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

function SchedulePeriodControls({ view, title, onView, onPrevious, onNext, onToday }) {
  return (
    <Card padded={false} className="p-3 sm:p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex w-full rounded-lg bg-surface-muted p-1 sm:w-auto">
          {[
            ['week', 'Неделя'],
            ['month', 'Месяц'],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => onView(value)}
              className={`min-h-10 flex-1 rounded-md px-4 text-sm font-semibold transition-colors sm:flex-none ${view === value ? 'bg-surface text-brand-600 shadow-sm' : 'text-ink-muted'}`}
            >
              {t(label)}
            </button>
          ))}
        </div>
        <p className="order-first text-center text-sm font-bold capitalize text-ink sm:order-none sm:text-base">{title}</p>
        <div className="grid grid-cols-[44px_1fr_44px] gap-2 sm:flex">
          <Button type="button" aria-label={t('Предыдущий период')} onClick={onPrevious} className="justify-center px-0 sm:px-3">
            <ChevronLeft className="size-4" />
          </Button>
          <Button type="button" onClick={onToday} className="justify-center">{t('Сегодня')}</Button>
          <Button type="button" aria-label={t('Следующий период')} onClick={onNext} className="justify-center px-0 sm:px-3">
            <ChevronRight className="size-4" />
          </Button>
        </div>
      </div>
    </Card>
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

function NextLesson({ row, onCancel }) {
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
          {row.can_request_cancel && <Button className="mt-4" onClick={onCancel}>{t('Не сможем прийти')}</Button>}
        </div>
      </div>
    </Card>
  )
}

function DayCard({ date, rows, onCancel }) {
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
                {row.can_request_cancel && <Button className="mt-3" onClick={() => onCancel(row)}>{t('Не сможем прийти')}</Button>}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

const REQUEST_STATUS = {
  new: { label: 'Ожидает решения', tone: 'warning' },
  approved: { label: 'Одобрен', tone: 'success' },
  rejected: { label: 'Отклонён', tone: 'danger' },
}

function RequestHistory({ data, loading }) {
  const rows = data?.results || []
  if (loading && !data) return <Skeleton className="h-24" />
  if (!rows.length) return null
  return (
    <Card>
      <div className="mb-3">
        <h2 className="font-bold text-ink">{t('Мои запросы')}</h2>
        <p className="text-[13px] text-ink-muted">{t('Запрос не меняет расписание, пока администратор его не одобрит.')}</p>
      </div>
      <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {rows.slice(0, 6).map(row => {
          const state = REQUEST_STATUS[row.status] || REQUEST_STATUS.new
          return (
            <li key={row.id} className="rounded-lg border border-line bg-canvas p-3">
              <div className="flex items-start justify-between gap-2">
                <p className="font-semibold text-ink">{row.type === 'cancel' ? t('Отмена занятия') : row.kind === 'makeup' ? t('Запись на отработку') : t('Запись на занятие')}</p>
                <Badge tone={state.tone}>{t(state.label)}</Badge>
              </div>
              <p className="mt-1 text-[12.5px] text-ink-muted">{dateLabel(row.lesson.starts_at_local)} · {timeLabel(row.lesson.starts_at_local)} · {row.lesson.group_name}</p>
              {row.type === 'enroll' && row.spots_available_at_request != null && (
                <p className="mt-1 text-xs text-ink-subtle">{t('На момент запроса свободно: {count}', { count: row.spots_available_at_request })}</p>
              )}
              {row.type === 'cancel' && row.cancel_reason_display && (
                <p className="mt-1 text-xs text-ink-muted">{t('Причина: {reason}', { reason: t(row.cancel_reason_display) })}</p>
              )}
              {row.type === 'cancel' && row.notice_is_timely != null && (
                <p className={`mt-1 text-xs font-semibold ${row.will_be_charged ? 'text-warning-600' : 'text-success-600'}`}>
                  {row.notice_is_timely ? t('Предупреждение отправлено в срок.') : t('Предупреждение отправлено позже срока.')}{' '}
                  {row.will_be_charged ? t('Занятие спишется.') : t('Занятие не спишется.')}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function LessonRequestModal({ child, request, options, onClose, onCreated }) {
  const [selected, setSelected] = useState(request.row || null)
  const [comment, setComment] = useState('')
  const [cancelReason, setCancelReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const isCancel = request.type === 'cancel'
  const rows = options.data?.results || []

  async function submit() {
    if (!selected) return
    setSubmitting(true)
    setError('')
    try {
      await portal.post(requestsUrl(child.id), {
        type: request.type,
        lesson_id: selected.id,
        comment,
        ...(isCancel ? { cancel_reason: cancelReason } : {}),
      })
      onCreated()
    } catch (requestError) {
      setError(portalError(requestError, {
        offline: t('Нет связи. Проверьте интернет и попробуйте ещё раз.'),
        other: t('Не удалось отправить запрос.'),
      }))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size={isCancel ? 'md' : 'xl'}
      title={isCancel ? t('Не сможем прийти') : t('Запросить запись на занятие')}
      description={isCancel
        ? t('Сообщите причину. Администратор и преподаватель увидят предупреждение до занятия.')
        : t('Это запрос администратору. Расписание и число свободных мест пока не изменятся.')}
      footer={(
        <>
          <Button onClick={onClose}>{t('Закрыть')}</Button>
          <Button variant="primary" onClick={submit} disabled={!selected || (isCancel && !cancelReason)} loading={submitting}>
            <Send className="size-4" />{t('Отправить запрос')}
          </Button>
        </>
      )}
    >
      {!isCancel && (
        options.loading && !options.data ? <Skeleton className="h-48" /> : options.error ? <ErrorState onRetry={options.reload} /> : rows.length ? (
          <div className="grid gap-2 sm:grid-cols-2">
            {rows.map(row => (
              <button
                type="button"
                key={row.id}
                onClick={() => setSelected(row)}
                className={`rounded-lg border p-3 text-left transition-colors ${selected?.id === row.id ? 'border-brand-500 bg-brand-50' : 'border-line hover:border-brand-200'}`}
              >
                <div className="flex justify-between gap-2"><strong>{row.group_name}</strong><Badge tone="success">{t('Свободно: {count}', { count: row.spots_left })}</Badge></div>
                <p className="mt-1 text-sm text-ink-muted">{dateLabel(row.starts_at_local)} · {timeLabel(row.starts_at_local)}–{timeLabel(row.ends_at_local)}</p>
                <p className="text-xs text-ink-subtle">{[row.branch_name, row.room_name].filter(Boolean).join(' · ')}</p>
              </button>
            ))}
          </div>
        ) : <EmptyState icon={CalendarDays} title={t('Подходящих занятий пока нет')} description={t('Показываются только будущие занятия по направлению и возрасту ребёнка, где есть места.')} />
      )}
      {isCancel && selected && (
        <div className="space-y-4">
          <div className="rounded-lg border border-line bg-canvas p-3">
            <p className="font-semibold text-ink">{title(selected)}</p>
            <p className="text-sm text-ink-muted">{dateLabel(selected.starts_at_local)} · {timeLabel(selected.starts_at_local)}–{timeLabel(selected.ends_at_local)}</p>
          </div>
          <Field label={t('Причина пропуска')} required>
            {() => (
              <div className="grid gap-2 sm:grid-cols-3">
                {CANCEL_REASONS.map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setCancelReason(value)}
                    className={`min-h-12 rounded-lg border px-3 py-2 text-sm font-semibold transition-colors ${cancelReason === value ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line bg-surface text-ink hover:border-brand-200'}`}
                  >
                    {t(label)}
                  </button>
                ))}
              </div>
            )}
          </Field>
          <p className="rounded-lg bg-warning-50 px-3 py-2 text-[13px] text-warning-600">
            {t('После отправки система покажет, было ли предупреждение своевременным и спишется ли занятие по правилам центра.')}
          </p>
        </div>
      )}
      <Field label={t('Комментарий')} hint={t('Необязательно. Администратор увидит его вместе с запросом.')}>
        {({ id }) => <Textarea id={id} className="mt-3" value={comment} onChange={event => setComment(event.target.value)} maxLength={1000} rows={3} />}
      </Field>
      {error && <p role="alert" className="mt-3 rounded-lg bg-danger-50 px-3 py-2 text-sm font-semibold text-danger-600">{error}</p>}
    </Modal>
  )
}

function LessonBadges({ row }) {
  const special = KIND[row.enrollment_kind]
  const state = STATUS[row.status]
  return (
    <div className="flex flex-wrap gap-1.5">
      {special && <Badge tone={special.tone}>{t(special.label)}</Badge>}
      {row.rescheduled_from_starts_at_local && <Badge tone="info">{t('Новое время')}</Badge>}
      {state && row.status !== 'scheduled' && <Badge tone={state.tone}>{t(state.label)}</Badge>}
    </div>
  )
}

function LessonMeta({ row, className }) {
  const place = [row.branch_name, row.room_name].filter(Boolean).join(' · ')
  const cancellationReason = row.cancel_reason || (row.cancel_reason_category_display ? t(row.cancel_reason_category_display) : '')
  return (
    <div className={className}>
      {place && <span className="inline-flex items-center gap-1.5 text-ink-muted"><MapPin className="size-4 shrink-0" />{place}</span>}
      {row.branch_address && <span className="inline-flex items-center gap-1.5 text-ink-muted"><MapPin className="size-4 shrink-0" />{row.branch_address}</span>}
      {row.teacher_name && <span className="inline-flex items-center gap-1.5 text-ink-muted"><UserRound className="size-4 shrink-0" />{row.teacher_name}</span>}
      {row.status === 'cancelled' && cancellationReason && <p className="col-span-full font-semibold text-danger-600">{t('Причина отмены: {reason}', { reason: cancellationReason })}</p>}
      {row.status === 'rescheduled' && cancellationReason && <p className="col-span-full font-semibold text-warning-600">{t('Причина переноса: {reason}', { reason: cancellationReason })}</p>}
      {row.status === 'rescheduled' && row.rescheduled_to && (
        <p className="col-span-full inline-flex items-center gap-1.5 font-semibold text-warning-600">
          <ArrowRight className="size-4 shrink-0" />
          {t('Новое время: {date}, {time}', {
            date: dateLabel(row.rescheduled_to.starts_at_local),
            time: timeLabel(row.rescheduled_to.starts_at_local),
          })}
        </p>
      )}
      {row.rescheduled_from_starts_at_local && (
        <p className="col-span-full text-info-600">
          {t('Перенесено с {date}, {time}', {
            date: dateLabel(row.rescheduled_from_starts_at_local),
            time: timeLabel(row.rescheduled_from_starts_at_local),
          })}
        </p>
      )}
    </div>
  )
}
