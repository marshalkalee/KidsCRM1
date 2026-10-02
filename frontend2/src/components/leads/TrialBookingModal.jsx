import { useCallback, useEffect, useState } from 'react'
import { CalendarDays, Clock, MapPin, Pencil, RefreshCw, UserRound, Users } from 'lucide-react'
import api from '../../api/axios'
import { localDatePart, localTimePart } from '../../utils/calendarDate'
import { Badge, Button, EmptyState, ErrorState, Modal, Spinner, apiErrorMessage, useToast } from '../../ui'
import { t } from '../../i18n'

function dateLabel(iso) {
  const [year, month, day] = localDatePart(iso).split('-')
  return `${day}.${month}.${year}`
}

function ageRange(lesson) {
  if (lesson.age_min != null && lesson.age_max != null) return `${lesson.age_min}–${lesson.age_max} лет`
  if (lesson.age_min != null) return `от ${lesson.age_min} лет`
  if (lesson.age_max != null) return `до ${lesson.age_max} лет`
  return 'любой возраст'
}

/** Один мобильный/десктопный экран подбора: фильтры берутся из заявки. */
export default function TrialBookingModal({ lead, mode = 'book', onClose, onEdit, onBooked }) {
  const toast = useToast()
  const [lessons, setLessons] = useState([])
  const [state, setState] = useState('loading')
  const [error, setError] = useState('')
  const [savingId, setSavingId] = useState(null)

  const load = useCallback(() => {
    setState('loading')
    setError('')
    api.get(`leads/${lead.id}/trial-lessons/${mode === 'reschedule' ? '?mode=reschedule' : ''}`)
      .then(res => { setLessons(res.data); setState('ready') })
      .catch(err => {
        setError(apiErrorMessage(err))
        setState(err.response?.status === 400 ? 'incomplete' : 'error')
      })
  }, [lead.id, mode])

  useEffect(() => { load() }, [load])

  async function book(lesson) {
    setSavingId(lesson.id)
    try {
      const endpoint = mode === 'reschedule' ? 'reschedule-trial' : 'book-trial'
      const { data } = await api.post(`leads/${lead.id}/${endpoint}/`, { lesson: lesson.id })
      toast.success(t(mode === 'reschedule' ? 'Пробное занятие перенесено' : 'Пробное занятие назначено'))
      onBooked(data)
    } catch (err) {
      toast.error(apiErrorMessage(err))
      if (err.response?.status === 409) load()
    } finally {
      setSavingId(null)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="xl"
      title={t(mode === 'reschedule' ? 'Перенести пробное' : 'Записать на пробное')}
      description={t(mode === 'reschedule'
        ? 'Выберите другое будущее занятие со свободными местами.'
        : 'Показываем только будущие занятия со свободными местами.')}
      footer={<Button onClick={onClose}>{t('Закрыть')}</Button>}
    >
      <div className="mb-4 flex flex-wrap gap-2">
        <Badge tone="brand">{lead.direction_name || t('Направление не указано')}</Badge>
        <Badge tone="neutral">{lead.child_age != null ? `${lead.child_age} лет` : t('Возраст не указан')}</Badge>
        <Badge tone="info">{lead.branch_name || t('Филиал не указан')}</Badge>
      </div>

      {state === 'loading' && <Spinner />}
      {state === 'error' && (
        <div>
          <ErrorState title={error} onRetry={load} />
        </div>
      )}
      {state === 'incomplete' && (
        <EmptyState
          icon={Pencil}
          title={error}
          description={t('Эти данные нужны, чтобы отфильтровать подходящие группы и занятия.')}
          action={<Button variant="primary" icon={Pencil} onClick={onEdit}>{t('Заполнить заявку')}</Button>}
        />
      )}
      {state === 'ready' && lessons.length === 0 && (
        <EmptyState
          icon={CalendarDays}
          title={t('Подходящих занятий пока нет')}
          description={t('Проверьте расписание или измените направление, возраст и филиал в заявке.')}
          action={<Button icon={RefreshCw} onClick={load}>{t('Обновить')}</Button>}
        />
      )}
      {state === 'ready' && lessons.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {lessons.map(lesson => (
            <article key={lesson.id} className="flex min-w-0 flex-col rounded-xl border border-line bg-surface p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-bold text-ink">{lesson.group_name}</p>
                  <p className="mt-1 flex items-center gap-1.5 text-sm text-ink-muted">
                    <CalendarDays className="size-4 text-brand-500" />
                    {dateLabel(lesson.starts_at_local)}
                  </p>
                </div>
                <Badge tone="success">
                  {t('Свободно {n} мест', { n: lesson.spots_left })}
                </Badge>
              </div>
              <div className="mt-3 grid gap-2 text-[13px] text-ink-muted sm:grid-cols-2">
                <span className="flex items-center gap-1.5"><Clock className="size-3.5" />{localTimePart(lesson.starts_at_local)}–{localTimePart(lesson.ends_at_local)}</span>
                <span className="flex items-center gap-1.5"><MapPin className="size-3.5" />{lesson.branch_name}{lesson.room_name ? ` · ${lesson.room_name}` : ''}</span>
                <span className="flex items-center gap-1.5"><Users className="size-3.5" />{lesson.occupied_count}/{lesson.capacity} · {ageRange(lesson)}</span>
                {lesson.teacher_name && <span className="flex items-center gap-1.5"><UserRound className="size-3.5" />{lesson.teacher_name}</span>}
              </div>
              <Button
                className="mt-4 w-full justify-center"
                variant="primary"
                loading={savingId === lesson.id}
                disabled={Boolean(savingId)}
                onClick={() => book(lesson)}
              >
                {t(mode === 'reschedule' ? 'Перенести на это занятие' : 'Записать на это занятие')}
              </Button>
            </article>
          ))}
        </div>
      )}
    </Modal>
  )
}
