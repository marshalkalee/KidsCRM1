import { useCallback, useEffect, useState } from 'react'
import { ListChecks, PlusCircle, Snowflake } from 'lucide-react'
import { fetchBranches, fetchDirections } from '../../api/lessons'
import {
  fetchChildSubscriptions, fetchLedger, fetchNextLesson, fetchSubscriptionTypes,
  freezeSubscription, sellSubscription, unfreezeSubscription,
} from '../../api/subscriptions'
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, Select, Skeleton,
  apiErrorMessage, formatDate, formatDateTime, money, useToast,
} from '../../ui'

const STATUS_TONE = { active: 'success', frozen: 'warning', expired: 'neutral', exhausted: 'danger' }

const METHODS = [
  { value: 'kaspi_transfer', label: 'Kaspi-перевод' },
  { value: 'cash', label: 'Наличные' },
  { value: 'card', label: 'Карта' },
  { value: 'other', label: 'Другое' },
]

const DISCOUNT_REASONS = [
  { value: 'large_family', label: 'Многодетная семья' },
  { value: 'second_child', label: 'Второй ребёнок' },
  { value: 'promotion', label: 'Акция' },
  { value: 'staff', label: 'Сотрудник' },
  { value: 'other', label: 'Другое' },
]

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

export default function SubscriptionsTab({ child, onCountChange }) {
  const toast = useToast()
  const [subscriptions, setSubscriptions] = useState(null)
  const [error, setError] = useState(false)
  const [ledgerFor, setLedgerFor] = useState(null)
  const [freezeFor, setFreezeFor] = useState(null)
  const [sellOpen, setSellOpen] = useState(false)

  const load = useCallback(() => {
    fetchChildSubscriptions(child.id)
      .then(rows => {
        setSubscriptions(rows)
        setError(false)
        onCountChange?.(rows.length)
      })
      .catch(() => setError(true))
  }, [child.id, onCountChange])

  useEffect(() => { load() }, [load])

  async function unfreeze(sub) {
    try {
      await unfreezeSubscription(sub.id)
      toast.success('Абонемент разморожен')
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (subscriptions === null) return <Skeleton className="h-40" />

  const current = subscriptions.find(s => s.status === 'active' || s.status === 'frozen')

  return (
    <div className="space-y-4">
      {current && (
        <Card className="space-y-2">
          <div className="flex items-center justify-between">
            <p className="font-semibold text-ink">{current.subscription_type_name}</p>
            <Badge tone={STATUS_TONE[current.status]}>{current.status_display}</Badge>
          </div>
          <p className="text-[13px] text-ink-muted">
            Осталось занятий: {current.sessions_remaining_cache ?? 'безлимит'} · до {formatDate(current.ends_on)}
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <Button variant="secondary" size="sm" icon={ListChecks} onClick={() => setLedgerFor(current)}>
              Журнал списаний
            </Button>
            {current.status === 'active' && (
              <Button variant="secondary" size="sm" icon={Snowflake} onClick={() => setFreezeFor(current)}>
                Заморозить
              </Button>
            )}
            {current.status === 'frozen' && (
              <Button variant="secondary" size="sm" onClick={() => unfreeze(current)}>Разморозить</Button>
            )}
          </div>
        </Card>
      )}

      <Button variant="primary" size="sm" icon={PlusCircle} onClick={() => setSellOpen(true)}>
        Продать абонемент
      </Button>

      <p className="font-semibold text-ink">История абонементов</p>
      {subscriptions.length === 0 ? (
        <Card><EmptyState title="Абонементов ещё не было" /></Card>
      ) : (
        <div className="space-y-2">
          {subscriptions.map(s => (
            <Card key={s.id} className="flex items-center justify-between">
              <div className="min-w-0">
                <p className="font-semibold text-ink">{s.subscription_type_name}</p>
                <p className="text-[13px] text-ink-muted">
                  {formatDate(s.starts_on)} — {formatDate(s.ends_on)} · {money(s.price)}
                </p>
              </div>
              <Badge tone={STATUS_TONE[s.status]}>{s.status_display}</Badge>
            </Card>
          ))}
        </div>
      )}

      {ledgerFor && <LedgerModal subscription={ledgerFor} onClose={() => setLedgerFor(null)} />}
      {freezeFor && (
        <FreezeModal
          subscription={freezeFor}
          onClose={() => setFreezeFor(null)}
          onDone={() => { setFreezeFor(null); load() }}
        />
      )}
      {sellOpen && (
        <SellModal child={child} onClose={() => setSellOpen(false)} onDone={() => { setSellOpen(false); load() }} />
      )}
    </div>
  )
}

function LedgerModal({ subscription, onClose }) {
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetchLedger(subscription.id).then(setEntries).catch(() => setError(true))
  }, [subscription.id])

  return (
    <Modal open onClose={onClose} title="Из чего сложился остаток" description={subscription.subscription_type_name}>
      {error && <ErrorState />}
      {!error && !entries && <Skeleton className="h-24" />}
      {!error && entries && entries.length === 0 && <EmptyState title="Записей пока нет" />}
      {!error && entries && entries.length > 0 && (
        <div className="space-y-2">
          {entries.map(entry => (
            <div key={entry.id} className="flex items-center justify-between border-b border-line py-2 text-[13px] last:border-0">
              <div>
                <p className="text-ink">{entry.kind_display}</p>
                {entry.comment && <p className="text-ink-muted">{entry.comment}</p>}
              </div>
              <div className="text-right">
                <p className={entry.delta < 0 ? 'text-danger-600' : 'text-success-600'}>{entry.delta > 0 ? `+${entry.delta}` : entry.delta}</p>
                <p className="text-ink-muted">{formatDateTime(entry.created_at)}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </Modal>
  )
}

function FreezeModal({ subscription, onClose, onDone }) {
  const toast = useToast()
  const [startsOn, setStartsOn] = useState('')
  const [endsOn, setEndsOn] = useState('')
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (submitting) return
    setSubmitting(true)
    try {
      await freezeSubscription(subscription.id, { starts_on: startsOn, ends_on: endsOn, reason })
      toast.success('Абонемент заморожен')
      onDone()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Заморозить абонемент">
      <form onSubmit={submit} className="space-y-3">
        <Field label="Дата начала" required>
          {({ id }) => <Input id={id} type="date" value={startsOn} onChange={e => setStartsOn(e.target.value)} required />}
        </Field>
        <Field label="Дата окончания" required>
          {({ id }) => <Input id={id} type="date" value={endsOn} onChange={e => setEndsOn(e.target.value)} required />}
        </Field>
        <Field label="Причина">
          {({ id }) => <Input id={id} value={reason} onChange={e => setReason(e.target.value)} />}
        </Field>
        <Button type="submit" variant="primary" loading={submitting}>Заморозить</Button>
      </form>
    </Modal>
  )
}

function SellModal({ child, onClose, onDone }) {
  const toast = useToast()
  const [loaded, setLoaded] = useState(false)
  const [branches, setBranches] = useState([])
  const [directions, setDirections] = useState([])
  const [types, setTypes] = useState([])
  const [startMode, setStartMode] = useState('today')
  const [firstLessonDate, setFirstLessonDate] = useState(null)
  const [firstLessonLoading, setFirstLessonLoading] = useState(false)
  const [form, setForm] = useState({
    branch_id: '', direction_id: '', subscription_type_id: '',
    starts_on: todayIso(),
    discount_amount: '', discount_reason: '', paid_amount: '', payment_method: 'kaspi_transfer',
  })
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    Promise.all([fetchBranches(), fetchDirections(), fetchSubscriptionTypes()])
      .then(([branchRows, directionRows, typeRows]) => {
        setBranches(branchRows)
        setDirections(directionRows)
        setTypes(typeRows)
        setForm(f => ({
          ...f,
          branch_id: branchRows[0]?.id || '',
          direction_id: directionRows[0]?.id || '',
          subscription_type_id: typeRows[0]?.id || '',
        }))
        setLoaded(true)
      })
      .catch(() => toast.error('Не удалось загрузить справочники'))
  }, [toast])

  useEffect(() => {
    if (startMode !== 'first_lesson' || !form.direction_id) return
    setFirstLessonLoading(true)
    fetchNextLesson(child.id, form.direction_id)
      .then(startsAt => {
        setFirstLessonDate(startsAt)
        if (startsAt) setForm(f => ({ ...f, starts_on: startsAt.slice(0, 10) }))
      })
      .catch(() => toast.error('Не удалось найти занятие'))
      .finally(() => setFirstLessonLoading(false))
  }, [startMode, form.direction_id, child.id, toast])

  function selectMode(mode) {
    setStartMode(mode)
    if (mode === 'today') setForm(f => ({ ...f, starts_on: todayIso() }))
  }

  async function submit(e) {
    e.preventDefault()
    if (submitting) return
    setSubmitting(true)
    try {
      await sellSubscription({
        child_id: child.id,
        branch_id: form.branch_id,
        direction_id: form.direction_id,
        subscription_type_id: form.subscription_type_id,
        starts_on: form.starts_on,
        discount_amount: form.discount_amount || 0,
        discount_reason: form.discount_reason,
        paid_amount: form.paid_amount,
        payment_method: form.payment_method,
      })
      toast.success('Абонемент продан')
      onDone()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal open onClose={onClose} title="Продать абонемент">
      {!loaded ? (
        <Skeleton className="h-40" />
      ) : (
        <form onSubmit={submit} className="space-y-3">
          <Field label="Тип абонемента" required>
            {({ id }) => (
              <Select id={id} value={form.subscription_type_id} onChange={e => setForm({ ...form, subscription_type_id: e.target.value })}>
                {types.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Филиал" required>
            {({ id }) => (
              <Select id={id} value={form.branch_id} onChange={e => setForm({ ...form, branch_id: e.target.value })}>
                {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Направление" required>
            {({ id }) => (
              <Select id={id} value={form.direction_id} onChange={e => setForm({ ...form, direction_id: e.target.value })}>
                {directions.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
            )}
          </Field>

          <div>
            <p className="text-[13px] font-medium text-ink mb-1">Дата начала</p>
            <div className="flex flex-col gap-1" role="radiogroup" aria-label="Дата начала">
              <label className="flex items-center gap-2 text-[13px]">
                <input type="radio" checked={startMode === 'today'} onChange={() => selectMode('today')} />
                Сегодня
              </label>
              <label className="flex items-center gap-2 text-[13px]">
                <input type="radio" checked={startMode === 'specific'} onChange={() => selectMode('specific')} />
                С конкретной даты
              </label>
              <label className="flex items-center gap-2 text-[13px]">
                <input type="radio" checked={startMode === 'first_lesson'} onChange={() => selectMode('first_lesson')} />
                С первого занятия
              </label>
            </div>
            {startMode === 'specific' && (
              <Input
                type="date" className="mt-2"
                value={form.starts_on}
                onChange={e => setForm({ ...form, starts_on: e.target.value })}
                required
              />
            )}
            {startMode === 'first_lesson' && (
              <p className="text-[13px] text-ink-muted mt-2">
                {firstLessonLoading && 'Ищем ближайшее занятие…'}
                {!firstLessonLoading && firstLessonDate && `Первое занятие: ${formatDate(firstLessonDate)}`}
                {!firstLessonLoading && !firstLessonDate && 'Занятий по этому направлению не найдено — выберите дату вручную'}
              </p>
            )}
          </div>

          <Field label="Скидка">
            {({ id }) => <Input id={id} type="number" value={form.discount_amount} onChange={e => setForm({ ...form, discount_amount: e.target.value })} />}
          </Field>
          <Field label="Причина скидки">
            {({ id }) => (
              <Select id={id} value={form.discount_reason} onChange={e => setForm({ ...form, discount_reason: e.target.value })}>
                <option value="">Без скидки</option>
                {DISCOUNT_REASONS.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Оплачено сейчас" required>
            {({ id }) => <Input id={id} type="number" value={form.paid_amount} onChange={e => setForm({ ...form, paid_amount: e.target.value })} required />}
          </Field>
          <Field label="Способ оплаты">
            {({ id }) => (
              <Select id={id} value={form.payment_method} onChange={e => setForm({ ...form, payment_method: e.target.value })}>
                {METHODS.map(m => <option key={m.value} value={m.value}>{m.label}</option>)}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="primary" loading={submitting}>Продать</Button>
        </form>
      )}
    </Modal>
  )
}