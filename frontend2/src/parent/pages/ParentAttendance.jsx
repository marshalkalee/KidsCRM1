import { useState } from 'react'
import {
  CalendarDays,
  Check,
  CheckSquare,
  Clock3,
  CloudOff,
  CreditCard,
  MapPin,
  RotateCcw,
  X,
} from 'lucide-react'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  DateInput,
  EmptyState,
  ErrorState,
  Field,
  Skeleton,
  formatDate,
} from '../../ui'
import { t } from '../../i18n'
import { usePortalData } from '../api'
import { useParent } from '../useParent'

const STATUS = {
  present: { label: 'Был', tone: 'success', icon: Check },
  absent: { label: 'Не был', tone: 'neutral', icon: X },
  makeup: { label: 'Отработка', tone: 'info', icon: RotateCcw },
}

const ABSENCE_REASON = {
  illness: 'Болезнь',
  family: 'Семейные обстоятельства',
}

const CONSUMPTION = {
  no_active_subscription: 'Не списано: активного абонемента нет',
  subscription_exhausted: 'Не списано: занятия закончились',
  subscription_frozen: 'Не списано: абонемент заморожен',
  rule_forbids: 'Не списано по условиям абонемента',
  makeup_no_charge: 'Отработка не списывает новое занятие',
  trial_no_charge: 'Пробное занятие не списывается',
}

function isoDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function initialPeriod() {
  const today = new Date()
  const from = new Date(today.getFullYear(), today.getMonth() - 2, 1)
  return { dateFrom: isoDate(from), dateTo: isoDate(today) }
}

function attendanceUrl(childId, period) {
  if (!childId) return null
  const params = new URLSearchParams()
  if (period.dateFrom) params.set('date_from', period.dateFrom)
  if (period.dateTo) params.set('date_to', period.dateTo)
  const query = params.toString()
  return `children/${childId}/attendance/${query ? `?${query}` : ''}`
}

function lessonDate(value) {
  return value ? formatDate(value.slice(0, 10)) : '—'
}

function lessonTime(value) {
  return value?.slice(11, 16) || '—'
}

function lessonTitle(row) {
  return row.group_name || row.lesson_name || t('Индивидуальное занятие')
}

export default function ParentAttendance() {
  const { child } = useParent()
  const [draft, setDraft] = useState(initialPeriod)
  const [period, setPeriod] = useState(initialPeriod)
  const [periodError, setPeriodError] = useState('')
  const attendance = usePortalData(attendanceUrl(child?.id, period))

  function applyPeriod(event) {
    event.preventDefault()
    if (draft.dateFrom && draft.dateTo && draft.dateFrom > draft.dateTo) {
      setPeriodError(t('Конец периода не может быть раньше начала.'))
      return
    }
    setPeriodError('')
    setPeriod({ ...draft })
  }

  function showAll() {
    const all = { dateFrom: '', dateTo: '' }
    setDraft(all)
    setPeriod(all)
    setPeriodError('')
  }

  if (!child) {
    return (
      <Card>
        <EmptyState icon={CheckSquare} title={t('Ребёнок не выбран')} />
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={t('История посещений')}
          description={t('Здесь видно, когда ребёнок был на занятии и списалось ли оно с абонемента.')}
        />
        <form onSubmit={applyPeriod} className="grid grid-cols-2 gap-3 md:grid-cols-[minmax(180px,240px)_minmax(180px,240px)_auto] md:items-end">
          <Field label={t('С даты')} error={periodError}>
            {({ id, invalid }) => (
              <DateInput
                id={id}
                invalid={invalid}
                value={draft.dateFrom}
                max={draft.dateTo || undefined}
                onChange={dateFrom => setDraft(current => ({ ...current, dateFrom }))}
              />
            )}
          </Field>
          <Field label={t('По дату')}>
            {({ id }) => (
              <DateInput
                id={id}
                value={draft.dateTo}
                min={draft.dateFrom || undefined}
                onChange={dateTo => setDraft(current => ({ ...current, dateTo }))}
              />
            )}
          </Field>
          <div className="col-span-2 grid grid-cols-2 gap-2 md:col-span-1 md:flex">
            <Button type="submit" variant="primary" loading={attendance.loading}>{t('Показать')}</Button>
            <Button type="button" onClick={showAll}>{t('За всё время')}</Button>
          </div>
        </form>
      </Card>

      {attendance.stale && (
        <p className="flex items-center gap-2 rounded-lg bg-warning-50 px-3 py-2 text-[13px] text-warning-600">
          <CloudOff className="size-4 shrink-0" />
          {t('Показаны сохранённые данные. Они могут быть неактуальны.')}
        </p>
      )}

      {attendance.loading && !attendance.data ? (
        <LoadingState />
      ) : attendance.error ? (
        <Card><ErrorState onRetry={attendance.reload} /></Card>
      ) : attendance.data ? (
        <AttendanceContent data={attendance.data} />
      ) : null}
    </div>
  )
}

function LoadingState() {
  return (
    <>
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2].map(item => <Skeleton key={item} className="h-20" />)}
      </div>
      <Skeleton className="h-40" />
      <Skeleton className="h-52" />
    </>
  )
}

