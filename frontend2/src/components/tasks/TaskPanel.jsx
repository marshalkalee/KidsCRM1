import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarClock, CheckCircle2, ChevronRight, Pencil, Send, Trash2, UserRound, UserRoundPlus } from 'lucide-react'
import api from '../../api/axios'
import { useSession } from '../../session/SessionContext'
import { Badge, Button, ErrorState, Modal, Select, Skeleton, Textarea, apiErrorMessage, formatDateTime, useConfirm, useToast } from '../../ui'
import { t } from '../../i18n'
import { ROLE_LABELS, TASK_MANAGER_ROLES } from './types'

const MAX_COMMENT = 2000

/**
 * Карточка задачи (TRU-184): шапка (тип, срок, исполнитель, о ком), лента
 * истории и комментариев — новые внизу, поле комментария и быстрые кнопки.
 * Открывается со страницы «Задачи» (/tasks?open=<id>) и из вкладки «Задачи»
 * карточки ребёнка. На телефоне Modal выезжает снизу на всю ширину.
 * onChanged — задача изменилась (закрыта, перенесена, передана, новый
 * комментарий): список под панелью перечитывается.
 */
export default function TaskPanel({ taskId, onClose, onChanged }) {
  const { user, can } = useSession()
  const toast = useToast()
  const [task, setTask] = useState(null)
  const [items, setItems] = useState(null)
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(null)
  const [handover, setHandover] = useState(false)
  const endRef = useRef(null)

  const load = useCallback(() => {
    Promise.all([api.get(`tasks/${taskId}/`), api.get(`tasks/${taskId}/timeline/`)])
      .then(([taskResponse, timelineResponse]) => {
        setTask(taskResponse.data)
        setItems(timelineResponse.data.items)
        setError(false)
      })
      .catch(() => setError(true))
  }, [taskId])
  useEffect(() => { load() }, [load])

  // Новые внизу: при открытии и после отправки — к последней записи.
  useEffect(() => {
    if (items?.length) endRef.current?.scrollIntoView({ block: 'end' })
  }, [items])

  const changed = useCallback(() => { load(); onChanged?.() }, [load, onChanged])

  const canManage = TASK_MANAGER_ROLES.includes(user?.role)
  const mine = task && String(task.assigned_to) === String(user?.id)
  const open = task?.status === 'open'

  async function run(key, request, message) {
    setBusy(key)
    try {
      await request()
      toast.success(message)
      changed()
      return true
    } catch (err) {
      toast.error(apiErrorMessage(err))
      return false
    } finally {
      setBusy(null)
    }
  }

  function complete() {
    run('complete', () => api.post(`tasks/${taskId}/complete/`, { comment: '' }), t('Задача выполнена'))
  }

  function postpone() {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    run('postpone', () => api.patch(`tasks/${taskId}/`, { due_at: tomorrow.toISOString() }), t('Отложено на завтра'))
  }

  async function reassign(assigneeId) {
    const ok = await run('handover', () => api.patch(`tasks/${taskId}/`, { assigned_to: assigneeId }), t('Задача передана'))
    if (ok) setHandover(false)
  }

  const header = task && (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <Badge tone="neutral">{task.type_display}</Badge>
      {!open && <Badge tone={task.status === 'done' ? 'success' : 'neutral'}>{task.status_display}</Badge>}
      {task.due_at && (
        <span className="inline-flex items-center gap-1">
          <CalendarClock className="size-3.5" />
          {formatDateTime(task.due_at)}
        </span>
      )}
      <span className="inline-flex items-center gap-1">
        <UserRound className="size-3.5" />
        {task.assigned_to_name || t('не назначен')}
      </span>
    </span>
  )

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={task?.title || t('Задача')}
      description={header}
      footer={task && (
        <div className="flex w-full flex-col gap-2">
          <CommentForm taskId={taskId} onSent={changed} />
          {open && (canManage || mine) && (
            <div className="flex flex-wrap items-center gap-1.5">
              {canManage && (
                <Button size="sm" variant="ghost" icon={UserRoundPlus} onClick={() => setHandover(v => !v)}>{t('Передать')}</Button>
              )}
              <Button size="sm" variant="ghost" icon={CalendarClock} loading={busy === 'postpone'} onClick={postpone}>{t('На завтра')}</Button>
              <Button size="sm" variant="primary" icon={CheckCircle2} loading={busy === 'complete'} onClick={complete} className="ml-auto">{t('Выполнено')}</Button>
            </div>
          )}
          {handover && <HandoverSelect task={task} me={user?.id} disabled={busy === 'handover'} onPick={reassign} />}
        </div>
      )}
    >
      {error ? (
        <ErrorState onRetry={load} />
      ) : task === null ? (
        <Skeleton className="h-40" />
      ) : (
        <div className="flex flex-col gap-4">
          <About task={task} canOpenLead={can('can_manage_leads')} />
          {task.description && (
            <p className="whitespace-pre-line text-sm text-ink-muted">{task.description}</p>
          )}
          <div>
            <p className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-ink-subtle">{t('История и комментарии')}</p>
            <ol className="flex flex-col gap-2.5">
              {items.map((item, index) => (
                <TimelineItem key={item.comment?.id || `${item.at}-${index}`} item={item} taskId={taskId} onChanged={changed} />
              ))}
            </ol>
            <div ref={endRef} />
          </div>
        </div>
      )}
    </Modal>
  )
}

