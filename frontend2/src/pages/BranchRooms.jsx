import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Check, DoorOpen, Pencil, Plus, Trash2, X } from 'lucide-react'
import api from '../api/axios'
import { useSession } from '../session/SessionContext'
import { Button, Card, EmptyState, ErrorState, Input, PageHeader, Skeleton, apiErrorMessage, useConfirm, useToast } from '../ui'
import { t } from '../i18n'

/**
 * Залы филиала (TRU-85) — нужны для проверки конфликтов расписания.
 * Добавить и переименовать — прямо в списке, без модалок. Менять залы
 * могут все, кроме бухгалтера (RoomViewSet: IsNotAccountant).
 */
export default function BranchRooms() {
  const { id } = useParams()
  const { user } = useSession()
  const toast = useToast()
  const confirm = useConfirm()
  const canManage = user?.role !== 'accountant'
  const [branch, setBranch] = useState(null)
  const [rooms, setRooms] = useState(null)
  const [error, setError] = useState(false)
  const [editingId, setEditingId] = useState(null)

  const load = useCallback(() => {
    Promise.all([api.get(`branches/${id}/`), api.get('rooms/', { params: { branch: id } })])
      .then(([b, r]) => { setBranch(b.data); setRooms(r.data.results || r.data); setError(false) })
      .catch(() => setError(true))
  }, [id])
  useEffect(() => { load() }, [load])

  async function save(room, values) {
    try {
      if (room) await api.patch(`rooms/${room.id}/`, values)
      else await api.post('rooms/', { ...values, branch: id })
      toast.success(room ? t('Зал сохранён') : t('Зал добавлен'))
      setEditingId(null)
      load()
      return true
    } catch (err) {
      const data = err.response?.data
      toast.error(data?.name?.[0] || data?.capacity?.[0] || apiErrorMessage(err))
      return false
    }
  }

  async function remove(room) {
    const ok = await confirm({ title: t('Удалить зал «{name}»?', { name: room.name }), message: t('Прошедшие занятия в этом зале останутся в истории.'), confirmText: t('Удалить'), danger: true })
    if (!ok) return
    try {
      await api.delete(`rooms/${room.id}/`)
      toast.success(t('Зал удалён'))
      load()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  const back = { to: '/branches', label: t('Филиалы') }
  if (error) return <><PageHeader title={t('Залы')} back={back} /><Card><ErrorState onRetry={load} /></Card></>
  if (!rooms) return <><PageHeader title={<Skeleton className="h-8 w-56" />} back={back} /><Skeleton className="h-48 max-w-2xl" /></>

  return (
    <div>
      <PageHeader title={t('Залы — {name}', { name: branch.name })} description={t('По залам система ловит накладки в расписании.')} back={back} />
      <Card padded={false} className="max-w-2xl">
        {rooms.length === 0 && !canManage && <EmptyState icon={DoorOpen} title={t('Залов пока нет')} />}
        <ul className="divide-y divide-line">
          {rooms.map(room => (
            <li key={room.id} className="px-5 py-3">
              {editingId === room.id ? (
                <RoomForm room={room} onSave={values => save(room, values)} onCancel={() => setEditingId(null)} />
              ) : (
                <div className="flex items-center gap-3">
                  <DoorOpen className="size-4 shrink-0 text-ink-subtle" />
                  <span className="flex-1 font-medium text-ink">{room.name}</span>
                  <span className="text-sm text-ink-muted">{room.capacity ? t('до {n} чел.', { n: room.capacity }) : t('вместимость не указана')}</span>
                  {canManage && (
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" aria-label={t('Изменить')} onClick={() => setEditingId(room.id)}><Pencil className="size-4" /></Button>
                      <Button variant="danger-ghost" size="icon" aria-label={t('Удалить')} onClick={() => remove(room)}><Trash2 className="size-4" /></Button>
                    </div>
                  )}
                </div>
              )}
            </li>
          ))}
          {canManage && (
            <li className="bg-surface-muted/50 px-5 py-3">
              <RoomForm key={rooms.length} onSave={values => save(null, values)} />
            </li>
          )}
        </ul>
      </Card>
    </div>
  )
}

function RoomForm({ room, onSave, onCancel }) {
  const [name, setName] = useState(room?.name || '')
  const [capacity, setCapacity] = useState(room?.capacity ?? '')
  const [saving, setSaving] = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    const ok = await onSave({ name: name.trim(), capacity: capacity === '' ? null : Number(capacity) })
    setSaving(false)
    if (ok && !room) { setName(''); setCapacity('') }
  }

  return (
    <form onSubmit={submit} className="flex flex-wrap items-center gap-2">
      <Input aria-label={t('Название зала')} placeholder={room ? '' : t('Новый зал, например «Большой»')} className="h-9 min-w-40 flex-1" value={name} onChange={e => setName(e.target.value)} autoFocus={Boolean(room)} />
      <Input aria-label={t('Вместимость')} type="number" min={1} placeholder={t('Мест')} className="h-9 w-24" value={capacity} onChange={e => setCapacity(e.target.value)} />
      {room ? (
        <>
          <Button variant="primary" size="icon" type="submit" aria-label={t('Сохранить')} loading={saving}><Check className="size-4" /></Button>
          <Button variant="ghost" size="icon" aria-label={t('Отмена')} onClick={onCancel}><X className="size-4" /></Button>
        </>
      ) : (
        <Button variant="primary" size="sm" className="h-9" type="submit" icon={Plus} loading={saving} disabled={!name.trim()}>{t('Добавить')}</Button>
      )}
    </form>
  )
}