function AttendanceContent({ data }) {
  const summary = data.summary || {}
  const hasMakeups = data.available_makeups?.length > 0
  return (
    <>
      <section aria-label={t('Сводка за период')} className="grid grid-cols-3 gap-2">
        <SummaryCard value={summary.present || 0} label={t('Посещено')} tone="text-success-600" />
        <SummaryCard value={summary.absent || 0} label={t('Пропущено')} tone="text-ink-muted" />
        <SummaryCard value={summary.makeup || 0} label={t('Отработано')} tone="text-info-600" />
      </section>

      <div className={hasMakeups ? 'grid items-start gap-4 lg:grid-cols-[minmax(300px,0.72fr)_minmax(0,1.28fr)]' : ''}>
        {hasMakeups && <AvailableMakeups rows={data.available_makeups} />}
        <AttendanceHistory rows={data.results} />
      </div>
    </>
  )
}

function AttendanceHistory({ rows }) {
  return (
    <Card>
      <CardHeader
        title={t('Посещения за период')}
        description={t('По каждой дате показан факт списания с абонемента.')}
      />
      {rows?.length ? (
        <ul className="divide-y divide-line">
          {rows.map(row => <AttendanceRow key={row.id} row={row} />)}
        </ul>
      ) : (
        <EmptyState
          icon={CalendarDays}
          title={t('За этот период посещений нет')}
          description={t('Выберите другой период или покажите историю за всё время.')}
        />
      )}
    </Card>
  )
}

function SummaryCard({ value, label, tone }) {
  return (
    <Card className="min-w-0 px-2 py-3 text-center sm:px-4">
      <p className={`text-2xl font-bold ${tone}`}>{value}</p>
      <p className="mt-0.5 truncate text-[11px] text-ink-muted sm:text-xs">{label}</p>
    </Card>
  )
}

function AvailableMakeups({ rows }) {
  return (
    <Card>
      <CardHeader
        title={t('Доступные отработки')}
        description={t('Успейте запросить запись до указанной даты.')}
      />
      <ul className="space-y-2.5">
        {rows.map(row => (
          <li key={row.attendance_id} className="rounded-lg border border-line bg-canvas p-3.5">
            <div className="flex items-start gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-info-50 text-info-600">
                <RotateCcw className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="font-semibold text-ink">{lessonTitle(row)}</p>
                {row.group_name && <p className="text-[12.5px] text-ink-muted">{row.lesson_name}</p>}
                <p className="mt-0.5 text-[12.5px] text-ink-muted">
                  {t('Пропуск от {date}', { date: lessonDate(row.starts_at_local) })}
                </p>
                <p className="mt-1 text-[13px] font-semibold text-info-600">
                  {t('Можно отработать до {date}', { date: formatDate(row.expires_on) })}
                </p>
              </div>
            </div>
            <Button
              to={`/parent/schedule?makeup=${row.attendance_id}`}
              variant="primary"
              className="mt-3 w-full justify-center"
            >
              {t('Запросить запись на отработку')}
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function AttendanceRow({ row }) {
  const status = STATUS[row.status] || STATUS.absent
  const StatusIcon = status.icon
  const reason = ABSENCE_REASON[row.absence_reason]
  const consumption = row.consumed_from_subscription
    ? 'Списано с абонемента'
    : CONSUMPTION[row.consume_outcome] || 'Не списано с абонемента'

  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-ink">{lessonTitle(row)}</p>
          {row.group_name && <p className="mt-0.5 text-[12.5px] text-ink-muted">{row.lesson_name}</p>}
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-muted">
            <span className="inline-flex items-center gap-1"><CalendarDays className="size-3.5" />{lessonDate(row.starts_at_local)}</span>
            <span className="inline-flex items-center gap-1"><Clock3 className="size-3.5" />{lessonTime(row.starts_at_local)}–{lessonTime(row.ends_at_local)}</span>
          </p>
          {(row.branch_name || row.room_name) && (
            <p className="mt-1 inline-flex items-center gap-1 text-[12.5px] text-ink-subtle">
              <MapPin className="size-3.5" />{[row.branch_name, row.room_name].filter(Boolean).join(' · ')}
            </p>
          )}
        </div>
        <Badge tone={status.tone} className="shrink-0">
          <StatusIcon className="size-3" />{t(status.label)}
        </Badge>
      </div>

      <div className={`mt-3 flex items-center gap-2 rounded-md px-3 py-2 text-[12.5px] ${row.consumed_from_subscription ? 'bg-success-50 text-success-600' : 'bg-surface-muted text-ink-muted'}`}>
        <CreditCard className="size-4 shrink-0" />
        <span className="font-semibold">{t(consumption)}</span>
      </div>
      {reason && <p className="mt-2 text-[12.5px] text-ink-muted">{t('Причина пропуска: {reason}', { reason: t(reason) })}</p>}
    </li>
  )
}