function About({ task, canOpenLead }) {
  if (task.link) {
    return (
      <Link to={task.link} className="inline-flex items-center gap-0.5 self-start text-sm font-semibold text-brand-600 hover:underline">
        {t('Открыть отметку посещаемости')}
        <ChevronRight className="size-4" />
      </Link>
    )
  }
  if (task.child) {
    return (
      <Link to={`/children/${task.child}`} className="inline-flex items-center gap-0.5 self-start text-sm font-semibold text-brand-600 hover:underline">
        {task.child_name}
        <ChevronRight className="size-4" />
      </Link>
    )
  }
  if (task.lead) {
    const label = t('Заявка: {name}', { name: task.lead_name || '—' })
    return canOpenLead ? (
      <Link to={`/leads/${task.lead}`} className="inline-flex items-center gap-0.5 self-start text-sm font-semibold text-brand-600 hover:underline">
        {label}
        <ChevronRight className="size-4" />
      </Link>
    ) : <p className="text-sm font-semibold text-ink">{label}</p>
  }
  return null
}

function TimelineItem({ item, taskId, onChanged }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(item.text)
  const [saving, setSaving] = useState(false)
  const comment = item.comment
  const url = comment && `tasks/${taskId}/comments/${comment.id}/`

  async function save() {
    if (!text.trim() || saving) return
    setSaving(true)
    try {
      await api.patch(url, { text })
      setEditing(false)
      onChanged()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  async function remove() {
    if (!await confirm({ title: t('Удалить комментарий?'), confirmText: t('Удалить'), danger: true })) return
    try {
      await api.delete(url)
      onChanged()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const meta = (
    <p className="text-xs text-ink-subtle">
      {[item.author_name, formatDateTime(item.at)].filter(Boolean).join(' · ')}
      {comment?.edited && ` · ${t('изменено')}`}
    </p>
  )

  if (!comment) {
    return (
      <li className="flex gap-2.5 px-1">
        <span className="mt-1.5 size-2 shrink-0 rounded-full bg-line-strong" />
        <div className="min-w-0">
          <p className="text-[13px] text-ink-muted">{item.text}</p>
          {meta}
        </div>
      </li>
    )
  }

  return (
    <li className="rounded-lg bg-surface-muted px-3 py-2">
      {editing ? (
        <div className="flex flex-col gap-2">
          <Textarea rows={2} maxLength={MAX_COMMENT} value={text} onChange={e => setText(e.target.value)} autoFocus />
          <div className="flex justify-end gap-1.5">
            <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setText(item.text) }}>{t('Отмена')}</Button>
            <Button size="sm" variant="primary" loading={saving} onClick={save}>{t('Сохранить')}</Button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-line break-words text-sm text-ink">{item.text}</p>
      )}
      <div className="mt-1 flex items-center gap-2">
        <div className="min-w-0 flex-1">{meta}</div>
        {comment.can_edit && !editing && (
          <>
            <button type="button" onClick={() => setEditing(true)} className="rounded p-1 text-ink-subtle hover:bg-surface hover:text-ink" aria-label={t('Изменить')}>
              <Pencil className="size-3.5" />
            </button>
            <button type="button" onClick={remove} className="rounded p-1 text-ink-subtle hover:bg-surface hover:text-danger-600" aria-label={t('Удалить')}>
              <Trash2 className="size-3.5" />
            </button>
          </>
        )}
      </div>
    </li>
  )
}

function CommentForm({ taskId, onSent }) {
  const toast = useToast()
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)

  async function send(e) {
    e?.preventDefault()
    if (!text.trim() || sending) return
    setSending(true)
    try {
      await api.post(`tasks/${taskId}/comments/`, { text })
      setText('')
      onSent()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <form onSubmit={send} className="flex items-end gap-2">
      <Textarea
        rows={2}
        maxLength={MAX_COMMENT}
        value={text}
        placeholder={t('Комментарий')}
        aria-label={t('Комментарий')}
        onChange={e => setText(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send(e) }}
        className="flex-1"
      />
      <Button type="submit" variant="primary" icon={Send} loading={sending} disabled={!text.trim()} aria-label={t('Отправить')}>
        <span className="hidden sm:inline">{t('Отправить')}</span>
      </Button>
    </form>
  )
}

function HandoverSelect({ task, me, disabled, onPick }) {
  const [colleagues, setColleagues] = useState(null)
  useEffect(() => {
    api.get('users/')
      .then(res => setColleagues((res.data.results || res.data).filter(u => u.is_active !== false && String(u.id) !== String(task.assigned_to))))
      .catch(() => setColleagues([]))
  }, [task.assigned_to])
  if (colleagues === null) return <Skeleton className="h-10" />
  return (
    <Select defaultValue="" disabled={disabled} aria-label={t('Кому передать')} onChange={e => e.target.value && onPick(e.target.value)}>
      <option value="" disabled>{t('Кому передать')}</option>
      {colleagues.map(c => (
        <option key={c.id} value={c.id}>
          {c.full_name}{String(c.id) === String(me) ? ` (${t('я')})` : ''}{ROLE_LABELS[c.role] ? ` · ${ROLE_LABELS[c.role]()}` : ''}
        </option>
      ))}
    </Select>
  )
}
