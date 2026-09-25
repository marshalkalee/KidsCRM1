import { useCallback, useEffect, useMemo, useState } from 'react'
import { Archive, ArchiveRestore, Pencil, Plus, Tag } from 'lucide-react'
import api from '../api/axios'
import DirectionModal from '../components/DirectionModal'
import { Badge, Button, DataTable, EmptyState, PageHeader, apiErrorMessage, plural, useToast } from '../ui'
import { t } from '../i18n'

function ageRange(d) {
  if (d.age_min != null && d.age_max != null) return t('{from}–{to} лет', { from: d.age_min, to: d.age_max })
  if (d.age_min != null) return t('от {n} лет', { n: d.age_min })
  if (d.age_max != null) return t('до {n} лет', { n: d.age_max })
  return t('любой')
}

/** Направления (TRU-85): архивация вместо удаления — история групп и
 * абонементов по направлению остаётся. */
export default function Directions() {
  const toast = useToast()
  const [directions, setDirections] = useState(null)
  const [branches, setBranches] = useState([])
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)

  const load = useCallback(() => {
    Promise.all([api.get('directions/'), api.get('branches/')])
      .then(([d, b]) => {
        setDirections(d.data.results || d.data)
        setBranches(b.data.results || b.data)
        setError(false)
      })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  const branchName = useMemo(() => Object.fromEntries(branches.map(b => [b.id, b.name])), [branches])

  async function toggleArchive(direction) {
    try {
      await api.patch(`directions/${direction.id}/`, { is_active: !direction.is_active })
      toast.success(direction.is_active ? t('Направление в архиве') : t('Направление восстановлено'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const archivedCount = directions?.filter(d => !d.is_active).length || 0
  // Архивные — внизу, со статусом (как в первом React), без отдельного переключателя.
  const rows = [...(directions || []).filter(d => d.is_active), ...(directions || []).filter(d => !d.is_active)]
  const activeCount = (directions || []).length - archivedCount

  const columns = [
    {
      key: 'name',
      header: t('Направление'),
      primary: true,
      render: d => (
        <span className="flex items-center gap-2.5">
          <span className="size-3 shrink-0 rounded-full" style={{ backgroundColor: d.color || '#9aa3ad' }} />
          <span className="font-semibold text-ink">{d.name}</span>
        </span>
      ),
    },
    { key: 'age', header: t('Возраст'), render: d => <span className="text-ink-muted">{ageRange(d)}</span> },
    {
      key: 'branches',
      header: t('Филиалы'),
      render: d => (d.branches.length
        ? <span className="flex flex-wrap gap-1">{d.branches.map(id => <Badge key={id}>{branchName[id] || '…'}</Badge>)}</span>
        : <span className="text-ink-subtle">{t('не выбраны')}</span>),
    },
    { key: 'status', header: t('Статус'), mobileAside: true, render: d => (d.is_active ? <Badge tone="success">{t('Активно')}</Badge> : <Badge>{t('В архиве')}</Badge>) },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: d => (
        <span className="inline-flex gap-1" onClick={e => e.stopPropagation()}>
          <Button variant="ghost" size="icon" aria-label={t('Изменить')} onClick={() => setEditing(d)}><Pencil className="size-4" /></Button>
          <Button variant="ghost" size="icon" aria-label={d.is_active ? t('В архив') : t('Восстановить')} onClick={() => toggleArchive(d)}>
            {d.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}
          </Button>
        </span>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title={t('Направления')}
        description={directions ? `${activeCount} ${plural(activeCount, ['направление', 'направления', 'направлений'])}` : t('Загрузка…')}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Новое направление')}</Button>}
      />
      <DataTable
        columns={columns}
        rows={rows}
        loading={!directions && !error}
        error={error}
        onRetry={load}
        onRowClick={d => setEditing(d)}
        empty={<EmptyState icon={Tag} title={t('Направлений пока нет')} description={t('Балет, растяжка, хореография — по ним строятся группы и абонементы.')} action={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Добавить направление')}</Button>} />}
      />
      {editing && (
        <DirectionModal
          direction={editing === 'new' ? null : editing}
          branches={branches}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load() }}
        />
      )}
    </div>
  )
}
