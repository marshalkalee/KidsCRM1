import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowRight, CalendarPlus, ListTodo, MessageCircle, Pencil, Phone, SearchX, Send, Trash2, UserRound, UserRoundPlus,
  ArrowRight, CalendarPlus, ListTodo, MessageCircle, Pencil, Phone, SearchX, Send, Sparkles, Trash2, UserRound,
} from 'lucide-react'
import api from '../api/axios'
import LeadConversionModal from '../components/leads/LeadConversionModal'
import LeadModal from '../components/leads/LeadModal'
import { AIMessageModal, useAI } from '../components/ai/ai'
import { LeadGroups } from '../components/ai/assist'
import RejectModal from '../components/leads/RejectModal'
import TrialBookingModal from '../components/leads/TrialBookingModal'
import { LEAD_STATUS, LEAD_STATUSES, leadTitle } from '../components/leads/format'
import { getLeadsViewPreference } from '../components/leads/viewPreference'
import { useSession } from '../session/SessionContext'
import {
  Avatar, Badge, Button, Card, Dropdown, EmptyState, ErrorState, PageHeader, Skeleton, Textarea, ageLabel, apiErrorMessage, cn,
  formatDateTime, useConfirm, useToast,
} from '../ui'
import { t } from '../i18n'

/** Готовый текст первого сообщения в WhatsApp (ТЗ п. 4.5). */
function whatsappUrl(lead, organizationName) {
  const about = lead.direction_name ? t(' на {direction}', { direction: lead.direction_name }) : ''
  const text = t('Здравствуйте, {name}! Это {org}. Вы оставляли заявку{about} — удобно обсудить занятия?', {
    name: lead.parent_name, org: organizationName || 'KidsCRM', about,
  })
  return `https://wa.me/${lead.phone.replace(/\D/g, '')}?text=${encodeURIComponent(text)}`
}

/**
 * Карточка заявки (TRU-96) — рабочее место менеджера перед звонком и
 * после. Слева: как связаться и что известно; справа: статус и переходы,
 * лента комментариев, история статусов. На телефоне — одна колонка.
 */
