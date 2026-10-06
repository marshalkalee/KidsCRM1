import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, Check, CheckCheck, MessageSquareText, UsersRound, X } from 'lucide-react'
import api from '../api/axios'
import { useSession } from '../session/SessionContext'
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Select, Skeleton, Textarea,
  apiErrorMessage, cn, formatDateTime, useToast,
} from '../ui'
import { t } from '../i18n'

const STATUS_OPTIONS = [
  ['new', 'Новые'],
  ['approved', 'Одобренные'],
  ['rejected', 'Отклонённые'],
  ['', 'Все статусы'],
]

const TYPE_OPTIONS = [
  ['', 'Все типы'],
  ['enroll', 'Запись'],
  ['cancel', 'Отмена'],
]

function waitLabel(createdAt) {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(createdAt).getTime()) / 60000))
  if (minutes < 60) return t('{n} мин.', { n: minutes })
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return t('{n} ч.', { n: hours })
  const days = Math.floor(hours / 24)
  return t('{n} дн.', { n: days })
}

function requestTone(row) {
  if (row.status !== 'new') return 'normal'
  const starts = new Date(row.lesson.starts_at).getTime()
  if (starts < Date.now()) return 'overdue'
  if (starts - Date.now() <= 24 * 60 * 60 * 1000) return 'urgent'
  return 'normal'
}

