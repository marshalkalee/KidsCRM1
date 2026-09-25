import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronRight, Mail, MessageCircle, Pencil, Phone, SearchX, Trash2, Wallet } from 'lucide-react'
import api from '../api/axios'
import ParentModal from '../components/ParentModal'
import { Communications } from '../components/communications/Communications'
import {
  Avatar, Badge, Button, CHILD_STATUSES, CONTACT_ROLES, Card, CardHeader, EmptyState, ErrorState, PageHeader,
  Skeleton, ageLabel, apiErrorMessage, cn, formatDateTime, money, useConfirm, useToast,
} from '../ui'

/**
 * Карточка родителя (TRU-83): все его дети из любых филиалов, звонок и
 * WhatsApp в один клик, долг и оплаты по всем детям (только роли с
 * can_view_client_money — сервер присылает money: null остальным),
 * сводная лента коммуникаций по семье.
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

  const back = { to: '/parents', label: 'Все родители' }
  if (status === 'loading') {
    return (
      <div>
        <PageHeader title={<Skeleton className="h-8 w-56" />} back={back} />
        <Skeleton className="h-40" />
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
  const phones = parent.phones // нет в ответе — роли без can_view_phone
  const whatsapp = parent.whatsapp || phones?.[0]?.number

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
        actions={permissions.can_edit && (
          <>
            <Button icon={Pencil} onClick={() => setEditing(true)}>Редактировать</Button>
            <Button variant="danger-ghost" icon={Trash2} onClick={remove} aria-label="Удалить родителя">
              <span className="sm:hidden">Удалить</span>
            </Button>
          </>
        )}
      />

      <div className="mb-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="flex items-start gap-4">
            <Avatar name={parent.full_name} size="lg" />
            <div className="min-w-0 flex-1 space-y-3">
              {phones ? (
                <div className="flex flex-wrap gap-2">
                  {phones.map(phone => (
                    <a key={phone.number} href={`tel:${phone.number}`} className="inline-flex items-center gap-2 rounded-md bg-brand-600 px-3.5 py-2 text-sm font-semibold text-white shadow-card hover:bg-brand-700">
                      <Phone className="size-4" /> {phone.number}
                    </a>
                  ))}
                  {whatsapp && (
                    <a href={`https://wa.me/${whatsapp.replace(/\D/g, '')}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-md bg-success-50 px-3.5 py-2 text-sm font-semibold text-success-600 hover:brightness-95">
                      <MessageCircle className="size-4" /> WhatsApp
                    </a>
                  )}
                </div>
              ) : (
                <p className="text-sm text-ink-muted">Телефоны скрыты для вашей роли.</p>
              )}
              {parent.email && (
                <a href={`mailto:${parent.email}`} className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-brand-700">
                  <Mail className="size-4" /> {parent.email}
                </a>
              )}
            </div>
          </div>
        </Card>
        {card.money && <DebtCard debt={card.money.total_debt} />}
      </div>

      <section className="mb-6">
        <h2 className="mb-3 text-[15px] font-bold text-ink">Дети <span className="font-normal text-ink-subtle">{children.length}</span></h2>
        {children.length === 0 ? (
          <Card><p className="text-sm text-ink-muted">Дети не привязаны. Привязать можно в карточке ребёнка, вкладка «Контакты».</p></Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {children.map(child => {
              const childStatus = CHILD_STATUSES[child.status] || { label: child.status, tone: 'neutral' }
              return (
                <Link key={child.id} to={`/children/${child.id}`} className="group flex min-w-0 items-center gap-3 rounded-lg border border-line bg-surface p-4 shadow-card transition-colors hover:border-brand-200">
                  <Avatar name={child.full_name} size="md" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-semibold text-ink group-hover:text-brand-700">{child.full_name}</p>
                    <p className="truncate text-[13px] text-ink-muted">{ageLabel(child.age)}{child.branch_names && ` · ${child.branch_names}`}</p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      <Badge>{CONTACT_ROLES[child.role] || child.role}</Badge>
                      {child.is_payer && <Badge tone="brand">Плательщик</Badge>}
                      {child.status !== 'active' && <Badge tone={childStatus.tone}>{childStatus.label}</Badge>}
                    </div>
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-ink-subtle group-hover:text-brand-600" />
                </Link>
              )
            })}
          </div>
        )}
      </section>

      {card.money && (
        <section className="mb-6">
          <Card padded={false}>
            <CardHeader className="mb-0 px-5 pt-5" title="История оплат" description="По абонементам всех детей, последние 50" />
            <Payments payments={card.money.payments} />
          </Card>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-[15px] font-bold text-ink">Коммуникации</h2>
        <Communications
          params={{ family: parent.id }}
          canCreate={permissions.can_log_communications}
          childOptions={children.map(c => ({ id: c.id, full_name: c.full_name }))}
          fixedContact={parent.id}
          showChild
        />
      </section>

      {editing && (
        <ParentModal parent={parent} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); load() }} />
      )}
    </div>
  )
}

function DebtCard({ debt }) {
  const hasDebt = Number(debt) > 0
  return (
    <Card className={cn('flex items-center gap-4', hasDebt ? 'border-danger-50 bg-danger-50' : 'border-success-50 bg-success-50')}>
      <span className={cn('flex size-11 items-center justify-center rounded-full bg-surface', hasDebt ? 'text-danger-600' : 'text-success-600')}>
        <Wallet className="size-5" />
      </span>
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">Долг по всем детям</p>
        <p className={cn('text-2xl font-bold', hasDebt ? 'text-danger-600' : 'text-success-600')}>{hasDebt ? money(debt) : 'Нет долга'}</p>
      </div>
    </Card>
  )
}

function Payments({ payments }) {
  if (!payments.length) return <p className="px-5 pb-5 pt-3 text-sm text-ink-muted">Оплат пока нет.</p>
  return (
    <ul className="mt-3 divide-y divide-line border-t border-line">
      {payments.map(payment => (
        <li key={payment.id} className="flex items-center justify-between gap-4 px-5 py-3 text-sm">
          <div className="min-w-0">
            <p className="truncate font-medium text-ink">{payment.child_name} · <span className="font-normal text-ink-muted">{payment.subscription_name}</span></p>
            <p className="text-xs text-ink-subtle">{formatDateTime(payment.paid_at)} · {payment.method_label}</p>
          </div>
          <span className="shrink-0 font-semibold text-ink">{money(payment.amount)}</span>
        </li>
      ))}
    </ul>
  )
}
