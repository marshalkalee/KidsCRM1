import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Archive, ArchiveRestore, Building2, DoorOpen, Pencil, Plus } from 'lucide-react'
import api from '../api/axios'
import BranchModal from '../components/BranchModal'
import { hoursSummary } from '../components/workingHours'
import { useSession } from '../session/SessionContext'
import { Badge, Button, DataTable, EmptyState, PageHeader, apiErrorMessage, cn, plural, useConfirm, useToast } from '../ui'
import { t } from '../i18n'

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
        title: t('Архивировать «{name}»?', { name: branch.name }),
        message: t('Филиал пропадёт из выбора в шапке и из новых записей. История занятий и оплат сохранится, филиал можно вернуть.'),
        confirmText: t('Архивировать'),
        danger: true,
      })
      if (!ok) return
    }
    try {
      await api.patch(`branches/${branch.id}/`, { is_active: !branch.is_active })
      toast.success(branch.is_active ? t('Филиал в архиве') : t('Филиал восстановлен'))
      load()
      reloadSession()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const active = branches?.filter(b => b.is_active) || []
  // Архивные — внизу, как в первом React: одна таблица со статусом.
  const rows = [...active, ...(branches?.filter(b => !b.is_active) || [])]

  const columns = [
    { key: 'name', header: t('Название'), primary: true, render: b => <span className={cn('font-semibold', b.is_active ? 'text-ink' : 'text-ink-muted')}>{b.name}</span> },
    { key: 'address', header: t('Адрес'), className: 'text-ink-muted', render: b => b.address || '—' },
    { key: 'phone', header: t('Телефон'), hideOnMobile: true, className: 'text-ink-muted whitespace-nowrap', render: b => b.phone || '—' },
    { key: 'hours', header: t('Часы работы'), hideOnMobile: true, className: 'text-ink-muted', render: b => hoursSummary(b.working_hours) },
    {
      key: 'rooms',
      header: t('Залы'),
      render: b => (
        <Link to={`/branches/${b.id}/rooms`} onClick={e => e.stopPropagation()} className="inline-flex items-center gap-1.5 font-semibold text-brand-600 hover:underline">
          <DoorOpen className="size-3.5" />{b.rooms_count ?? 0}
        </Link>
      ),
    },
    { key: 'status', header: t('Статус'), mobileAside: true, render: b => (b.is_active ? <Badge tone="success">{t('Активен')}</Badge> : <Badge>{t('В архиве')}</Badge>) },
    {
      key: 'actions',
      header: '',
      align: 'right',
      render: b => (
        <span className="inline-flex gap-1" onClick={e => e.stopPropagation()}>
          <Button variant="ghost" size="icon" aria-label={t('Изменить')} onClick={() => setEditing(b)}><Pencil className="size-4" /></Button>
          <Button variant="ghost" size="icon" aria-label={b.is_active ? t('В архив') : t('Восстановить')} onClick={() => toggleArchive(b)}>
            {b.is_active ? <Archive className="size-4" /> : <ArchiveRestore className="size-4" />}
          </Button>
        </span>
      ),
    },
  ]

  return (
    <div>
      <PageHeader
        title={t('Филиалы')}
        description={branches ? `${active.length} ${plural(active.length, ['активный филиал', 'активных филиала', 'активных филиалов'])}` : t('Загрузка…')}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Новый филиал')}</Button>}
      />
      <DataTable
        columns={columns}
        rows={rows}
        loading={!branches && !error}
        error={error}
        onRetry={load}
        onRowClick={b => setEditing(b)}
        empty={<EmptyState icon={Building2} title={t('Филиалов пока нет')} description={t('Добавьте первый филиал — затем залы в нём и направления.')} action={<Button variant="primary" icon={Plus} onClick={() => setEditing('new')}>{t('Новый филиал')}</Button>} />}
      />
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
