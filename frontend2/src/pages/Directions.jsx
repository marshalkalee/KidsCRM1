import { useCallback, useEffect, useMemo, useState } from 'react'
import { Archive, ArchiveRestore, Pencil, Plus, Tag } from 'lucide-react'
import api from '../api/axios'
import DirectionModal from '../components/DirectionModal'
import { Badge, Button, Checkbox, DataTable, EmptyState, PageHeader, apiErrorMessage, plural, useToast } from '../ui'

function ageRange(d) {
  if (d.age_min != null && d.age_max != null) return `${d.age_min}–${d.age_max} лет`
  if (d.age_min != null) return `от ${d.age_min} лет`
  if (d.age_max != null) return `до ${d.age_max} лет`
  return 'любой'
}

/** Направления (TRU-85): архивация вместо удаления — история групп и
 * абонементов по направлению остаётся. */
export default function Directions() {
  const toast = useToast()
  const [directions, setDirections] = useState(null)
  const [branches, setBranches] = useState([])
  const [error, setError] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
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
      toast.success(direction.is_active ? 'Направление в архиве' : 'Направление восстановлено')
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const archivedCount = directions?.filter(d => !d.is_active).length || 0
  const rows = (directions || []).filter(d => showArchived || d.is_active)
  const activeCount = (directions || []).length - archivedCount

  const columns = [
    {
      key: 'name',
      header: 'Направление',
      primary: true,
      render: d => (
        <span className="flex items-center gap-2.5">
          <span className="size-3 shrink-0 rounded-full" style={{ backgroundColor: d.color || '#9aa3ad' }} />
          <span className="font-semibold text-ink">{d.name}</span>
          {!d.is_active && <Badge>В архиве</Badge>}
        </span>
      ),
    },
    { key: 'age', header: 'Возраст', render: d => <span className="text-ink-muted">{ageRange(d)}</span> },
    {
      key: 'branches',
      header: 'Филиалы',
      render: d => (d.branches.length
        ? <span className="flex flex-wrap gap-1">{d.branches.map(id => <Badge key={id}>{branchName[id] || '…'}</Badge>)}</span>
        : <span className="text-ink-subtle">не выбраны</span>),
    },
    {
      key: 'actions',
      header: '',
      align: 'right',
      mobileAside: true,
      render: d => (
        <span className="inline-flex gap-1" onClick={e => e.stopPropagation()}>
          <Button variant="ghost" size="icon" aria-label="Изменить" onClick={() => setEditing(d)}><Pencil className="size-4" /></Button>
          <Button variant="ghost" size="icon" aria-label={d.is_active ? 'В архив' : 'Восстановить'} onClick={() => toggleArchive(d)}>
            {d.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}
          </Button>
        </span>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title="Направления"
        description={directions ? `${activeCount} ${plural(activeCount, ['направление', 'направления', 'направлений'])}` : 'Загрузка…'}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>Добавить направление</Button>}
      />
      {archivedCount > 0 && (
        <Checkbox className="mb-4" label={`Показать архивные (${archivedCount})`} checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />
      )}
      <DataTable
        columns={columns}
        rows={rows}
        loading={!directions && !error}
        error={error}
        onRetry={load}
        onRowClick={d => setEditing(d)}
        empty={<EmptyState icon={Tag} title="Направлений пока нет" description="Балет, растяжка, хореография — по ним строятся группы и абонементы." action={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>Добавить направление</Button>} />}
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
