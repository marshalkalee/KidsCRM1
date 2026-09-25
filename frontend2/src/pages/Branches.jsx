import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Archive, ArchiveRestore, Building2, Clock, DoorOpen, MapPin, Pencil, Phone, Plus } from 'lucide-react'
import api from '../api/axios'
import BranchModal from '../components/BranchModal'
import { hoursSummary } from '../components/workingHours'
import { useSession } from '../session/SessionContext'
import { Badge, Button, Card, Checkbox, EmptyState, ErrorState, PageHeader, Skeleton, apiErrorMessage, cn, plural, useConfirm, useToast } from '../ui'

/**
 * Филиалы (TRU-85): карточки с часами работы и залами. Архивация — PATCH
 * is_active (не удаление): архивный филиал пропадает из переключателя в
 * шапке, но его история остаётся.
 */
export default function Branches() {
  const toast = useToast()
  const confirm = useConfirm()
  const { reload: reloadSession } = useSession()
  const [branches, setBranches] = useState(null)
  const [error, setError] = useState(false)
  const [showArchived, setShowArchived] = useState(false)
  const [editing, setEditing] = useState(null) // null | 'new' | branch

  const load = useCallback(() => {
    api.get('branches/')
      .then(r => { setBranches(r.data.results || r.data); setError(false) })
      .catch(() => setError(true))
  }, [])
  useEffect(() => { load() }, [load])

  async function toggleArchive(branch) {
    if (branch.is_active) {
      const ok = await confirm({
        title: `Архивировать «${branch.name}»?`,
        message: 'Филиал пропадёт из выбора в шапке и из новых записей. История занятий и оплат сохранится, филиал можно вернуть.',
        confirmText: 'Архивировать',
        danger: true,
      })
      if (!ok) return
    }
    try {
      await api.patch(`branches/${branch.id}/`, { is_active: !branch.is_active })
      toast.success(branch.is_active ? 'Филиал в архиве' : 'Филиал восстановлен')
      load()
      reloadSession()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const active = branches?.filter(b => b.is_active) || []
  const archived = branches?.filter(b => !b.is_active) || []
  const shown = showArchived ? [...active, ...archived] : active

  return (
    <div>
      <PageHeader
        title="Филиалы"
        description={branches ? `${active.length} ${plural(active.length, ['активный филиал', 'активных филиала', 'активных филиалов'])}` : 'Загрузка…'}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>Добавить филиал</Button>}
      />
      {archived.length > 0 && (
        <Checkbox className="mb-4" label={`Показать архивные (${archived.length})`} checked={showArchived} onChange={e => setShowArchived(e.target.checked)} />
      )}
      {error && <Card><ErrorState onRetry={load} /></Card>}
      {!error && !branches && <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"><Skeleton className="h-48" /><Skeleton className="h-48" /></div>}
      {branches && shown.length === 0 && (
        <Card>
          <EmptyState icon={Building2} title="Филиалов пока нет" description="Добавьте первый филиал — затем залы в нём и направления." action={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>Добавить филиал</Button>} />
        </Card>
      )}
      {shown.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {shown.map(branch => (
            <Card key={branch.id} className={cn('flex flex-col gap-3', !branch.is_active && 'opacity-70')}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-base font-bold text-ink">{branch.name}</p>
                  {!branch.is_active && <Badge className="mt-1">В архиве</Badge>}
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button variant="ghost" size="icon" aria-label="Изменить" onClick={() => setEditing(branch)}><Pencil className="size-4" /></Button>
                  <Button variant="ghost" size="icon" aria-label={branch.is_active ? 'В архив' : 'Восстановить'} onClick={() => toggleArchive(branch)}>
                    {branch.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}
                  </Button>
                </div>
              </div>
              <ul className="space-y-1.5 text-[13px] text-ink-muted">
                {branch.address && <li className="flex gap-2"><MapPin className="mt-0.5 size-3.5 shrink-0" />{branch.address}</li>}
                {branch.phone && <li className="flex gap-2"><Phone className="mt-0.5 size-3.5 shrink-0" />{branch.phone}</li>}
                <li className="flex gap-2"><Clock className="mt-0.5 size-3.5 shrink-0" />{hoursSummary(branch.working_hours)}</li>
              </ul>
              <Link to={`/branches/${branch.id}/rooms`} className="mt-auto flex items-center justify-between rounded-md bg-surface-muted px-3 py-2 text-sm font-medium text-ink hover:bg-brand-50 hover:text-brand-700">
                <span className="flex items-center gap-2"><DoorOpen className="size-4" /> Залы</span>
                <span className="text-ink-muted">{branch.rooms_count ?? 0}</span>
              </Link>
            </Card>
          ))}
        </div>
      )}
      {editing && (
        <BranchModal
          branch={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); reloadSession() }}
        />
      )}
    </div>
  )
}
