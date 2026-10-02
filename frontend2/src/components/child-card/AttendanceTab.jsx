import { useCallback, useEffect, useState } from 'react'
import {
  CalendarClock, CalendarPlus, CheckCircle2, Clock, History, MapPin, RotateCcw, Users, XCircle,
} from 'lucide-react'
import api from '../../api/axios'
import {
  Badge, Button, Card, CardHeader, DataTable, DateInput, EmptyState, ErrorState, Field, Modal,
  Skeleton, apiErrorMessage, formatDateTime, useConfirm, useToast,
} from '../../ui'
import { plural, t } from '../../i18n'

const PAGE_SIZE = 50

const STATUS_META = {
  present: { label: 'Посещено', tone: 'success' },
  absent: { label: 'Пропущено', tone: 'danger' },
  makeup: { label: 'Отработка', tone: 'brand' },
}

function dateIso(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function defaultPeriod() {
  const today = new Date()
  return {
    dateFrom: dateIso(new Date(today.getFullYear(), today.getMonth() - 2, 1)),
    dateTo: dateIso(today),
  }
}

/**
 * Вкладка «Посещения» (TRU-55): история и списания за период, сводка и
 * доступные отработки. Подключается только через реестр tabs.js (TRU-82).
 */
export default function AttendanceTab({ child, onCountChange }) {
  const initialPeriod = defaultPeriod()
  const toast = useToast()
  const confirm = useConfirm()
  const [draftPeriod, setDraftPeriod] = useState(initialPeriod)
  const [period, setPeriod] = useState(initialPeriod)
  const [periodError, setPeriodError] = useState('')
  const [page, setPage] = useState(1)
  const [history, setHistory] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(true)
  const [historyError, setHistoryError] = useState(false)
  const [makeups, setMakeups] = useState(null)
  const [makeupsError, setMakeupsError] = useState(false)
  const [pickingFor, setPickingFor] = useState(null)

  const loadHistory = useCallback(() => {
    api.get('attendance/history/', {
      params: {
        child: child.id,
        date_from: period.dateFrom || undefined,
        date_to: period.dateTo || undefined,
        page,
      },
    })
      .then(response => {
        setHistory({
          rows: response.data.results,
          total: response.data.count ?? response.data.results.length,
          summary: response.data.summary,
        })
        setHistoryError(false)
      })
      .catch(() => setHistoryError(true))
      .finally(() => setHistoryLoading(false))
  }, [child.id, page, period.dateFrom, period.dateTo])

  const loadMakeups = useCallback(() => {
    api.get('attendance/available-makeups/', { params: { child: child.id } })
      .then(response => {
        setMakeups(response.data.results)
        setMakeupsError(false)
        onCountChange?.(response.data.results.length)
      })
      .catch(() => setMakeupsError(true))
  }, [child.id, onCountChange])

  useEffect(() => { loadHistory() }, [loadHistory])
  useEffect(() => { loadMakeups() }, [loadMakeups])

  function startHistoryLoad() {
    setHistoryLoading(true)
    setHistoryError(false)
  }

  function applyPeriod(event) {
    event.preventDefault()
    if (draftPeriod.dateFrom && draftPeriod.dateTo && draftPeriod.dateFrom > draftPeriod.dateTo) {
      setPeriodError(t('Конец периода не может быть раньше начала.'))
      return
    }
    setPeriodError('')
    startHistoryLoad()
    if (page === 1 && period.dateFrom === draftPeriod.dateFrom && period.dateTo === draftPeriod.dateTo) {
      loadHistory()
      return
    }
    setPage(1)
    setPeriod({ ...draftPeriod })
  }

  function showAllHistory() {
    const all = { dateFrom: '', dateTo: '' }
    setDraftPeriod(all)
    setPeriodError('')
    startHistoryLoad()
    if (page === 1 && !period.dateFrom && !period.dateTo) {
      loadHistory()
      return
    }
    setPage(1)
    setPeriod(all)
  }

  function retryHistory() {
    startHistoryLoad()
    loadHistory()
  }

  function changePage(nextPage) {
    startHistoryLoad()
    setPage(nextPage)
  }

  async function enroll(row, candidateLessonId, confirmCapacity = false) {
    try {
      await api.post('schedule/enrollments/', {
        lesson: candidateLessonId,
        child: child.id,
        kind: 'makeup',
        source_attendance: row.attendance_id,
        confirm_capacity: confirmCapacity,
      })
      toast.success(t('Записан(а) на отработку'))
      setPickingFor(null)
      loadMakeups()
    } catch (error) {
      if (error.response?.status === 409) {
        const ok = await confirm({
          title: t('Мест нет'),
          message: t('Вместимость группы уже заполнена ({current}/{capacity}). Записать всё равно?', {
            current: error.response.data.current_count,
            capacity: error.response.data.capacity,
          }),
          confirmText: t('Записать'),
        })
        if (ok) return enroll(row, candidateLessonId, true)
        return
      }
      toast.error(apiErrorMessage(error))
    }
  }

  const columns = [
    {
      key: 'date',
      header: t('Дата и время'),
      primary: true,
      render: row => (
        <div>
          <span className="font-semibold">{formatDateTime(row.starts_at_local)}</span>
          {row.is_retroactive_edit && (
            <span className="mt-1 flex items-center gap-1 text-[11px] font-semibold text-info-600">
              <History className="size-3" /> {t('Изменено задним числом')}
            </span>
          )}
        </div>
      ),
    },
    {
      key: 'lesson',
      header: t('Занятие'),
      render: row => (
        <div>
          <span className="font-medium">{row.lesson_name}</span>
          {row.teacher_name && <p className="text-xs text-ink-subtle">{row.teacher_name}</p>}
        </div>
      ),
    },
    {
      key: 'group',
      header: t('Группа'),
      render: row => (
        <div>
          <span>{row.group_name || t('Индивидуальное')}</span>
          {row.branch_name && <p className="text-xs text-ink-subtle">{row.branch_name}</p>}
        </div>
      ),
    },
    {
      key: 'status',
      header: t('Статус'),
      mobileAside: true,
      render: row => {
        const meta = STATUS_META[row.status] || { label: row.status_display, tone: 'neutral' }
        return <Badge tone={meta.tone}>{t(meta.label)}</Badge>
      },
    },
    {
      key: 'reason',
      header: t('Причина пропуска'),
      render: row => t(row.absence_reason_display) || '—',
      mobileRender: row => t(row.absence_reason_display) || null,
    },
    {
      key: 'consumption',
      header: t('Абонемент'),
      render: row => (
        <div title={t(row.consumption_display)}>
          <Badge tone={row.consumed_from_subscription ? 'success' : 'neutral'}>
            {row.consumed_from_subscription ? t('Списано') : t('Не списано')}
          </Badge>
          {!row.consumed_from_subscription && row.consume_outcome && (
            <p className="mt-1 max-w-48 text-xs text-ink-subtle">{t(row.consumption_display)}</p>
          )}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t('История посещений')}
          description={t('Отметки и фактические списания совпадают с журналом занятий.')}
        />
        <form onSubmit={applyPeriod} className="flex flex-col gap-3 sm:flex-row sm:items-end">
          <Field label={t('С даты')} error={periodError} className="sm:w-48">
            {({ id, invalid }) => (
              <DateInput
                id={id}
                value={draftPeriod.dateFrom}
                onChange={value => setDraftPeriod(current => ({ ...current, dateFrom: value }))}
                invalid={invalid}
                max={draftPeriod.dateTo || dateIso(new Date())}
              />
            )}
          </Field>
          <Field label={t('По дату')} className="sm:w-48">
            {({ id }) => (
              <DateInput
                id={id}
                value={draftPeriod.dateTo}
                onChange={value => setDraftPeriod(current => ({ ...current, dateTo: value }))}
                min={draftPeriod.dateFrom || undefined}
                max={dateIso(new Date())}
              />
            )}
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={historyLoading}>{t('Показать')}</Button>
            <Button type="button" variant="ghost" onClick={showAllHistory}>{t('За всё время')}</Button>
          </div>
        </form>
      </Card>

      {!history && historyLoading && <HistorySkeleton />}
      {historyError && <Card><ErrorState onRetry={retryHistory} /></Card>}
      {history && !historyError && (
        <>
          <Summary summary={history.summary} loading={historyLoading} />
          <DataTable
            columns={columns}
            rows={history.rows}
            loading={historyLoading}
            pagination={{ page, pageSize: PAGE_SIZE, total: history.total }}
            onPageChange={changePage}
            empty={(
              <EmptyState
                icon={CalendarClock}
                title={t('За этот период отметок нет')}
                description={t('Выберите другой период или проверьте журнал занятий.')}
              />
            )}
          />
        </>
      )}

      <Card>
        <CardHeader
          title={t('Доступные отработки')}
          description={t('Пропуски, которые ещё можно отработать.')}
          actions={makeups && <Badge tone={makeups.length ? 'warning' : 'neutral'}>{makeups.length}</Badge>}
        />
        {makeupsError && <ErrorState onRetry={loadMakeups} />}
        {!makeupsError && !makeups && <Skeleton className="h-16" />}
        {!makeupsError && makeups && makeups.length === 0 && (
          <p className="flex items-center gap-2 rounded-lg bg-surface-muted px-4 py-3 text-sm text-ink-muted">
            <CalendarClock className="size-4 shrink-0" />
            {t('Пропусков для отработки нет.')}
          </p>
        )}
        {!makeupsError && makeups && makeups.length > 0 && (
          <ul className="divide-y divide-line">
            {makeups.map(row => (
              <li key={row.attendance_id} className="flex flex-col gap-3 py-3 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{row.group_name || t('Индивидуальное занятие')}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-muted">
                    <span className="inline-flex items-center gap-1"><Clock className="size-3.5" />{formatDateTime(row.starts_at_local)}</span>
                    {row.room_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" />{row.room_name}</span>}
                    {row.absence_reason_display && <span>{t('Причина:')} {t(row.absence_reason_display)}</span>}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-3 sm:shrink-0 sm:justify-end">
                  <Badge tone={row.days_left <= 3 ? 'warning' : 'neutral'}>
                    {t('до')} {formatShortDate(row.expires_on)} · {row.days_left} {pluralDays(row.days_left)}
                  </Badge>
                  <Button variant="primary" size="sm" icon={CalendarPlus} onClick={() => setPickingFor(row)}>
                    {t('Отработать')}
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {pickingFor && (
        <MakeupCandidatesModal
          row={pickingFor}
          onClose={() => setPickingFor(null)}
          onPick={lessonId => enroll(pickingFor, lessonId)}
        />
      )}
    </div>
  )
}

function Summary({ summary, loading }) {
  const items = [
    { key: 'present', label: t('Посещено'), icon: CheckCircle2, className: 'text-success-600 bg-success-50' },
    { key: 'absent', label: t('Пропущено'), icon: XCircle, className: 'text-danger-600 bg-danger-50' },
    { key: 'makeup', label: t('Отработано'), icon: RotateCcw, className: 'text-brand-700 bg-brand-50' },
  ]
  return (
    <div className={`grid grid-cols-1 gap-3 sm:grid-cols-3 ${loading ? 'opacity-60' : ''}`}>
      {items.map(item => (
        <Card key={item.key} className="flex items-center gap-3 p-4">
          <span className={`flex size-10 shrink-0 items-center justify-center rounded-lg ${item.className}`}>
            <item.icon className="size-5" />
          </span>
          <div>
            <p className="text-2xl font-bold leading-none text-ink">{summary[item.key]}</p>
            <p className="mt-1 text-xs font-semibold text-ink-muted">{item.label}</p>
          </div>
        </Card>
      ))}
    </div>
  )
}

function HistorySkeleton() {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
      </div>
      <Skeleton className="h-64" />
    </div>
  )
}

function formatShortDate(iso) {
  if (!iso) return '—'
  const [year, month, day] = iso.split('-')
  return `${day}.${month}.${year}`
}

function pluralDays(n) {
  return plural(n, ['день', 'дня', 'дней'])
}

function MakeupCandidatesModal({ row, onClose, onPick }) {
  const [candidates, setCandidates] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    api.get(`attendance/${row.attendance_id}/makeup-candidates/`)
      .then(response => setCandidates(response.data.results))
      .catch(() => setError(true))
  }, [row.attendance_id])

  return (
    <Modal
      open
      onClose={onClose}
      title={t('Выберите занятие для отработки')}
      description={`${row.group_name || t('Индивидуальное занятие')} · ${t('то же направление')}`}
    >
      {error && <ErrorState />}
      {!error && !candidates && <Skeleton className="h-24" />}
      {!error && candidates && candidates.length === 0 && (
        <EmptyState icon={CalendarClock} title={t('Подходящих занятий не нашлось')} description={t('В этом направлении нет будущих занятий.')} />
      )}
      {!error && candidates && candidates.length > 0 && (
        <div className="space-y-2">
          {candidates.map(lesson => {
            const full = lesson.spots_left !== null && lesson.spots_left <= 0
            return (
              <button
                key={lesson.id}
                type="button"
                onClick={() => onPick(lesson.id)}
                className="flex w-full items-center justify-between gap-3 rounded-md border border-line px-3.5 py-3 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40"
              >
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{lesson.group_name}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-muted">
                    <span className="inline-flex items-center gap-1"><Clock className="size-3.5" />{formatDateTime(lesson.starts_at_local)}</span>
                    {lesson.room_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" />{lesson.room_name}</span>}
                    {lesson.teacher_name && <span>{lesson.teacher_name}</span>}
                  </div>
                </div>
                {lesson.capacity !== null && (
                  <Badge tone={full ? 'danger' : 'neutral'} className="shrink-0">
                    <Users className="size-3" />{lesson.current_count}/{lesson.capacity}
                  </Badge>
                )}
              </button>
            )
          })}
        </div>
      )}
    </Modal>
  )
}
