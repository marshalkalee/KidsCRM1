import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronRight, Mail, MessageCircle, Pencil, Phone, SearchX, Trash2 } from 'lucide-react'
import api from '../api/axios'
import ParentModal from '../components/ParentModal'
import { Communications } from '../components/communications/Communications'
import {
  Avatar, Badge, Button, CHILD_STATUSES, CONTACT_ROLES, Card, CardHeader, EmptyState, ErrorState, PageHeader,
  Skeleton, ageLabel, apiErrorMessage, cn, formatDateTime, money, plural, useConfirm, useToast,
} from '../ui'

const PHONE_TYPES = { mobile: 'мобильный', work: 'рабочий', home: 'домашний' }
const PAYMENTS_PREVIEW = 5

/**
 * Карточка родителя (TRU-83, по блокам — TRU-89). Слева «кто это и как
 * связаться» и деньги, справа — дети и история общения. На телефоне — одна
 * колонка в том же порядке. Телефоны и деньги сервер не присылает ролям без
 * прав (can_view_phone / can_view_client_money) — тогда блоков просто нет.
 */
export default function ParentDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const confirm = useConfirm()
  const [card, setCard] = useState(null)
  const [status, setStatus] = useState('loading')
  const [editing, setEditing] = useState(false)

  const load = useCallback(() => {
    api.get(`clients/parents/${id}/card/`)
      .then(r => { setCard(r.data); setStatus('ready') })
      .catch(err => setStatus(err.response?.status === 404 ? 'missing' : 'error'))
  }, [id])

  useEffect(() => { load() }, [load])

  const back = { to: '/parents', label: 'Родители' }
  if (status === 'loading') {
    return (
      <div>
        <PageHeader title={<Skeleton className="h-8 w-56" />} back={back} />
        <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)]"><Skeleton className="h-64" /><Skeleton className="h-64" /></div>
      </div>
    )
  }
  if (status === 'missing') {
    return (
      <Card>
        <EmptyState icon={SearchX} title="Родитель не найден" description="Возможно, запись удалили или ссылка неверная." action={<Button to="/parents">К списку родителей</Button>} />
      </Card>
    )
  }
  if (status === 'error') return <Card><ErrorState onRetry={load} /></Card>

  const { parent, children, permissions } = card
  const roles = [...new Set(children.map(c => CONTACT_ROLES[c.role] || c.role))]

  async function remove() {
    if (children.length) {
      toast.error('Сначала отвяжите детей — в карточке каждого ребёнка, вкладка «Контакты».')
      return
    }
    const ok = await confirm({ title: 'Удалить родителя?', message: `${parent.full_name} пропадёт из списка родителей.`, confirmText: 'Удалить', danger: true })
    if (!ok) return
    try {
      await api.delete(`clients/parents/${parent.id}/`)
      toast.success('Родитель удалён')
      navigate('/parents', { replace: true })
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  return (
    <div>
      <PageHeader
        back={back}
        title={parent.full_name}
        description={[roles.join(', '), `${children.length} ${plural(children.length, ['ребёнок', 'ребёнка', 'детей'])}`].filter(Boolean).join(' · ')}
        actions={permissions.can_edit && (
          <>
            <Button icon={Pencil} onClick={() => setEditing(true)}>Редактировать</Button>
            <Button variant="danger-ghost" size="icon" onClick={remove} aria-label="Удалить родителя"><Trash2 className="size-4" /></Button>
          </>
        )}
      />

      <div className="grid gap-6 lg:grid-cols-[340px_minmax(0,1fr)] lg:items-start">
        <aside className="space-y-4 lg:sticky lg:top-24">
          <ContactsCard parent={parent} />
          {card.money && <MoneyCard money={card.money} />}
        </aside>

        <div className="min-w-0 space-y-6">
          <ChildrenCard kids={children} />
          <section>
            <h2 className="mb-3 text-[15px] font-bold text-ink">Коммуникации</h2>
            <Communications
              stacked
              params={{ family: parent.id }}
              canCreate={permissions.can_log_communications}
              childOptions={children.map(c => ({ id: c.id, full_name: c.full_name }))}
              fixedContact={parent.id}
              showChild
            />
          </section>
        </div>
      </div>

      {editing && (
        <ParentModal parent={parent} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); load() }} />
      )}
    </div>
  )
}

