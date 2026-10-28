import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertTriangle, CalendarClock, CheckCircle2, ChevronRight, MessageCircle, Plus, UserRoundPlus } from 'lucide-react'
import api from '../api/axios'
import AcceptPaymentModal from '../components/money/AcceptPaymentModal'
import CommentsCount from '../components/tasks/CommentsCount'
import NewTaskModal from '../components/tasks/NewTaskModal'
import TaskPanel from '../components/tasks/TaskPanel'
import CallButton from '../components/telephony/CallButton'
import { ROLE_LABELS, TASK_MANAGER_ROLES, TASK_TYPES } from '../components/tasks/types'
import { SellModal } from '../components/money/SubscriptionsTab'
import { useSession } from '../session/SessionContext'
import { Badge, Button, Card, Dropdown, EmptyState, ErrorState, Field, Modal, PageHeader, SearchInput, Select, Skeleton, apiErrorMessage, cn, money, useToast } from '../ui'
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

// История: закрытые задачи за период, свежие сверху, по 50 с «Показать ещё» —
// иначе за полгода работы она растёт одним бесконечным списком.
const HISTORY_PERIODS = [
  { value: '7', get label() { return t('7 дней') } },
  { value: '30', get label() { return t('30 дней') } },
  { value: '90', get label() { return t('3 месяца') } },
  { value: 'all', get label() { return t('Всё время') } },
]

const HISTORY_STATUSES = [
  { value: 'closed', get label() { return t('Выполненные и отменённые') } },
  { value: 'done', get label() { return t('Выполненные') } },
  { value: 'cancelled', get label() { return t('Отменённые') } },
]

const HISTORY_DEFAULTS = { period: '7', status: 'closed', type: '', q: '' }

/** Начало дня N дней назад (сегодня входит в период). */
function closedAfter(period) {
  if (period === 'all') return undefined
  const since = new Date()
  since.setHours(0, 0, 0, 0)
  since.setDate(since.getDate() - Number(period) + 1)
  return since.toISOString()
}

/** «Сегодня» / «Вчера» / «пн, 20 окт.» — шапка дня в истории. */
function closedDayLabel(iso) {
  const day = new Date(iso)
  const today = new Date()
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1)
  if (day.toDateString() === today.toDateString()) return t('Сегодня')
  if (day.toDateString() === yesterday.toDateString()) return t('Вчера')
  return day.toLocaleDateString(locale, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    ...(day.getFullYear() !== today.getFullYear() && { year: 'numeric' }),
  })
}

