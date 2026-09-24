import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Building2, CalendarClock, Clock3, Layers, Pencil, SearchX, Sparkles, Users, Wallet } from 'lucide-react'
import api from '../api/axios'
import ChildModal from '../components/ChildModal'
import { visibleChildCardTabs } from '../components/child-card/tabs'
import { useSession } from '../session/SessionContext'
import {
  Avatar, Badge, Button, CHILD_STATUSES, Card, EmptyState, ErrorState, PageHeader, Skeleton, Tabs,
  ageLabel, cn, formatDate, money,
} from '../ui'

const GENDERS = { female: 'Девочка', male: 'Мальчик' }

/**
 * Карточка ребёнка (TRU-82): шапка из GET children/<id>/card/ и вкладки из
 * реестра components/child-card/tabs.js — вкладки других доменов
 * подключаются там, эта страница их не знает.
 */
export default function ChildDetail() {
  const { id } = useParams()
  const { can } = useSession()
  const [params, setParams] = useSearchParams()
  const [card, setCard] = useState(null)
  const [status, setStatus] = useState('loading') // loading | ready | missing | error
  const [editing, setEditing] = useState(false)
  const [counts, setCounts] = useState({})

  const load = useCallback(() => {
    api.get(`clients/children/${id}/card/`)
      .then(r => { setCard(r.data); setStatus('ready') })
      .catch(err => setStatus(err.response?.status === 404 ? 'missing' : 'error'))
  }, [id])

  useEffect(() => { load() }, [load])

  const tabs = useMemo(() => visibleChildCardTabs(can), [can])
  const activeKey = tabs.some(t => t.key === params.get('tab')) ? params.get('tab') : tabs[0].key
  const activeTab = tabs.find(t => t.key === activeKey)
  // Стабильные колбэки на вкладку — иначе вкладка перезагружала бы данные
  // на каждый рендер карточки.
  const countSetters = useMemo(
    () => Object.fromEntries(tabs.map(tab => [tab.key, n => setCounts(c => (c[tab.key] === n ? c : { ...c, [tab.key]: n }))])),
    [tabs],
  )

  const back = { to: '/children', label: 'Все дети' }
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
        <EmptyState icon={SearchX} title="Ребёнок не найден" description="Возможно, запись удалили или ссылка неверная." action={<Button to="/children">К списку детей</Button>} />
      </Card>
    )
  }
  if (status === 'error') return <Card><ErrorState onRetry={load} /></Card>

  const { child, permissions } = card
  const childStatus = CHILD_STATUSES[child.status] || { label: child.status, tone: 'neutral' }
  const TabComponent = activeTab.component

  return (
    <div>
      <PageHeader
        back={back}
        title={child.full_name}
        actions={permissions.can_edit && <Button icon={Pencil} onClick={() => setEditing(true)}>Редактировать</Button>}
      />

      <Card className="mb-6">
        <div className="flex flex-col gap-5 md:flex-row md:items-start">
          <Avatar name={child.full_name} src={child.photo_url} size="lg" />
          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-ink-muted">
              <Badge tone={childStatus.tone} dot>{childStatus.label}</Badge>
              <span>{ageLabel(child.age)} · {formatDate(child.birth_date)}</span>
              {GENDERS[child.gender] && <span>{GENDERS[child.gender]}</span>}
            </div>
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
              <Fact icon={Building2} label="Филиал" values={card.branches.map(b => b.name)} />
              <Fact icon={Layers} label="Направления" values={card.directions.map(d => d.name)} />
              <Fact icon={Users} label="Группы" values={card.groups.map(g => g.name)} />
            </dl>
            {child.status === 'left' && child.leave_reason && (
              <p className="text-sm text-ink-muted"><span className="font-semibold text-ink">Причина ухода:</span> {child.leave_reason}</p>
            )}
          </div>
        </div>

        {(child.medical_notes || card.money) && (
          <div className="mt-5 grid gap-3 border-t border-line pt-5 md:grid-cols-3">
            {card.money && <SubscriptionTile subscription={card.money.subscription} />}
            {card.money && <DebtTile debt={card.money.debt} />}
            {child.medical_notes && (
              <div className="flex gap-3 rounded-lg bg-warning-50 p-3.5">
                <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning-600" />
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-wide text-warning-600">Здоровье</p>
                  <p className="mt-0.5 whitespace-pre-line text-sm text-ink">{child.medical_notes}</p>
                </div>
              </div>
            )}
          </div>
        )}
      </Card>

      <Tabs
        className="mb-4"
        tabs={tabs.map(tab => ({ key: tab.key, label: tab.label, count: counts[tab.key] }))}
        value={activeKey}
        onChange={key => setParams(key === tabs[0].key ? {} : { tab: key }, { replace: true })}
      />
      {TabComponent ? (
        <TabComponent key={activeKey} child={child} card={card} permissions={permissions} onCountChange={countSetters[activeKey]} />
      ) : (
        <Card>
          <EmptyState icon={Sparkles} title={`Раздел «${activeTab.label}» скоро появится`} description="Мы уже работаем над ним — данные подтянутся сюда автоматически." />
        </Card>
      )}

      {editing && (
        <ChildModal
          child={child}
          onClose={() => setEditing(false)}
          onSaved={() => { setEditing(false); load() }}
        />
      )}
    </div>
  )
}

function Fact({ icon: Icon, label, values }) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1.5 text-xs text-ink-subtle"><Icon className="size-3.5" />{label}</dt>
      <dd className="mt-0.5 text-ink">{values.length ? values.join(', ') : <span className="text-ink-subtle">—</span>}</dd>
    </div>
  )
}

const TILE_TONES = {
  neutral: ['bg-surface-muted', 'text-ink-subtle'],
  danger: ['bg-danger-50', 'text-danger-600'],
  success: ['bg-success-50', 'text-success-600'],
}

function Tile({ icon: Icon, label, tone = 'neutral', children }) {
  const [background, iconColor] = TILE_TONES[tone]
  return (
    <div className={cn('flex gap-3 rounded-lg p-3.5', background)}>
      <Icon className={cn('mt-0.5 size-4 shrink-0', iconColor)} />
      <div className="min-w-0">
        <p className="text-xs font-semibold uppercase tracking-wide text-ink-subtle">{label}</p>
        {children}
      </div>
    </div>
  )
}

function SubscriptionTile({ subscription }) {
  if (!subscription) {
    return (
      <Tile icon={CalendarClock} label="Абонемент">
        <p className="mt-0.5 text-sm text-ink-muted">Нет абонемента</p>
      </Tile>
    )
  }
  return (
    <Tile icon={CalendarClock} label="Абонемент">
      <p className="mt-0.5 truncate text-sm font-semibold text-ink">{subscription.name}</p>
      <p className="text-[13px] text-ink-muted">
        до {formatDate(subscription.ends_on)}
        {subscription.sessions_remaining != null && ` · осталось ${subscription.sessions_remaining}`}
      </p>
    </Tile>
  )
}

function DebtTile({ debt }) {
  const hasDebt = Number(debt) > 0
  return (
    <Tile icon={hasDebt ? Wallet : Clock3} label="Долг" tone={hasDebt ? 'danger' : 'success'}>
      <p className={cn('mt-0.5 text-lg font-bold', hasDebt ? 'text-danger-600' : 'text-success-600')}>
        {hasDebt ? money(debt) : 'Нет долга'}
      </p>
    </Tile>
  )
}
