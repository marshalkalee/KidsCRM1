import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import api from '../../api/axios'
import { Button, Field, Input, Modal, Select, apiErrorMessage, useConfirm, useToast } from '../../ui'
import { t } from '../../i18n'

const listOf = response => response.data.results || response.data
const weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']

function emptySlot() {
  return {
    id: null,
    weekday: 0,
    start_time: '18:00',
    duration_minutes: 60,
    room: '',
    teacher: '',
  }
}

/** Постоянные недельные слоты группы; сервер сам поддерживает календарь заполненным вперёд. */
export default function FixedScheduleModal({ group, onClose, onSaved }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [slots, setSlots] = useState([])
  const [rooms, setRooms] = useState([])
  const [teachers, setTeachers] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [hasSchedule, setHasSchedule] = useState(false)

  useEffect(() => {
    let alive = true
    Promise.all([
      api.get(`groups/${group.id}/fixed-schedule/`),
      api.get('rooms/', { params: { branch: group.branch } }),
      api.get('users/', { params: { role: 'teacher' } }),
    ])
      .then(([schedule, roomList, teacherList]) => {
        if (!alive) return
        const loadedSlots = schedule.data.slots || []
        setHasSchedule(loadedSlots.length > 0)
        setSlots(loadedSlots.length ? loadedSlots.map(slot => ({ ...slot, room: slot.room || '', teacher: slot.teacher || '' })) : [emptySlot()])
        setRooms(listOf(roomList))
        setTeachers(listOf(teacherList))
      })
      .catch(error => toast.error(apiErrorMessage(error)))
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [group.branch, group.id, toast])

  function setSlot(index, key, value) {
    setSlots(current => current.map((slot, i) => (i === index ? { ...slot, [key]: value } : slot)))
  }

  function removeSlot(index) {
    setSlots(current => current.filter((_, i) => i !== index))
  }

  async function save(e) {
    e.preventDefault()
    setSaving(true)
    try {
      const response = await api.put(`groups/${group.id}/fixed-schedule/`, {
        generate_weeks_ahead: 8,
        slots: slots.map(slot => ({
          ...(slot.id ? { id: slot.id } : {}),
          weekday: Number(slot.weekday),
          start_time: slot.start_time,
          duration_minutes: Number(slot.duration_minutes),
          room: slot.room || null,
          teacher: slot.teacher || null,
        })),
      })
      const generated = response.data.generated_count || 0
      toast.success(generated ? t('Расписание сохранено, создано занятий: {count}', { count: generated }) : t('Расписание сохранено'))
      onSaved()
    } catch (error) {
      toast.error(apiErrorMessage(error, t('Не удалось сохранить расписание')))
    } finally {
      setSaving(false)
    }
  }

  async function clear() {
    const ok = await confirm({
      title: t('Удалить постоянное расписание?'),
      message: t('Будущие занятия, которые не изменяли вручную, исчезнут из календаря.'),
      confirmText: t('Удалить расписание'),
      danger: true,
    })
    if (!ok) return
    setSaving(true)
    try {
      await api.put(`groups/${group.id}/fixed-schedule/`, { generate_weeks_ahead: 8, slots: [] })
      toast.success(t('Постоянное расписание удалено'))
      onSaved()
    } catch (error) {
      toast.error(apiErrorMessage(error, t('Не удалось удалить расписание')))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="xl"
      title={t('Постоянное расписание')}
      description={t('Занятия автоматически появятся в календаре на восемь недель вперёд. Горизонт расписания обновляется ежедневно.')}
      footer={!loading && (
        <>
          {hasSchedule && <Button variant="danger-ghost" onClick={clear} disabled={saving} className="sm:mr-auto">{t('Удалить расписание')}</Button>}
          <Button onClick={onClose} disabled={saving}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="fixed-schedule-form" loading={saving} disabled={!slots.length}>{t('Сохранить')}</Button>
        </>
      )}
    >
      {loading ? (
        <p className="py-8 text-center text-sm text-ink-muted">{t('Загрузка…')}</p>
      ) : (
        <form id="fixed-schedule-form" onSubmit={save} className="space-y-3 [&_label]:whitespace-nowrap [&_label]:text-[9px] [&_label]:tracking-[0.03em]">
          {slots.map((slot, index) => (
            <div key={slot.id || `new-${index}`} className="rounded-xl border border-line bg-surface-muted p-3.5">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-12">
                <Field label={t('День недели')} required className="lg:col-span-3">
                  {({ id }) => (
                    <Select id={id} value={String(slot.weekday)} onChange={e => setSlot(index, 'weekday', e.target.value)} required>
                      {weekdays.map((day, value) => <option key={day} value={String(value)}>{t(day)}</option>)}
                    </Select>
                  )}
                </Field>
                <Field label={t('Время')} required className="lg:col-span-2">
                  {({ id }) => <Input id={id} type="time" value={slot.start_time} onChange={e => setSlot(index, 'start_time', e.target.value)} required />}
                </Field>
                <Field label={t('Длительность, мин.')} required className="lg:col-span-2">
                  {({ id }) => <Input id={id} type="number" min={15} max={360} step={5} value={slot.duration_minutes} onChange={e => setSlot(index, 'duration_minutes', e.target.value)} required />}
                </Field>
                <Field label={t('Зал')} className="lg:col-span-2">
                  {({ id }) => (
                    <Select id={id} value={slot.room} onChange={e => setSlot(index, 'room', e.target.value)}>
                      <option value="">{t('Не выбран')}</option>
                      {rooms.map(room => <option key={room.id} value={String(room.id)}>{room.name}</option>)}
                    </Select>
                  )}
                </Field>
                <Field label={t('Преподаватель')} className="lg:col-span-2">
                  {({ id }) => (
                    <Select id={id} value={slot.teacher} onChange={e => setSlot(index, 'teacher', e.target.value)}>
                      <option value="">{t('Не выбран')}</option>
                      {teachers.map(teacher => <option key={teacher.id} value={String(teacher.id)}>{teacher.full_name}</option>)}
                    </Select>
                  )}
                </Field>
                <div className="flex items-end justify-end lg:col-span-1">
                  <Button variant="danger-ghost" size="icon" onClick={() => removeSlot(index)} aria-label={t('Удалить время')} title={t('Удалить время')}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </div>
            </div>
          ))}

          <Button icon={Plus} onClick={() => setSlots(current => [...current, emptySlot()])}>{t('Добавить время')}</Button>
          {!slots.length && <p className="rounded-lg bg-warning-50 px-4 py-3 text-sm text-warning-700">{t('Добавьте хотя бы одно время занятия.')}</p>}
        </form>
      )}
    </Modal>
  )
}
