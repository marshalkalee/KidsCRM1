import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, Check, CheckCheck, MapPin, MessageSquareText, Minus, Plus, UserRound, X } from 'lucide-react'
import api from '../api/axios'
import { useSession } from '../session/SessionContext'
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Select, Skeleton, Tabs, Textarea,
  apiErrorMessage, cn, formatDateTime, useToast,
} from '../ui'
import { PageGroupContext } from '../ui/pageGroup'
import { t } from '../i18n'

/*
 * Запросы родителей: запись и отмена занятий ждут решения администратора.
 * Статус — вкладками в шапке; сначала то, что горит (занятие уже прошло
 * или вот-вот начнётся); у каждой карточки — что будет, если одобрить.
 */

const STATUS_TABS = [
  ['new', 'Новые'],
  ['approved', 'Одобренные'],
  ['rejected', 'Отклонённые'],
  ['all', 'Все'],
]

const TYPE_OPTIONS = [
  ['', 'Все'],
  ['enroll', 'Запись'],
  ['cancel', 'Отмена'],
]

const GROUPS = [
  ['overdue', 'Занятие уже прошло — решить сейчас'],
  ['urgent', 'Занятие в ближайшие сутки'],
  ['normal', 'Ждут решения'],
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
  const [newCount, setNewCount] = useState(null)
  const [error, setError] = useState(false)
  const [filters, setFilters] = useState({ status: 'new', type: '', branch: '' })
  const [selected, setSelected] = useState([])
  const [rejecting, setRejecting] = useState(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    const { status, ...rest } = filters
    const params = Object.fromEntries(Object.entries({ ...rest, status: status === 'all' ? '' : status }).filter(([, value]) => value))
    const requests = [api.get('parent-requests/', { params })]
    // Число на вкладке «Новые» — с теми же типом и филиалом.
    if (status !== 'new') requests.push(api.get('parent-requests/', { params: { ...params, status: 'new' } }))
    Promise.all(requests)
      .then(([list, fresh]) => {
        setRows(list.data.results || list.data)
        setNewCount((fresh || list).data.count ?? (fresh || list).data.length)
        setSelected([])
        setError(false)
      })
      .catch(() => setError(true))
  }, [filters])

  useEffect(() => { load() }, [load])

  const newRows = useMemo(() => rows?.filter(row => row.status === 'new') || [], [rows])
  const selectedRows = useMemo(() => newRows.filter(row => selected.includes(row.id)), [newRows, selected])
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

  const setFilter = (key, value) => setFilters(current => ({ ...current, [key]: value }))
  const group = {
    title: t('Запросы родителей'),
    tabs: (
      <Tabs
        value={filters.status}
        onChange={value => setFilter('status', value)}
        tabs={STATUS_TABS.map(([key, label]) => ({ key, label: t(label), count: key === 'new' ? newCount : null }))}
      />
    ),
  }
  const grouped = filters.status === 'new' && rows
    ? GROUPS.map(([key, title]) => ({ key, title, items: rows.filter(row => requestTone(row) === key) })).filter(g => g.items.length)
    : null

  const card = row => (
    <RequestCard
      key={row.id}
      row={row}
      busy={busy}
      selected={selected.includes(row.id)}
      selectable={row.status === 'new' && (!selectedType || selectedType === row.type || selected.includes(row.id))}
      onToggle={() => toggle(row)}
      onApprove={() => processOne(row, 'approve')}
      onReject={() => setRejecting({ row })}
    />
  )

  return (
    <PageGroupContext.Provider value={group}>
      <PageHeader
        title={t('Запросы родителей')}
        description={t('Запись и отмена занятий подтверждаются здесь — расписание не меняется до одобрения.')}
      />

      <Card className="mb-4 !py-3">
        {selected.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-ink">{t('Выбрано: {n}', { n: selected.length })}</span>
            <Button size="sm" variant="ghost" icon={X} onClick={() => setSelected([])}>{t('Снять выбор')}</Button>
            <div className="ml-auto flex flex-wrap gap-2">
              <Button size="sm" icon={X} onClick={() => setRejecting({ bulk: true })}>{t('Отклонить')}</Button>
              <Button size="sm" variant="primary" icon={CheckCheck} loading={busy} onClick={() => processBulk('approve')}>{t('Одобрить выбранные')}</Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div role="radiogroup" aria-label={t('Тип запроса')} className="flex gap-1 rounded-lg bg-surface-muted p-1">
              {TYPE_OPTIONS.map(([value, label]) => (
                <button
                  key={label}
                  type="button"
                  role="radio"
                  aria-checked={filters.type === value}
                  onClick={() => setFilter('type', value)}
                  className={cn(
                    'h-8 flex-1 rounded-md px-3 text-[13px] font-semibold transition sm:flex-none',
                    filters.type === value ? 'bg-surface text-brand-600 shadow-card ring-1 ring-line' : 'text-ink-muted hover:text-ink',
                  )}
                >
                  {t(label)}
                </button>
              ))}
            </div>
            {branches.length > 1 && (
              <div className="sm:ml-auto sm:w-60">
                <Select aria-label={t('Филиал')} value={filters.branch} onChange={event => setFilter('branch', event.target.value)}>
                  <option value="">{t('Все филиалы')}</option>
                  {branches.map(branch => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
                </Select>
              </div>
            )}
            {filters.status === 'new' && newRows.length > 1 && (
              <p className="text-[12px] text-ink-subtle sm:order-first sm:hidden lg:order-none lg:block">
                {t('Отметьте несколько запросов одного типа, чтобы решить их разом.')}
              </p>
            )}
          </div>
        )}
      </Card>

      {error && <Card><ErrorState onRetry={load} /></Card>}
      {!error && rows === null && <div className="grid gap-3 xl:grid-cols-2"><Skeleton className="h-48" /><Skeleton className="h-48" /></div>}
      {!error && rows?.length === 0 && (
        <Card>
          <EmptyState
            icon={MessageSquareText}
            title={filters.status === 'new' ? t('Новых запросов нет') : t('Запросов пока нет')}
            description={t('Новые запросы родителей появятся здесь и в центре уведомлений.')}
          />
        </Card>
      )}
      {rows?.length > 0 && (grouped ? (
        <div className="space-y-6">
          {grouped.map(g => (
            <section key={g.key}>
              <h2 className={cn(
                'mb-3 flex items-center gap-3 px-1 text-[13px] font-bold uppercase tracking-[0.06em]',
                g.key === 'overdue' ? 'text-danger-600' : g.key === 'urgent' ? 'text-warning-600' : 'text-ink-subtle',
              )}>
                {t(g.title)} <Badge tone={g.key === 'overdue' ? 'danger' : g.key === 'urgent' ? 'warning' : 'neutral'}>{g.items.length}</Badge>
                <span className="h-px flex-1 bg-line" />
              </h2>
              <div className="grid gap-3 xl:grid-cols-2">{g.items.map(card)}</div>
            </section>
          ))}
        </div>
      ) : (
        <div className="grid gap-3 xl:grid-cols-2">{rows.map(card)}</div>
      ))}

      {rejecting && (
        <RejectModal
          count={rejecting.bulk ? selected.length : 1}
          busy={busy}
          onClose={() => setRejecting(null)}
          onSubmit={reason => (rejecting.bulk ? processBulk('reject', reason) : processOne(rejecting.row, 'reject', reason))}
        />
      )}
    </PageGroupContext.Provider>
  )
}

