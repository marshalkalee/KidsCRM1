import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, CalendarClock, CheckCircle2, ChevronRight, MessageCircle, Phone, UserRoundPlus } from 'lucide-react'
import api from '../api/axios'
import AcceptPaymentModal from '../components/money/AcceptPaymentModal'
import { SellModal } from '../components/money/SubscriptionsTab'
import { useSession } from '../session/SessionContext'
import { Badge, Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Select, Skeleton, Tabs, apiErrorMessage, cn, money, useToast } from '../ui'
import { locale, t } from '../i18n'

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
  call_back: (task, center) => t('Здравствуйте! Это {center}, перезваниваем по вашей заявке.', { center }),
  trial_signup: (task, center) => t('Здравствуйте! Хотим предложить записаться на пробное занятие в {center}.', { center }),
  renewal_offer: task => t('Здравствуйте! Абонемент для {child} скоро закончится — предлагаем продлить заранее.', { child: task.child_name }),
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Заголовок без повтора имени: имя ребёнка и так стоит строкой ниже. */
function taskTitle(task) {
  const name = task.child_name || task.lead_name
  if (!name) return task.title
  const trimmed = task.title.replace(new RegExp(`\\s*[:—–-]\\s*${escapeRegExp(name)}\\s*$`), '').trim()
  return trimmed || task.title
}

/** «Сегодня, 13:22» / «Вчера, 14:22» / «7 окт., 14:22»; конец дня — без времени. */
function dueLabel(iso) {
  const due = new Date(iso)
  const today = new Date()
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1)
  const tomorrow = new Date(); tomorrow.setDate(today.getDate() + 1)
  const endOfDay = due.getHours() === 23 && due.getMinutes() === 59
  const time = due.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })
  const day = due.toDateString() === today.toDateString() ? t('Сегодня')
    : due.toDateString() === yesterday.toDateString() ? t('Вчера')
      : due.toDateString() === tomorrow.toDateString() ? t('Завтра')
        : due.toLocaleDateString(locale, { day: 'numeric', month: 'short' })
  return endOfDay ? day : `${day}, ${time}`
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
  // Каждая группа — один блок с шапкой, а не подписи между карточками.
  const groups = (tab === 'today'
    ? [
        { key: 'overdue', title: t('Просрочено'), icon: AlertTriangle, tone: 'text-danger-600', tasks: overdue },
        { key: 'today', title: t('На сегодня'), icon: CalendarClock, tasks: today },
      ]
    : tab === 'future'
      ? [{ key: 'future', title: t('Запланировано'), icon: CalendarClock, tasks: future }]
      : [{ key: 'history', title: t('Выполненные и отменённые'), icon: CheckCircle2, tasks: history }]
  ).filter(group => group.tasks.length > 0)

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
        <div className="mt-4 space-y-4">
          {groups.map(group => (
            <Card key={group.key} padded={false} className="overflow-hidden">
              <div className="flex items-center gap-2 border-b border-line px-5 py-3">
                {group.icon && <group.icon className={cn('size-4', group.tone)} />}
                <p className={cn('text-[15px] font-bold', group.tone || 'text-ink')}>{group.title}</p>
                <span className="text-[13px] font-semibold text-ink-subtle">{group.tasks.length}</span>
              </div>
              <div className="divide-y divide-line">
                {group.tasks.map(task => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    closed={tab === 'history'}
                    overdue={isOverdue(task.due_at)}
                    closing={closing === task.id}
                    center={user?.organization_name}
                    me={user?.id}
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
                ))}
              </div>
            </Card>
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

function TaskCard({ task, overdue: late, closed, closing, center, me, onComplete, onPostpone, onReassign, onPay, onSell, onOpen }) {
  // Закрытая задача не «просрочена», даже если срок давно прошёл.
  const overdue = late && !closed
  const template = REMINDER_TEMPLATES[task.type]
  const digestLink = task.description?.match(/\/digest\?id=[0-9a-f-]+/i)?.[0]
  const description = taskDescription(task.description)
  const who = task.child_name || task.lead_name
  const debt = Number(task.child_debt) > 0 ? Number(task.child_debt) : 0
  const someoneElse = task.assigned_to && String(task.assigned_to) !== String(me)
  return (
    <div>
      <div className="flex gap-3 px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <p className="text-[15px] font-bold text-ink">{taskTitle(task)}</p>
            {closed && <Badge tone={task.status === 'done' ? 'success' : 'neutral'}>{task.status_display}</Badge>}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
            {task.due_at && !closed && (
              <span className={cn('inline-flex items-center gap-1', overdue ? 'font-semibold text-danger-600' : 'text-ink-muted')}>
                {overdue ? <AlertTriangle className="size-3.5" /> : <CalendarClock className="size-3.5" />}
                {overdue ? t('Просрочено: {when}', { when: dueLabel(task.due_at) }) : dueLabel(task.due_at)}
              </span>
            )}
            {closed && task.updated_at && (
              <span className="inline-flex items-center gap-1 text-success-700">
                <CheckCircle2 className="size-3.5" />
                {t('Завершено {date}', { date: dueLabel(task.updated_at) })}
              </span>
            )}
            {who && (
              <button type="button" onClick={onOpen} className="inline-flex items-center gap-0.5 font-semibold text-ink hover:text-brand-600">
                {who}
                {debt > 0 && task.type === 'payment_reminder' && <span className="ml-1 font-normal text-danger-600">· {t('долг {sum}', { sum: money(debt) })}</span>}
                <ChevronRight className="size-3.5 text-ink-subtle" />
              </button>
            )}
            {someoneElse && task.assigned_to_name && <span className="text-ink-subtle">{t('Исполнитель: {name}', { name: task.assigned_to_name })}</span>}
          </div>
          {description && <p className="mt-2 whitespace-pre-line text-[13px] leading-relaxed text-ink-muted">{description}</p>}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5 px-5 pb-3">
        {task.contact_phone && (
          <a href={`tel:${task.contact_phone}`} className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-semibold text-ink-muted hover:bg-surface hover:text-ink">
            <Phone className="size-4" />
            <span className="hidden sm:inline">{t('Позвонить')}</span>
          </a>
        )}
        {(task.contact_whatsapp || task.contact_phone) && template && (
          <a
            href={waLink(task.contact_whatsapp || task.contact_phone, template(task, center))}
            target="_blank" rel="noreferrer"
            className="inline-flex h-8 items-center gap-1.5 rounded-md px-2.5 text-[13px] font-semibold text-success-600 hover:bg-success-50"
          >
            <MessageCircle className="size-4" />
            <span className="hidden sm:inline">{t('WhatsApp')}</span>
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
          <div className="flex w-full items-center gap-1.5 sm:ml-auto sm:w-auto">
            <Button size="sm" variant="ghost" icon={UserRoundPlus} onClick={onReassign}>{t('Передать')}</Button>
            <Button size="sm" variant="ghost" icon={CalendarClock} onClick={onPostpone}>{t('На завтра')}</Button>
            <Button size="sm" variant="primary" loading={closing} onClick={onComplete} className="ml-auto sm:ml-0">{t('Выполнено')}</Button>
          </div>
        )}
      </div>
    </div>
  )
}