export default function LeadDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const toast = useToast()
  const confirm = useConfirm()
  const { user } = useSession()
  const [lead, setLead] = useState(null)
  const [state, setState] = useState('loading')
  const [history, setHistory] = useState([])
  const [comments, setComments] = useState([])
  const [editing, setEditing] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [bookingTrial, setBookingTrial] = useState(false)
  const [converting, setConverting] = useState(false)
  const [staff, setStaff] = useState([])
  const [writing, setWriting] = useState(false)
  const ai = useAI()

  const loadExtras = useCallback(() => {
    api.get(`leads/${id}/history/`).then(res => setHistory(res.data)).catch(() => {})
    api.get(`leads/${id}/comments/`).then(res => setComments(res.data)).catch(() => {})
  }, [id])

  const load = useCallback(() => {
    api.get(`leads/${id}/`)
      .then(res => {
        setLead(res.data)
        setState('ready')
        if (res.data.status === 'trial_attended' && !res.data.converted_child) setConverting(true)
      })
      .catch(err => setState(err.response?.status === 404 ? 'missing' : 'error'))
    loadExtras()
  }, [id, loadExtras])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    api.get('users/').then(res => setStaff((res.data.results || res.data).filter(u => ['owner', 'manager', 'admin'].includes(u.role) && u.is_active !== false))).catch(() => {})
  }, [])

  const storedReturnTo = location.state?.leadsReturnTo
  const leadsReturnTo = typeof storedReturnTo === 'string' && storedReturnTo.startsWith('/leads')
    ? storedReturnTo
    : `/leads?view=${getLeadsViewPreference()}`
  const back = { to: leadsReturnTo, label: t('Заявки') }
  if (state === 'loading') {
    return (
      <div>
        <PageHeader title={<Skeleton className="h-8 w-56" />} back={back} />
        <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]"><Skeleton className="h-64" /><Skeleton className="h-64" /></div>
      </div>
    )
  }
  if (state === 'missing') {
    return <Card><EmptyState icon={SearchX} title={t('Заявка не найдена')} description={t('Возможно, её удалили или ссылка неверная.')} action={<Button to={leadsReturnTo}>{t('К заявкам')}</Button>} /></Card>
  }
  if (state === 'error') return <Card><ErrorState onRetry={load} /></Card>

  async function changeStatus(to, extra = {}) {
    try {
      const res = await api.post(`leads/${lead.id}/status/`, { status: to, ...extra })
      setLead(res.data)
      if (to === 'trial_attended' && !res.data.converted_child) setConverting(true)
      loadExtras()
      toast.success(t('Статус: {status}', { status: LEAD_STATUS[to].label }))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  async function reassign(userId) {
    try {
      const res = await api.patch(`leads/${lead.id}/`, { assigned_to: userId || null })
      setLead(res.data)
      toast.success(t('Ответственный изменён'))
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  async function remove() {
    const ok = await confirm({ title: t('Удалить заявку?'), message: t('Заявка «{name}» пропадёт из воронки.', { name: leadTitle(lead) }), confirmText: t('Удалить'), danger: true })
    if (!ok) return
    try {
      await api.delete(`leads/${lead.id}/`)
      toast.success(t('Заявка удалена'))
      navigate(leadsReturnTo, { replace: true })
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const meta = LEAD_STATUS[lead.status]
  return (
    <div>
      <PageHeader
        back={back}
        title={leadTitle(lead)}
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            {lead.kind === 'renewal' && <Badge tone="info">{t('Продление')}</Badge>}
            <Badge tone={meta.tone} dot>{meta.label}</Badge>
            <span className={cn(lead.is_stale && 'font-semibold text-warning-600')}>
              {lead.days_in_status === 0 ? t('в статусе с сегодня') : t('в статусе {n} дн.', { n: lead.days_in_status })}
            </span>
            <span className="text-ink-subtle">{t('создана {date}', { date: formatDateTime(lead.created_at) })}</span>
          </span>
        }
        actions={
          <>
            <Button icon={Pencil} onClick={() => setEditing(true)}>{t('Редактировать')}</Button>
            <Button variant="danger-ghost" size="icon" onClick={remove} aria-label={t('Удалить заявку')}><Trash2 className="size-4" /></Button>
          </>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)] lg:items-start">
        <aside className="space-y-4 lg:sticky lg:top-24">
          <Card>
            <p className="text-[15px] font-bold text-ink">{t('Связаться')}</p>
            <p className="mt-1 text-sm text-ink-muted">{lead.parent_name} · <a href={`tel:${lead.phone}`} className="font-medium text-ink hover:text-brand-700">{lead.phone}</a></p>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <a href={`tel:${lead.phone}`} className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-brand-600 text-sm font-semibold text-white shadow-card hover:bg-brand-700">
                <Phone className="size-4" /> {t('Позвонить')}
              </a>
              <a href={whatsappUrl(lead, user?.organization_name)} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-success-50 text-sm font-semibold text-success-600 hover:brightness-95">
                <MessageCircle className="size-4" /> WhatsApp
              </a>
            </div>
            {ai.enabled && (
              <button
                type="button"
                onClick={() => setWriting(true)}
                className="mt-2 inline-flex h-10 w-full items-center justify-center gap-2 rounded-md border border-[#ddd6fe] bg-[#faf5ff] text-sm font-semibold text-[#7c3aed] hover:bg-[#f3e8ff]"
              >
                <Sparkles className="size-4" /> {t('Написать с ИИ')}
              </button>
            )}
          </Card>

          <Card>
            <p className="text-[15px] font-bold text-ink">{t('О заявке')}</p>
            <dl className="mt-2 divide-y divide-line text-sm">
              <Row label={t('Ребёнок')}>
                {lead.child
                  ? <Link to={`/children/${lead.child}`} className="text-brand-600 hover:underline">{lead.renewal_child_name}</Link>
                  : lead.child_name || '—'}
                {lead.child_age != null && <span className="text-ink-muted"> · {ageLabel(lead.child_age)}</span>}
              </Row>
              <Row label={t('Направление')}>{lead.direction_name || '—'}</Row>
              <Row label={t('Филиал')}>{lead.branch_name || '—'}</Row>
              {lead.kind !== 'renewal' && <Row label={t('Источник')}>{lead.source_name ? t(lead.source_name) : '—'}</Row>}
              <div className="flex items-center justify-between gap-3 py-2.5">
                <dt className="text-ink-subtle">{t('Ответственный')}</dt>
                <dd className="w-44">
                  <Dropdown
                    size="sm"
                    value={lead.assigned_to || ''}
                    onChange={reassign}
                    ariaLabel={t('Ответственный')}
                    options={[{ value: '', label: t('Не назначен') }, ...staff.map(u => ({ value: u.id, label: u.full_name }))]}
                  />
                </dd>
              </div>
            </dl>
          </Card>

          {!lead.converted_child && lead.kind !== 'renewal' && <LeadGroups leadId={lead.id} />}

          {lead.converted_child && (
            <Card>
              <p className="text-[15px] font-bold text-ink">{t('Стал клиентом')}</p>
              <Link to={`/children/${lead.converted_child}`} className="mt-2 flex items-center gap-3 rounded-md px-1 py-1.5 hover:bg-surface-muted">
                <Avatar name={lead.converted_child_name} />
                <span className="flex-1 font-semibold text-ink">{lead.converted_child_name}</span>
                <ArrowRight className="size-4 text-ink-subtle" />
              </Link>
            </Card>
          )}
        </aside>

        <div className="min-w-0 space-y-6">
          {lead.trial_booking && <TrialBookingCard booking={lead.trial_booking} />}
          {lead.status === 'trial_attended' && !lead.converted_child && (
            <Card className="border-brand-200 bg-[linear-gradient(135deg,#fff7f5,#ffffff)]">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="font-bold text-ink">{t('Пробное посещено — оформите клиента')}</p>
                  <p className="mt-1 text-sm text-ink-muted">{t('Проверьте дубли и дополните обязательные данные ребёнка и родителя.')}</p>
                </div>
                <Button variant="primary" icon={UserRoundPlus} onClick={() => setConverting(true)}>{t('Оформить клиента')}</Button>
              </div>
            </Card>
          )}
          <StatusCard
            lead={lead}
            onBookTrial={() => setBookingTrial(true)}
            onChange={to => (to === 'rejected' ? setRejecting(true) : changeStatus(to))}
          />
          <CommentsCard leadId={lead.id} comments={comments} onAdded={comment => setComments(list => [...list, comment])} />
          <HistoryCard history={history} />
        </div>
      </div>

      {writing && <AIMessageModal lead={lead} onClose={() => setWriting(false)} />}
      {editing && <LeadModal lead={lead} onClose={() => setEditing(false)} onSaved={saved => { setLead(saved); setEditing(false) }} />}
      {bookingTrial && (
        <TrialBookingModal
          lead={lead}
          onClose={() => setBookingTrial(false)}
          onEdit={() => {
            setBookingTrial(false)
            setEditing(true)
          }}
          onBooked={saved => {
            setLead(saved)
            setBookingTrial(false)
            loadExtras()
          }}
        />
      )}
      {converting && (
        <LeadConversionModal
          lead={lead}
          onClose={() => setConverting(false)}
          onConverted={saved => {
            setLead(saved)
            setConverting(false)
            loadExtras()
          }}
        />
      )}
      {rejecting && (
        <RejectModal
          lead={lead}
          onCancel={() => setRejecting(false)}
          onConfirm={async extra => { setRejecting(false); await changeStatus('rejected', extra) }}
        />
      )}
    </div>
  )
}

function Row({ label, children }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2.5">
      <dt className="text-ink-subtle">{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium text-ink">{children}</dd>
    </div>
  )
}

function TrialBookingCard({ booking }) {
  return (
    <Card className="border-brand-200 bg-[linear-gradient(135deg,#fff7f5,#ffffff)]">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <CalendarPlus className="size-5 text-brand-600" />
            <p className="font-bold text-ink">{t('Пробное занятие назначено')}</p>
            <Badge tone="warning">{t('Пробное')}</Badge>
          </div>
          <p className="mt-2 text-[15px] font-semibold text-ink">{booking.group_name}</p>
          <p className="mt-1 text-sm text-ink-muted">
            {formatDateTime(booking.starts_at_local)}–{booking.ends_at_local.slice(11, 16)} · {booking.branch_name}
            {booking.room_name ? ` · ${booking.room_name}` : ''}
          </p>
          {booking.teacher_name && <p className="mt-1 text-xs text-ink-subtle">{booking.teacher_name}</p>}
        </div>
        <Button
          to={`/schedule?date=${booking.starts_at_local.slice(0, 10)}&view=day&lesson=${booking.lesson_id}`}
          icon={CalendarPlus}
        >
          {t('Открыть в календаре')}
        </Button>
      </div>
    </Card>
  )
}

function StatusCard({ lead, onChange, onBookTrial }) {
  const targets = LEAD_STATUSES.filter(
    s => s.value !== 'trial_scheduled' && lead.allowed_transitions.includes(s.value),
  )
  const canBookTrial = lead.kind !== 'renewal'
    && !lead.trial_booking
    && lead.allowed_transitions.includes('trial_scheduled')
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[15px] font-bold text-ink">{t('Что дальше')}</p>
        {lead.status === 'rejected' && lead.rejection_reason_name && (
          <span className="text-[13px] text-ink-muted">{t('Причина отказа')}: <span className="font-semibold text-danger-600">{t(lead.rejection_reason_name)}</span>{lead.rejection_comment && ` — ${lead.rejection_comment}`}</span>
        )}
      </div>
      {targets.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {targets.map(s => (
            <Button key={s.value} size="sm" variant={s.value === 'rejected' ? 'danger-ghost' : 'secondary'} onClick={() => onChange(s.value)}>
              <span className={cn('size-2 rounded-full', s.dot)} />
              {s.label}
            </Button>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-ink-muted">{t('Заявка закрыта покупкой — дальше это клиент.')}</p>
      )}
      <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
        {lead.kind !== 'renewal' && (
          <Button
            size="sm"
            variant="ghost"
            icon={CalendarPlus}
            disabled={!canBookTrial}
            onClick={onBookTrial}
          >
            {lead.trial_booking ? t('Пробное назначено') : t('Записать на пробное')}
          </Button>
        )}
        <Button size="sm" variant="ghost" icon={ListTodo} disabled title={t('Появится вместе с модулем задач')}>{t('Создать задачу')}</Button>
      </div>
    </Card>
  )
}

function CommentsCard({ leadId, comments, onAdded }) {
  const toast = useToast()
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!text.trim()) return
    setSaving(true)
    try {
      const res = await api.post(`leads/${leadId}/comments/`, { text })
      onAdded(res.data)
      setText('')
    } catch (err) {
      toast.error(apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card>
      <p className="text-[15px] font-bold text-ink">{t('Комментарии')}</p>
      {comments.length === 0 ? (
        <p className="mt-2 text-sm text-ink-muted">{t('Пока пусто. Запишите, о чём договорились после звонка.')}</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {comments.map(comment => (
            <li key={comment.id} className="flex gap-3">
              <Avatar name={comment.author_name || '?'} className="!size-7 !text-[10px]" />
              <div className="min-w-0 flex-1 rounded-lg bg-surface-muted px-3 py-2">
                <p className="text-xs text-ink-subtle"><span className="font-semibold text-ink-muted">{comment.author_name}</span> · {formatDateTime(comment.created_at)}</p>
                <p className="mt-0.5 whitespace-pre-line text-sm text-ink">{comment.text}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="mt-3 flex items-end gap-2">
        <Textarea rows={2} value={text} onChange={e => setText(e.target.value)} placeholder={t('Новый комментарий')} aria-label={t('Новый комментарий')} className="flex-1" maxLength={2000} />
        <Button type="submit" variant="primary" size="icon" loading={saving} disabled={!text.trim()} aria-label={t('Добавить комментарий')}><Send className="size-4" /></Button>
      </form>
    </Card>
  )
}

function HistoryCard({ history }) {
  return (
    <Card>
      <p className="text-[15px] font-bold text-ink">{t('История статусов')}</p>
      <ol className="mt-3 space-y-0">
        {[...history].reverse().map((change, index) => {
          const to = LEAD_STATUS[change.to_status]
          return (
            <li key={change.id} className="relative flex gap-3 pb-4 last:pb-0">
              {index < history.length - 1 && <span className="absolute left-[5px] top-4 h-full w-px bg-line" />}
              <span className={cn('relative mt-1.5 size-[11px] shrink-0 rounded-full ring-4 ring-surface', to.dot)} />
              <div className="min-w-0 text-sm">
                <p className="text-ink">
                  {change.from_status ? (
                    <><span className="text-ink-muted">{LEAD_STATUS[change.from_status].label}</span> → <span className="font-semibold">{to.label}</span></>
                  ) : (
                    <span className="font-semibold">{t('Заявка создана')}</span>
                  )}
                </p>
                <p className="text-xs text-ink-subtle">
                  {formatDateTime(change.changed_at)}
                  {change.changed_by_name ? ` · ${change.changed_by_name}` : ` · ${t('система')}`}
                </p>
                {change.rejection_reason_name && <p className="mt-0.5 text-xs text-danger-600">{t('Причина')}: {t(change.rejection_reason_name)}{change.comment && ` — ${change.comment}`}</p>}
                {!change.rejection_reason_name && change.comment && <p className="mt-0.5 text-xs text-ink-muted">{change.comment}</p>}
              </div>
            </li>
          )
        })}
      </ol>
      {history.length === 0 && <p className="mt-2 flex items-center gap-2 text-sm text-ink-muted"><UserRound className="size-4" />{t('Истории пока нет')}</p>}
    </Card>
  )
}