function RequestCard({ row, busy, selected, selectable, onToggle, onApprove, onReject }) {
  const tone = requestTone(row)
  const enroll = row.type === 'enroll'
  const TypeIcon = enroll ? Plus : Minus
  const place = [row.lesson.branch_name, row.lesson.room_name].filter(Boolean).join(' · ')
  return (
    <Card padded={false} className={cn('relative flex overflow-hidden', selected && 'ring-2 ring-brand-400')}>
      {/* Срочность — полоской слева, а не ещё одной плашкой. */}
      <span className={cn('w-1 shrink-0', tone === 'overdue' ? 'bg-danger-600' : tone === 'urgent' ? 'bg-warning-600' : 'bg-transparent')} />
      <div className="flex min-w-0 flex-1 flex-col gap-3 p-4 sm:p-5">
        <div className="flex items-start gap-3">
          {row.status === 'new' && (
            <input
              type="checkbox"
              className="mt-2.5 size-4 shrink-0 accent-[var(--color-brand-500)]"
              checked={selected}
              disabled={!selectable}
              aria-label={t('Выбрать запрос')}
              onChange={onToggle}
            />
          )}
          <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-full', enroll ? 'bg-success-50 text-success-600' : 'bg-danger-50 text-danger-600')}>
            <TypeIcon className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <p className={cn('text-[12px] font-bold uppercase tracking-wide', enroll ? 'text-success-600' : 'text-danger-600')}>
              {enroll ? t('Запись на занятие') : t('Отмена занятия')}
              {row.kind === 'makeup' && <span className="ml-2 text-warning-600">· {t('Отработка')}</span>}
            </p>
            <Link to={`/children/${row.child}`} className="block truncate text-[16px] font-bold text-ink hover:text-brand-700 hover:underline">{row.child_name}</Link>
          </div>
          <span className="shrink-0 text-right text-xs text-ink-muted">
            {row.status === 'new'
              ? <>{t('ждёт')}<br /><span className={cn('font-semibold', tone === 'overdue' ? 'text-danger-600' : 'text-ink')}>{waitLabel(row.created_at)}</span></>
              : <Badge tone={row.status === 'approved' ? 'success' : 'neutral'}>{t(row.status_display)}</Badge>}
          </span>
        </div>

        <div className="space-y-1 text-[13px] text-ink-muted">
          <p className="font-semibold text-ink">{row.lesson.name}</p>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className={cn('inline-flex items-center gap-1.5', tone === 'overdue' && 'font-semibold text-danger-600', tone === 'urgent' && 'font-semibold text-warning-600')}>
              <CalendarClock className="size-4" />{formatDateTime(row.lesson.starts_at)}
            </span>
            {place && <span className="inline-flex items-center gap-1.5"><MapPin className="size-4" />{place}</span>}
            {row.lesson.teacher_name && <span className="inline-flex items-center gap-1.5"><UserRound className="size-4" />{row.lesson.teacher_name}</span>}
          </p>
          {!enroll && row.cancel_reason_display && <p>{t('Причина')}: <span className="font-semibold text-ink">{t(row.cancel_reason_display)}</span></p>}
        </div>

        {row.comment && (
          <p className="flex gap-2 rounded-lg bg-surface-muted px-3 py-2 text-sm text-ink">
            <MessageSquareText className="mt-0.5 size-4 shrink-0 text-ink-subtle" />
            <span>«{row.comment}»</span>
          </p>
        )}

        {row.status === 'new' && <Outcome row={row} />}
        {row.rejection_reason && <p className="text-sm text-danger-700"><span className="font-semibold">{t('Причина отказа')}:</span> {row.rejection_reason}</p>}
        {row.status !== 'new' && row.processed_at && <p className="text-xs text-ink-subtle">{t('Решено {when}', { when: formatDateTime(row.processed_at) })}</p>}

        {row.status === 'new' && (
          <div className="mt-auto grid grid-cols-2 gap-2 sm:flex sm:justify-end">
            <Button icon={X} onClick={onReject}>{t('Отклонить')}</Button>
            <Button variant="primary" icon={Check} loading={busy} onClick={onApprove}>{t('Одобрить')}</Button>
          </div>
        )}
      </div>
    </Card>
  )
}

/** «Если одобрить: …» — главное следствие решения, прямо над кнопками. */
function Outcome({ row }) {
  let tone
  let text
  if (row.type === 'enroll') {
    const spots = row.spots_available_now
    if (spots == null) return null
    tone = spots > 0 ? 'success' : 'danger'
    text = spots > 0
      ? t('ребёнок займёт место — свободно {n}', { n: spots })
      : t('мест нет — группа уже заполнена')
  } else {
    tone = row.will_be_charged ? 'warning' : 'success'
    text = row.will_be_charged
      ? t('занятие спишется — предупредили позже срока')
      : t('занятие не спишется — предупредили вовремя')
  }
  const tones = {
    success: 'bg-success-50 text-success-700',
    warning: 'bg-warning-50 text-warning-700',
    danger: 'bg-danger-50 text-danger-700',
  }
  return (
    <p className={cn('rounded-lg px-3 py-2 text-[13px]', tones[tone])}>
      <span className="font-semibold">{t('Если одобрить')}:</span> {text}
    </p>
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
