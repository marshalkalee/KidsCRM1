import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CalendarClock, CheckCircle2, MessageCircle, Phone, UserCheck } from 'lucide-react'
import api from '../api/axios'
import AcceptPaymentModal from '../components/money/AcceptPaymentModal'
import { SellModal } from '../components/money/SubscriptionsTab'
import { useSession } from '../session/SessionContext'
import { Badge, Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Select, Skeleton, Tabs, apiErrorMessage, useToast } from '../ui'
import { t } from '../i18n'

function waLink(phone, text) {
  return `https://wa.me/${phone.replace(/\D/g, '')}?text=${encodeURIComponent(text)}`
}

function isToday(iso) {
  if (!iso) return false
  const d = new Date(iso)
  const now = new Date()
  return d.toDateString() === now.toDateString()
}

function isOverdue(iso) {
  if (!iso) return false
  return new Date(iso) < new Date() && !isToday(iso)
}

function taskDescription(value) {
  const withoutLink = value?.replace(/\n?Открыть дайджест: \/digest\?id=[0-9a-f-]+/i, '') || ''
  const lines = withoutLink.split('\n')
  const reason = lines.find(line => line.startsWith('Основание: '))
  const action = lines.find(line => line.startsWith('Рекомендация: '))
  if (!reason || !action) return withoutLink
  const normalize = line => line.replace(/^(Основание|Рекомендация):\s*/i, '').replace(/[.\s]+$/, '').trim()
  return normalize(reason) === normalize(action)
    ? lines.filter(line => line !== reason).join('\n')
    : withoutLink
}

const REMINDER_TEMPLATES = {
  payment_reminder: task => t('Здравствуйте! Напоминаем об оплате абонемента для {child}. Сумма к оплате: {debt} ₸.', { child: task.child_name, debt: task.child_debt }),
  call_back: task => t('Здравствуйте! Это True Ballet, перезваниваем по вашей заявке.'),
  trial_signup: task => t('Здравствуйте! Хотим предложить записаться на пробное занятие в True Ballet.'),
  renewal_offer: task => t('Здравствуйте! Абонемент для {child} скоро закончится — предлагаем продлить заранее.', { child: task.child_name }),
}

