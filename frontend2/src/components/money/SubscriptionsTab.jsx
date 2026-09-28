import { useCallback, useEffect, useState } from 'react'
import { ListChecks, Snowflake } from 'lucide-react'
import { fetchLedger, freezeSubscription, fetchChildSubscriptions, unfreezeSubscription } from '../../api/subscriptions'
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, Input, Modal, Skeleton,
  apiErrorMessage, formatDate, formatDateTime, money, useToast,
} from '../../ui'

const STATUS_TONE = { active: 'success', frozen: 'warning', expired: 'neutral', exhausted: 'danger' }

export default function SubscriptionsTab({ child, onCountChange }) {
  const toast = useToast()
  const [subscriptions, setSubscriptions] = useState(null)
  const [error, setError] = useState(false)
  const [ledgerFor, setLedgerFor] = useState(null)
  const [freezeFor, setFreezeFor] = useState(null)

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