function ContactsCard({ parent }) {
  const phones = parent.phones // нет в ответе — роли без can_view_phone
  const whatsapp = parent.whatsapp || phones?.[0]?.number
  return (
    <Card>
      <p className="text-[15px] font-bold text-ink">Связаться</p>
      {phones ? (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {phones[0] && (
              <a href={`tel:${phones[0].number}`} className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-brand-600 text-sm font-semibold text-white shadow-card hover:bg-brand-700">
                <Phone className="size-4" /> Позвонить
              </a>
            )}
            {whatsapp && (
              <a href={`https://wa.me/${whatsapp.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-success-50 text-sm font-semibold text-success-600 hover:brightness-95">
                <MessageCircle className="size-4" /> WhatsApp
              </a>
            )}
          </div>
          <dl className="mt-4 divide-y divide-line border-t border-line text-sm">
            {phones.map(phone => (
              <Row key={phone.number} icon={Phone} label={PHONE_TYPES[phone.phone_type] || 'телефон'}>
                <a href={`tel:${phone.number}`} className="hover:text-brand-700">{phone.number}</a>
              </Row>
            ))}
            {parent.whatsapp && parent.whatsapp !== phones[0]?.number && (
              <Row icon={MessageCircle} label="WhatsApp">{parent.whatsapp}</Row>
            )}
            {parent.email && (
              <Row icon={Mail} label="email"><a href={`mailto:${parent.email}`} className="break-all hover:text-brand-700">{parent.email}</a></Row>
            )}
          </dl>
        </>
      ) : (
        <p className="mt-3 rounded-md bg-surface-muted px-3 py-2 text-[13px] text-ink-muted">Телефоны скрыты для вашей роли.</p>
      )}
    </Card>
  )
}

function Row({ icon: Icon, label, children }) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <Icon className="size-4 shrink-0 text-ink-subtle" />
      <dd className="min-w-0 flex-1 font-medium text-ink">{children}</dd>
      <dt className="text-xs text-ink-subtle">{label}</dt>
    </div>
  )
}

function MoneyCard({ money: summary }) {
  const [showAll, setShowAll] = useState(false)
  const hasDebt = Number(summary.total_debt) > 0
  const payments = showAll ? summary.payments : summary.payments.slice(0, PAYMENTS_PREVIEW)
  return (
    <Card padded={false}>
      <div className={cn('rounded-t-lg px-5 py-4', hasDebt ? 'bg-danger-50' : 'bg-success-50')}>
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">Долг по всем детям</p>
        <p className={cn('mt-0.5 text-2xl font-bold', hasDebt ? 'text-danger-600' : 'text-success-600')}>{hasDebt ? money(summary.total_debt) : 'Нет долга'}</p>
      </div>
      <div className="px-5 pb-4 pt-3">
        <p className="text-[13px] font-semibold text-ink">Оплаты</p>
        {summary.payments.length === 0 ? (
          <p className="mt-2 text-sm text-ink-muted">Оплат пока нет.</p>
        ) : (
          <ul className="mt-1 divide-y divide-line">
            {payments.map(payment => (
              <li key={payment.id} className="flex items-baseline justify-between gap-3 py-2 text-sm">
                <div className="min-w-0">
                  <p className="truncate text-ink">{payment.child_name.split(' ').slice(-1)[0]} · <span className="text-ink-muted">{payment.subscription_name}</span></p>
                  <p className="text-xs text-ink-subtle">{formatDateTime(payment.paid_at)} · {payment.method_label}</p>
                </div>
                <span className="shrink-0 font-semibold text-ink">{money(payment.amount)}</span>
              </li>
            ))}
          </ul>
        )}
        {summary.payments.length > PAYMENTS_PREVIEW && (
          <button type="button" onClick={() => setShowAll(v => !v)} className="mt-1 text-[13px] font-semibold text-brand-700 hover:underline">
            {showAll ? 'Свернуть' : `Все оплаты (${summary.payments.length})`}
          </button>
        )}
      </div>
    </Card>
  )
}

function ChildrenCard({ kids }) {
  return (
    <Card padded={false}>
      <CardHeader className="mb-0 px-5 pt-5" title="Дети" />
      {kids.length === 0 ? (
        <p className="px-5 pb-5 pt-2 text-sm text-ink-muted">Дети не привязаны. Привязать можно в карточке ребёнка, вкладка «Контакты».</p>
      ) : (
        <ul className="mt-3 divide-y divide-line border-t border-line">
          {kids.map(child => {
            const childStatus = CHILD_STATUSES[child.status] || { label: child.status, tone: 'neutral' }
            return (
              <li key={child.id}>
                <Link to={`/children/${child.id}`} className="group flex items-center gap-3 px-5 py-3.5 hover:bg-surface-muted/60">
                  <Avatar name={child.full_name} size="md" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold text-ink group-hover:text-brand-700">{child.full_name}</p>
                    <p className="truncate text-[13px] text-ink-muted">{ageLabel(child.age)}{child.branch_names && ` · ${child.branch_names}`}</p>
                  </div>
                  <div className="hidden shrink-0 flex-wrap justify-end gap-1.5 sm:flex">
                    {child.is_payer && <Badge tone="brand">Плательщик</Badge>}
                    <Badge tone={childStatus.tone} dot>{childStatus.label}</Badge>
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-ink-subtle group-hover:text-brand-600" />
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