export default function MyTasks() {
  const { user } = useSession()
  const toast = useToast()
  const navigate = useNavigate()
  const [tab, setTab] = useState('today')
  const [tasks, setTasks] = useState(null)
  const [history, setHistory] = useState([])
  const [error, setError] = useState(false)
  const [colleagues, setColleagues] = useState([])
  const [reassigning, setReassigning] = useState(null)
  const [paying, setPaying] = useState(null)
  const [selling, setSelling] = useState(null)
  const [closing, setClosing] = useState(null)

  const load = useCallback(() => {
    Promise.all([
      api.get('tasks/', { params: { assigned_to: user.id, status: 'open' } }),
      api.get('tasks/', { params: { assigned_to: user.id, status: 'done' } }),
      api.get('tasks/', { params: { assigned_to: user.id, status: 'cancelled' } }),
    ])
      .then(([openResponse, doneResponse, cancelledResponse]) => {
        const rows = response => response.data.results || response.data
        setTasks(rows(openResponse))
        setHistory([...rows(doneResponse), ...rows(cancelledResponse)])
        setError(false)
      })
      .catch(() => setError(true))
  }, [user.id])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    api.get('users/').then(res => {
      const rows = (res.data.results || res.data).filter(u => u.id !== user.id && u.role !== 'teacher')
      setColleagues(rows)
    }).catch(() => {})
  }, [user.id])

  const { overdue, today, future } = useMemo(() => {
    const groups = { overdue: [], today: [], future: [] }
    for (const task of tasks || []) {
      if (isOverdue(task.due_at)) groups.overdue.push(task)
      else if (isToday(task.due_at)) groups.today.push(task)
      else groups.future.push(task)
    }
    const byDueAt = (a, b) => new Date(a.due_at || 0) - new Date(b.due_at || 0)
    groups.overdue.sort(byDueAt)
    groups.today.sort(byDueAt)
    groups.future.sort(byDueAt)
    return groups
  }, [tasks])

  async function complete(task, comment = '') {
    setClosing(task.id)
    try {
      await api.post(`tasks/${task.id}/complete/`, { comment })
      toast.success(t('Задача выполнена'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setClosing(null)
    }
  }

  async function postpone(task) {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    try {
      await api.patch(`tasks/${task.id}/`, { due_at: tomorrow.toISOString() })
      toast.success(t('Отложено на завтра'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  async function reassign(task, assigneeId) {
    try {
      await api.patch(`tasks/${task.id}/`, { assigned_to: assigneeId })
      toast.success(t('Задача передана'))
      setReassigning(null)
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (tasks === null) return <Skeleton className="h-60" />

  const visible = tab === 'today' ? [...overdue, ...today] : tab === 'future' ? future : history

  return (
    <div>
      <PageHeader
        title={t('Мои задачи на сегодня')}
        description={overdue.length > 0
          ? t('{n} просрочено, {m} на сегодня', { n: overdue.length, m: today.length })
          : t('{n} задач на сегодня', { n: today.length })}
      />

      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { key: 'today', label: t('Сегодня и просроченные'), count: overdue.length + today.length },
          { key: 'future', label: t('На будущее'), count: future.length },
          { key: 'history', label: t('История'), count: history.length },
        ]}
      />

      {visible.length === 0 ? (
        <Card className="mt-4">
          <EmptyState
            title={tab === 'history' ? t('История задач пуста') : t('Задач нет')}
            description={tab === 'history' ? t('Выполненные задачи появятся здесь.') : t('На сегодня всё сделано.')}
          />
        </Card>
      ) : (
        <div className="mt-4 space-y-2">
          {tab === 'today' && overdue.length > 0 && (
            <p className="flex items-center gap-1.5 text-[13px] font-semibold text-danger-600">
              <AlertTriangle className="size-4" /> {t('Просроченные')}
            </p>
          )}
          {visible.map((task, i) => (
            <div key={task.id}>
              {tab === 'today' && i === overdue.length && overdue.length > 0 && (
                <p className="mb-2 mt-3 text-[13px] font-semibold text-ink-muted">{t('На сегодня')}</p>
              )}
              <TaskCard
                task={task}
                closed={tab === 'history'}
                overdue={isOverdue(task.due_at)}
                closing={closing === task.id}
                onComplete={() => complete(task)}
                onPostpone={() => postpone(task)}
                onReassign={() => setReassigning(task)}
                onPay={() => setPaying(task)}
                onSell={() => setSelling(task)}
                onOpen={() => {
                  if (task.child) navigate(`/children/${task.child}`)
                  else if (task.lead) navigate(`/leads/${task.lead}`)
                }}
              />
            </div>
          ))}
        </div>
      )}

      {reassigning && (
        <Modal open onClose={() => setReassigning(null)} title={t('Передать задачу')}>
          <Field label={t('Кому передать')}>
            {({ id }) => (
              <Select id={id} defaultValue="" onChange={e => e.target.value && reassign(reassigning, e.target.value)}>
                <option value="" disabled>{t('Выберите сотрудника')}</option>
                {colleagues.map(c => <option key={c.id} value={c.id}>{c.full_name}</option>)}
              </Select>
            )}
          </Field>
        </Modal>
      )}

      {paying && (
        <AcceptPaymentModal
          child={{ id: paying.child, full_name: paying.child_name }}
          onClose={() => setPaying(null)}
          onPaid={() => { complete(paying); setPaying(null) }}
        />
      )}

      {selling && (
        <SellModal
          child={{ id: selling.child, full_name: selling.child_name }}
          onClose={() => setSelling(null)}
          onDone={() => { complete(selling); setSelling(null) }}
        />
      )}
    </div>
  )
}

function TaskCard({ task, overdue, closed, closing, onComplete, onPostpone, onReassign, onPay, onSell, onOpen }) {
  const template = REMINDER_TEMPLATES[task.type]
  const digestLink = task.description?.match(/\/digest\?id=[0-9a-f-]+/i)?.[0]
  const description = taskDescription(task.description)
  return (
    <Card className={overdue ? 'border-danger-600' : undefined}>
      <div className="flex items-start justify-between gap-3">
        <button type="button" onClick={onOpen} className="min-w-0 flex-1 text-left">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={overdue ? 'danger' : 'neutral'}>{task.type_display}</Badge>
            {closed && <Badge tone={task.status === 'done' ? 'success' : 'neutral'}>{task.status_display}</Badge>}
            {task.due_at && (
              <span className="inline-flex items-center gap-1 text-[13px] text-ink-muted">
                <CalendarClock className="size-3.5" />
                {new Date(task.due_at).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>
          <p className="mt-1 font-semibold text-ink">{task.title}</p>
          <p className="truncate text-[13px] text-ink-muted">
            {task.child_name || task.lead_name}
            {task.type === 'payment_reminder' && task.child_debt ? ` · ${task.child_debt} ₸` : ''}
          </p>
          {task.assigned_to_name && <p className="text-xs text-ink-subtle">{t('Назначено: {name}', { name: task.assigned_to_name })}</p>}
          {closed && task.updated_at && (
            <p className="mt-1 inline-flex items-center gap-1 text-xs text-success-700">
              <CheckCircle2 className="size-3.5" />
              {t('Завершено {date}', { date: new Date(task.updated_at).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) })}
            </p>
          )}
          {description && <p className="mt-2 whitespace-pre-line text-[13px] text-ink-muted">{description}</p>}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {task.contact_phone && (
          <a href={`tel:${task.contact_phone}`} className="flex size-9 items-center justify-center rounded-md text-ink-muted hover:bg-surface-muted hover:text-ink" title={t('Позвонить')} aria-label={t('Позвонить')}>
            <Phone className="size-4" />
          </a>
        )}
        {(task.contact_whatsapp || task.contact_phone) && template && (
          <a
            href={waLink(task.contact_whatsapp || task.contact_phone, template(task))}
            target="_blank" rel="noreferrer"
            className="flex size-9 items-center justify-center rounded-md text-success-600 hover:bg-success-50"
            title={t('WhatsApp')} aria-label={t('WhatsApp')}
          >
            <MessageCircle className="size-4" />
          </a>
        )}
        {task.type === 'payment_reminder' && task.child && (
          <Button size="sm" variant="secondary" onClick={onPay}>{t('Принять оплату')}</Button>
        )}
        {task.type === 'renewal_offer' && task.child && (
          <Button size="sm" variant="secondary" onClick={onSell}>{t('Продать абонемент')}</Button>
        )}
        {digestLink && <a href={digestLink} className="inline-flex items-center text-sm font-semibold text-brand-600 hover:underline">{t('Открыть дайджест')}</a>}
        {!closed && (
          <div className="ml-auto flex gap-1.5">
            <Button size="sm" variant="ghost" icon={UserCheck} onClick={onReassign} aria-label={t('Передать коллеге')} />
            <Button size="sm" variant="ghost" onClick={onPostpone}>{t('Завтра')}</Button>
            <Button size="sm" variant="primary" loading={closing} onClick={onComplete}>{t('Выполнено')}</Button>
          </div>
        )}
      </div>
    </Card>
  )
}