export default function MyTasks() {
  const { user } = useSession()
  const toast = useToast()
  const navigate = useNavigate()
  // Карточка задачи (TRU-184): /tasks?open=<id> — ссылкой из уведомления.
  const [params, setParams] = useSearchParams()
  const openId = params.get('open')
  const [tab, setTab] = useState('today')
  const [tasks, setTasks] = useState(null)
  const [historyFilters, setHistoryFilters] = useState(HISTORY_DEFAULTS)
  const [history, setHistory] = useState({ rows: [], count: 0, page: 1, next: null, failed: false })
  const [loadingMore, setLoadingMore] = useState(false)
  // Ответ на старый фильтр не должен затереть ответ на новый.
  const historyRequest = useRef(0)
  const [error, setError] = useState(false)
  const [colleagues, setColleagues] = useState([])
  const [reassigning, setReassigning] = useState(null)
  const [paying, setPaying] = useState(null)
  const [selling, setSelling] = useState(null)
  const [closing, setClosing] = useState(null)
  const [creating, setCreating] = useState(false)
  // Ставить и передавать задачи — руководитель и администратор; бухгалтер и
  // преподаватель только выполняют и переносят свои.
  const canManage = TASK_MANAGER_ROLES.includes(user?.role)

  const loadOpen = useCallback(() => {
    api.get('tasks/', { params: { assigned_to: user.id, status: 'open' } })
      .then(response => {
        setTasks(response.data.results || response.data)
        setError(false)
      })
      .catch(() => setError(true))
  }, [user.id])
  useEffect(() => { loadOpen() }, [loadOpen])

  const loadHistory = useCallback((page = 1) => {
    const request = ++historyRequest.current
    return api.get('tasks/', {
      params: {
        assigned_to: user.id,
        status: historyFilters.status,
        type: historyFilters.type || undefined,
        q: historyFilters.q || undefined,
        closed_after: closedAfter(historyFilters.period),
        ordering: '-closed',
        page,
      },
    })
      .then(response => {
        if (request !== historyRequest.current) return
        const rows = response.data.results || response.data
        setHistory(prev => ({
          rows: page === 1 ? rows : [...prev.rows, ...rows],
          count: response.data.count ?? rows.length,
          page,
          next: response.data.next || null,
          failed: false,
        }))
      })
      .catch(() => {
        if (request === historyRequest.current) setHistory(prev => ({ ...prev, failed: true }))
      })
  }, [user.id, historyFilters])
  useEffect(() => { loadHistory() }, [loadHistory])

  // Закрыли, перенесли или передали задачу — обновить и открытые, и историю.
  const load = useCallback(() => {
    loadOpen()
    loadHistory()
  }, [loadOpen, loadHistory])

  function changeHistory(patch) {
    setHistoryFilters(prev => ({ ...prev, ...patch }))
  }

  function showMore() {
    setLoadingMore(true)
    loadHistory(history.page + 1).finally(() => setLoadingMore(false))
  }

  const historyGroups = useMemo(() => {
    const groups = []
    for (const task of history.rows) {
      const key = new Date(task.updated_at).toDateString()
      let group = groups.find(item => item.key === key)
      if (!group) {
        group = { key, title: closedDayLabel(task.updated_at), icon: CheckCircle2, tasks: [] }
        groups.push(group)
      }
      group.tasks.push(task)
    }
    return groups
  }, [history.rows])
  const historyFiltered = historyFilters.status !== HISTORY_DEFAULTS.status
    || Boolean(historyFilters.type) || Boolean(historyFilters.q)

  useEffect(() => {
    api.get('users/').then(res => {
      const rows = (res.data.results || res.data).filter(u => u.id !== user.id && u.is_active !== false)
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

  const openTask = useCallback(id => {
    setParams(prev => {
      const next = new URLSearchParams(prev)
      next.set('open', id)
      return next
    })
  }, [setParams])
  const closeTask = useCallback(() => {
    setParams(prev => {
      const next = new URLSearchParams(prev)
      next.delete('open')
      return next
    })
  }, [setParams])

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (tasks === null) return <Skeleton className="h-60" />

  const visible = tab === 'today' ? [...overdue, ...today] : tab === 'future' ? future : history.rows
  // Каждая группа — один блок с шапкой, а не подписи между карточками.
  // История — по дням закрытия, свежие сверху.
  const groups = (tab === 'today'
    ? [
        { key: 'overdue', title: t('Просрочено'), icon: AlertTriangle, tone: 'text-danger-600', tasks: overdue },
        { key: 'today', title: t('На сегодня'), icon: CalendarClock, tasks: today },
      ]
    : tab === 'future'
      ? [{ key: 'future', title: t('Запланировано'), icon: CalendarClock, tasks: future }]
      : historyGroups
  ).filter(group => group.tasks.length > 0)

  return (
    <div>
      <PageHeader
        title={t('Мои задачи на сегодня')}
        description={overdue.length > 0
          ? t('{n} просрочено, {m} на сегодня', { n: overdue.length, m: today.length })
          : t('{n} задач на сегодня', { n: today.length })}
        actions={canManage && <Button variant="primary" icon={Plus} onClick={() => setCreating(true)}>{t('Новая задача')}</Button>}
      />

      <Card padded={false} className="overflow-hidden">
        {/* Вкладки внутри списка — переключатель, а не вторая полоса вкладок под
            «Мои / Просроченные у команды»: два уровня не спорят друг с другом. */}
        <div className="border-b border-line px-4 py-3 sm:px-5">
          <div role="tablist" aria-label={t('Задачи')} className="flex w-full gap-1 rounded-lg bg-surface-muted p-1 sm:inline-flex sm:w-auto">
            {[
              { key: 'today', label: t('Сегодня и просроченные'), short: t('Сегодня'), count: overdue.length + today.length },
              { key: 'future', label: t('На будущее'), short: t('Будущие'), count: future.length },
              { key: 'history', label: t('История'), short: t('История'), count: history.count },
            ].map(item => (
              <button
                key={item.key}
                type="button"
                role="tab"
                aria-selected={tab === item.key}
                onClick={() => setTab(item.key)}
                className={cn(
                  'inline-flex min-w-0 flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-2 py-1.5 text-[13px] font-semibold transition sm:flex-none sm:px-3',
                  tab === item.key ? 'bg-surface text-brand-600 shadow-card ring-1 ring-line' : 'text-ink-muted hover:text-ink',
                )}
              >
                <span className="sm:hidden">{item.short}</span>
                <span className="hidden sm:inline">{item.label}</span>
                <span className={cn('rounded-full px-1.5 text-[11px]', tab === item.key ? 'bg-brand-50 text-brand-600' : 'bg-line text-ink-muted')}>{item.count}</span>
              </button>
            ))}
          </div>
        </div>

        {tab === 'history' && (
          <div className="flex flex-col gap-2 border-b border-line px-4 py-3 sm:px-5 lg:flex-row lg:items-center">
            <div role="radiogroup" aria-label={t('Период')} className="flex gap-1 overflow-x-auto">
              {HISTORY_PERIODS.map(period => (
                <button
                  key={period.value}
                  type="button"
                  role="radio"
                  aria-checked={historyFilters.period === period.value}
                  onClick={() => changeHistory({ period: period.value })}
                  className={cn(
                    'h-8 shrink-0 rounded-md border px-3 text-[13px] font-semibold transition',
                    historyFilters.period === period.value
                      ? 'border-brand-400 bg-brand-50 text-brand-600'
                      : 'border-line bg-surface text-ink-muted hover:text-ink',
                  )}
                >
                  {period.label}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-2 lg:flex">
              <Dropdown
                size="sm"
                ariaLabel={t('Статус')}
                value={historyFilters.status === HISTORY_DEFAULTS.status ? '' : historyFilters.status}
                onChange={value => changeHistory({ status: value || HISTORY_DEFAULTS.status })}
                options={HISTORY_STATUSES.map(item => ({ value: item.value === HISTORY_DEFAULTS.status ? '' : item.value, label: item.label }))}
                placeholder={HISTORY_STATUSES[0].label}
                className="lg:w-52"
              />
              <Dropdown
                size="sm"
                ariaLabel={t('Тип задачи')}
                value={historyFilters.type}
                onChange={value => changeHistory({ type: value })}
                options={[{ value: '', label: t('Все типы') }, ...TASK_TYPES.map(type => ({ value: type.value, label: type.label }))]}
                placeholder={t('Все типы')}
                className="lg:w-48"
              />
            </div>
            <SearchInput
              value={historyFilters.q}
              onChange={q => changeHistory({ q })}
              placeholder={t('Поиск: ребёнок, заявка, задача')}
              className="h-8 lg:ml-auto lg:w-64"
            />
          </div>
        )}

        {tab === 'history' && history.failed ? (
          <ErrorState onRetry={() => loadHistory()} />
        ) : visible.length === 0 ? (
          <EmptyState
            title={tab === 'history'
              ? (historyFiltered ? t('Ничего не нашлось') : t('За этот период закрытых задач нет'))
              : t('Задач нет')}
            description={tab === 'history'
              ? (historyFilters.period === 'all' ? t('Выполненные задачи появятся здесь.') : t('Выберите период побольше.'))
              : t('На сегодня всё сделано.')}
            action={tab === 'history' && historyFiltered && (
              <Button size="sm" onClick={() => setHistoryFilters(prev => ({ ...HISTORY_DEFAULTS, period: prev.period }))}>{t('Сбросить фильтры')}</Button>
            )}
            className="py-12"
          />
        ) : (
          groups.map(group => (
            <section key={group.key} className="border-b border-line last:border-b-0">
              <div className={cn('flex items-center gap-2 border-b border-line px-5 py-2.5', group.key === 'overdue' ? 'bg-danger-50/50' : 'bg-surface-muted')}>
                {group.icon && <group.icon className={cn('size-4', group.tone || 'text-ink-muted')} />}
                <p className={cn('text-[14px] font-bold', group.tone || 'text-ink')}>{group.title}</p>
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
                      canManage={canManage}
                      canPay={Boolean(user?.permissions?.can_accept_payments)}
                      onComplete={() => complete(task)}
                      onPostpone={() => postpone(task)}
                      onReassign={() => setReassigning(task)}
                      onPay={() => setPaying(task)}
                      onSell={() => setSelling(task)}
                      onDetails={() => openTask(task.id)}
                      onOpen={() => {
                        if (task.child) navigate(`/children/${task.child}`)
                        else if (task.lead) navigate(`/leads/${task.lead}`)
                      }}
                    />
                ))}
              </div>
            </section>
          ))
        )}

        {tab === 'history' && history.next && !history.failed && (
          <div className="flex flex-col items-center gap-2 border-t border-line px-5 py-4 sm:flex-row sm:justify-between">
            <p className="text-[13px] text-ink-muted">{t('Показано {shown} из {total}', { shown: history.rows.length, total: history.count })}</p>
            <Button size="sm" loading={loadingMore} onClick={showMore}>{t('Показать ещё')}</Button>
          </div>
        )}
      </Card>

      {openId && <TaskPanel taskId={openId} onClose={closeTask} onChanged={load} />}

      {creating && (
        <NewTaskModal
          onClose={() => setCreating(false)}
          onCreated={() => { setCreating(false); load() }}
        />
      )}

      {reassigning && (
        <Modal open onClose={() => setReassigning(null)} title={t('Передать задачу')}>
          <Field label={t('Кому передать')}>
            {({ id }) => (
              <Select id={id} defaultValue="" onChange={e => e.target.value && reassign(reassigning, e.target.value)}>
                <option value="" disabled>{t('Выберите сотрудника')}</option>
                {colleagues.map(c => <option key={c.id} value={c.id}>{c.full_name}{ROLE_LABELS[c.role] ? ` · ${ROLE_LABELS[c.role]()}` : ''}</option>)}
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

function TaskCard({ task, overdue: late, closed, closing, center, me, canManage, canPay, onComplete, onPostpone, onReassign, onPay, onSell, onOpen, onDetails }) {
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
            <button type="button" onClick={onDetails} className="text-left text-[15px] font-bold text-ink hover:text-brand-600">{taskTitle(task)}</button>
            {closed && <Badge tone={task.status === 'done' ? 'success' : 'neutral'}>{task.status_display}</Badge>}
            <CommentsCount count={task.comments_count} onClick={onDetails} />
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
          <CallButton phone={task.contact_phone} className="h-8 rounded-md px-2.5 text-[13px] font-semibold text-ink-muted hover:bg-surface hover:text-ink">
            <span className="hidden sm:inline">{t('Позвонить')}</span>
          </CallButton>
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
        {canPay && task.type === 'payment_reminder' && task.child && (
          <Button size="sm" variant="secondary" onClick={onPay}>{t('Принять оплату')}</Button>
        )}
        {canPay && task.type === 'renewal_offer' && task.child && (
          <Button size="sm" variant="secondary" onClick={onSell}>{t('Продать абонемент')}</Button>
        )}
        {digestLink && <a href={digestLink} className="inline-flex items-center text-sm font-semibold text-brand-600 hover:underline">{t('Открыть дайджест')}</a>}
        {!closed && (
          <div className="flex w-full items-center gap-1.5 sm:ml-auto sm:w-auto">
            {canManage && <Button size="sm" variant="ghost" icon={UserRoundPlus} onClick={onReassign}>{t('Передать')}</Button>}
            <Button size="sm" variant="ghost" icon={CalendarClock} onClick={onPostpone}>{t('На завтра')}</Button>
            <Button size="sm" variant="primary" loading={closing} onClick={onComplete} className="ml-auto sm:ml-0">{t('Выполнено')}</Button>
          </div>
        )}
      </div>
    </div>
  )
}