export default function ParentRequests() {
  const toast = useToast()
  const { branches } = useSession()
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(false)
  const [filters, setFilters] = useState({ status: 'new', type: '', branch: '' })
  const [selected, setSelected] = useState([])
  const [rejecting, setRejecting] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    const params = Object.fromEntries(Object.entries(filters).filter(([, value]) => value))
    api.get('parent-requests/', { params })
      .then(({ data }) => {
        setRows(data.results || data)
        setSelected([])
        setError(false)
      })
      .catch(() => setError(true))
  }, [filters])

  useEffect(() => { load() }, [load])

  const newRows = useMemo(() => rows?.filter(row => row.status === 'new') || [], [rows])
  const selectedRows = useMemo(
    () => newRows.filter(row => selected.includes(row.id)),
    [newRows, selected],
  )
  const selectedType = selectedRows[0]?.type

  function toggle(row) {
    setSelected(current => {
      if (current.includes(row.id)) return current.filter(id => id !== row.id)
      const currentRows = newRows.filter(item => current.includes(item.id))
      if (currentRows.length && currentRows[0].type !== row.type) return [row.id]
      return [...current, row.id]
    })
  }

  async function processOne(row, decision, reason = '') {
    setBusy(true)
    try {
      await api.post(`parent-requests/${row.id}/${decision}/`, { reason })
      toast.success(decision === 'approve' ? t('Запрос одобрен') : t('Запрос отклонён'))
      setRejecting(null)
      load()
      window.dispatchEvent(new CustomEvent('kc:notifications-changed'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function processBulk(decision, reason = '') {
    setBusy(true)
    try {
      const { data } = await api.post('parent-requests/bulk/', { ids: selected, decision, reason })
      if (data.processed_count) {
        toast.success(t('Обработано запросов: {n}', { n: data.processed_count }))
      }
      if (data.errors?.length) toast.error(data.errors[0].detail)
      setRejecting(null)
      load()
      window.dispatchEvent(new CustomEvent('kc:notifications-changed'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title={t('Запросы родителей')}
        description={t('Запись и отмена занятий подтверждаются здесь — расписание не меняется до одобрения.')}
        actions={rows && <Badge tone={newRows.length ? 'warning' : 'success'}>{t('Новых: {n}', { n: newRows.length })}</Badge>}
      />

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t('Статус')}>
            {({ id }) => (
              <Select id={id} value={filters.status} onChange={event => setFilters(value => ({ ...value, status: event.target.value }))}>
                {STATUS_OPTIONS.map(([value, label]) => <option key={label} value={value}>{t(label)}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t('Тип запроса')}>
            {({ id }) => (
              <Select id={id} value={filters.type} onChange={event => setFilters(value => ({ ...value, type: event.target.value }))}>
                {TYPE_OPTIONS.map(([value, label]) => <option key={label} value={value}>{t(label)}</option>)}
              </Select>
            )}
          </Field>
          <Field label={t('Филиал')}>
            {({ id }) => (
              <Select id={id} value={filters.branch} onChange={event => setFilters(value => ({ ...value, branch: event.target.value }))}>
                <option value="">{t('Все филиалы')}</option>
                {branches.map(branch => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
              </Select>
            )}
          </Field>
        </div>
      </Card>

      {selected.length > 0 && (
        <Card className="mb-4 border-brand-200 bg-brand-50">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="font-semibold text-ink">{t('Выбрано: {n}', { n: selected.length })}</p>
              <p className="text-sm text-ink-muted">{t('Массово обрабатываются запросы одного типа.')}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button icon={X} onClick={() => setSelected([])}>{t('Снять выбор')}</Button>
              <Button icon={X} onClick={() => setRejecting({ bulk: true })}>{t('Отклонить')}</Button>
              <Button variant="primary" icon={CheckCheck} loading={busy} onClick={() => processBulk('approve')}>{t('Одобрить выбранные')}</Button>
            </div>
          </div>
        </Card>
      )}

      {error && <Card><ErrorState onRetry={load} /></Card>}
      {!error && rows === null && <div className="space-y-3"><Skeleton className="h-44" /><Skeleton className="h-44" /></div>}
      {!error && rows?.length === 0 && (
        <Card><EmptyState icon={MessageSquareText} title={t('Запросов пока нет')} description={t('Новые запросы родителей появятся здесь и в центре уведомлений.')} /></Card>
      )}
      {rows?.length > 0 && (
        <div className="grid gap-3 xl:grid-cols-2">
          {rows.map(row => {
            const tone = requestTone(row)
            const isSelected = selected.includes(row.id)
            const selectable = row.status === 'new' && (!selectedType || selectedType === row.type || isSelected)
            return (
              <Card key={row.id} className={cn(
                'relative overflow-hidden',
                tone === 'overdue' && 'border-danger-200',
                tone === 'urgent' && 'border-warning-200',
                isSelected && 'ring-2 ring-brand-400',
              )}>
                <div className="flex items-start gap-3">
                  {row.status === 'new' && (
                    <input
                      type="checkbox"
                      className="mt-1 size-5 shrink-0 accent-brand-600"
                      checked={isSelected}
                      disabled={!selectable}
                      aria-label={t('Выбрать запрос')}
                      onChange={() => toggle(row)}
                    />
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={row.type === 'cancel' ? 'danger' : 'info'}>{t(row.type_display)}</Badge>
                      {row.kind === 'makeup' && <Badge tone="warning">{t('Отработка')}</Badge>}
                      {row.status !== 'new' && <Badge tone={row.status === 'approved' ? 'success' : 'neutral'}>{t(row.status_display)}</Badge>}
                      {tone === 'overdue' && <Badge tone="danger">{t('Занятие уже прошло')}</Badge>}
                      {tone === 'urgent' && <Badge tone="warning">{t('Занятие скоро')}</Badge>}
                      <span className="ml-auto text-xs text-ink-muted">{row.status === 'new' ? t('Ждёт {time}', { time: waitLabel(row.created_at) }) : formatDateTime(row.processed_at)}</span>
                    </div>

                    <Link to={`/children/${row.child}`} className="mt-3 block text-lg font-bold text-ink hover:text-brand-700 hover:underline">{row.child_name}</Link>
                    <div className="mt-2 grid gap-2 rounded-lg bg-surface-muted p-3 text-sm text-ink-muted sm:grid-cols-2">
                      <p className="font-semibold text-ink sm:col-span-2">{row.lesson.name}</p>
                      <p className="flex items-center gap-1.5"><CalendarClock className="size-4" />{formatDateTime(row.lesson.starts_at)}</p>
                      <p>{[row.lesson.branch_name, row.lesson.room_name].filter(Boolean).join(' · ') || '—'}</p>
                      {row.lesson.teacher_name && <p className="sm:col-span-2">{t('Преподаватель')}: {row.lesson.teacher_name}</p>}
                    </div>

                    {row.type === 'enroll' && (
                      <p className="mt-3 flex items-center gap-1.5 text-sm text-ink-muted">
                        <UsersRound className="size-4" />
                        {t('Свободных мест: сейчас {now}, при запросе {then}', { now: row.spots_available_now, then: row.spots_available_at_request })}
                      </p>
                    )}
                    {row.type === 'cancel' && (
                      <div className="mt-3 text-sm text-ink-muted">
                        <p>{t('Причина')}: <span className="font-semibold text-ink">{t(row.cancel_reason_display)}</span></p>
                        <p className={row.notice_is_timely ? 'text-success-700' : 'text-warning-700'}>
                          {row.notice_is_timely ? t('Предупреждение отправлено вовремя') : t('Предупреждение отправлено позже срока')} · {row.will_be_charged ? t('занятие спишется') : t('занятие не спишется')}
                        </p>
                      </div>
                    )}
                    {row.comment && <p className="mt-3 rounded-lg border border-line px-3 py-2 text-sm text-ink">{row.comment}</p>}
                    {row.rejection_reason && <p className="mt-3 text-sm text-danger-700"><span className="font-semibold">{t('Причина отказа')}:</span> {row.rejection_reason}</p>}

                    {row.status === 'new' && (
                      <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
                        <Button className="w-full sm:w-auto" icon={X} onClick={() => setRejecting({ row })}>{t('Отклонить')}</Button>
                        <Button className="w-full sm:w-auto" variant="primary" icon={Check} loading={busy} onClick={() => processOne(row, 'approve')}>{t('Одобрить')}</Button>
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {rejecting && (
        <RejectModal
          count={rejecting.bulk ? selected.length : 1}
          busy={busy}
          onClose={() => setRejecting(null)}
          onSubmit={reason => rejecting.bulk ? processBulk('reject', reason) : processOne(rejecting.row, 'reject', reason)}
        />
      )}
    </div>
  )
}

function RejectModal({ count, busy, onClose, onSubmit }) {
  const [reason, setReason] = useState('')
  const invalid = reason.trim().length < 3
  return (
    <Modal
      open
      onClose={onClose}
      title={t('Отклонить запрос')}
      footer={(
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" disabled={invalid} loading={busy} onClick={() => onSubmit(reason)}>{t('Отклонить {n}', { n: count })}</Button>
        </>
      )}
    >
      <p className="mb-4 text-sm text-ink-muted">{t('Родитель увидит это объяснение в своём кабинете.')}</p>
      <Field label={t('Причина отказа')} required hint={t('Минимум 3 символа')}>
        {({ id }) => <Textarea id={id} rows={4} maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} autoFocus />}
      </Field>
    </Modal>
  )
}
