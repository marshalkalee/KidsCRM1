import { useCallback, useEffect, useState } from 'react'
import { Archive, ArchiveRestore, Pencil, Plus, Tag } from 'lucide-react'
import api from '../api/axios'
import SubscriptionTypeModal from '../components/SubscriptionTypeModal'
import { Badge, Button, DataTable, PageHeader, apiErrorMessage, money, plural, useToast } from '../ui'
import { t } from '../i18n'

export default function SubscriptionTypes() {
  const toast = useToast()
  const [types, setTypes] = useState(null)
  const [directions, setDirections] = useState([])
  const [branches, setBranches] = useState([])
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = useCallback(() => {
    Promise.all([api.get('subscriptions/subscription-types/'), api.get('directions/'), api.get('branches/')])
      .then(([tp, d, b]) => {
        setTypes(tp.data.results || tp.data)
        setDirections(d.data.results || d.data)
        setBranches(b.data.results || b.data)
        setError(false)
      })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  async function toggleArchive(type) {
    try {
      await api.patch(`subscriptions/subscription-types/${type.id}/`, { is_active: !type.is_active })
      toast.success(type.is_active ? t('Тип абонемента в архиве') : t('Тип абонемента восстановлен'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const directionName = Object.fromEntries(directions.map(d => [d.id, d.name]))
  const activeCount = (types || []).filter(tp => tp.is_active).length
  const rows = [...(types || []).filter(tp => tp.is_active), ...(types || []).filter(tp => !tp.is_active)]

  const columns = [
    { key: 'name', header: t('Название'), primary: true, render: tp => <span className="font-semibold text-ink">{tp.name}</span> },
    { key: 'price', header: t('Цена'), render: tp => money(tp.price) },
    { key: 'sessions', header: t('Занятий'), render: tp => tp.is_unlimited ? t('Безлимит') : tp.quota_sessions },
    { key: 'duration_days', header: t('Срок, дней') },
    {
      key: 'directions', header: t('Направления'),
      render: tp => (tp.directions.length
        ? <span className="flex flex-wrap gap-1">{tp.directions.map(id => <Badge key={id}>{directionName[id] || '…'}</Badge>)}</span>
        : <span className="text-ink-subtle">{t('не выбраны')}</span>),
    },
    { key: 'status', header: t('Статус'), mobileAside: true, render: tp => (tp.is_active ? <Badge tone="success">{t('Активен')}</Badge> : <Badge>{t('В архиве')}</Badge>) },
    {
      key: 'actions', header: '', align: 'right',
      render: tp => (
        <span className="inline-flex gap-1" onClick={e => e.stopPropagation()}>
          <Button variant="ghost" size="icon" aria-label={t('Изменить')} onClick={() => setEditing(tp)}><Pencil className="size-4" /></Button>
          <Button variant="ghost" size="icon" aria-label={tp.is_active ? t('В архив') : t('Восстановить')} onClick={() => toggleArchive(tp)}>
            {tp.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}
          </Button>
        </span>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title={t('Типы абонементов')}
        description={types ? `${activeCount} ${plural(activeCount, ['тип', 'типа', 'типов'])}` : t('Загрузка…')}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Новый тип')}</Button>}
      />
      <DataTable columns={columns} rows={rows} loading={!types && !error} error={error} onRetry={load} icon={Tag} />
      {editing && (
        <SubscriptionTypeModal
          type={editing === 'new' ? null : editing}
          directions={directions}
          branches={branches}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }}
        />
      )}
    </div>
  )
}