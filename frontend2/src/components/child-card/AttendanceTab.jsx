import { useCallback, useEffect, useState } from 'react'
import { CalendarClock, CalendarPlus, Clock, MapPin, Users } from 'lucide-react'
import api from '../../api/axios'
import {
  Badge, Button, Card, EmptyState, ErrorState, Modal, Skeleton, apiErrorMessage, formatDateTime, useConfirm, useToast,
} from '../../ui'

/**
 * Вкладка «Посещения» карточки ребёнка — пока только список доступных
 * отработок (TRU-54). Полная история посещений — отдельная задача TRU-55,
 * которая расширит этот же компонент, не добавляя новую вкладку.
 */
export default function AttendanceTab({ child, onCountChange }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [rows, setRows] = useState(null)
  const [error, setError] = useState(false)
  const [pickingFor, setPickingFor] = useState(null) // null | строка из rows

  const load = useCallback(() => {
    api.get('attendance/available-makeups/', { params: { child: child.id } })
      .then(r => {
        setRows(r.data.results)
        setError(false)
        onCountChange?.(r.data.results.length)
      })
      .catch(() => setError(true))
  }, [child.id, onCountChange])

  useEffect(() => { load() }, [load])

  async function enroll(row, candidateLessonId, confirmCapacity = false) {
    try {
      await api.post('schedule/enrollments/', {
        lesson: candidateLessonId,
        child: child.id,
        kind: 'makeup',
        source_attendance: row.attendance_id,
        confirm_capacity: confirmCapacity,
      })
      toast.success('Записан(а) на отработку')
      setPickingFor(null)
      load()
    } catch (err) {
      if (err.response?.status === 409) {
        const ok = await confirm({
          title: 'Мест нет',
          message: `Вместимость группы уже заполнена (${err.response.data.current_count}/${err.response.data.capacity}). Записать всё равно?`,
          confirmText: 'Записать',
        })
        if (ok) return enroll(row, candidateLessonId, true)
        return
      }
      toast.error(apiErrorMessage(err))
    }
  }

  if (error) return <Card><ErrorState onRetry={load} /></Card>
  if (!rows) return <Skeleton className="h-32" />

  return (
    <>
      {rows.length === 0 ? (
        <Card>
          <EmptyState icon={CalendarClock} title="Нет пропусков, доступных для отработки" description="Здесь появятся занятия, которые ребёнок пропустил и ещё может отработать." />
        </Card>
      ) : (
        <div className="space-y-3">
          {rows.map(row => (
            <Card key={row.attendance_id} className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <p className="font-semibold text-ink">{row.group_name || 'Индивидуальное занятие'}</p>
                <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-muted">
                  <span className="inline-flex items-center gap-1"><Clock className="size-3.5" />{formatDateTime(row.starts_at_local)}</span>
                  {row.room_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" />{row.room_name}</span>}
                </div>
                {row.absence_reason_display && (
                  <p className="mt-1 text-[13px] text-ink-muted">Причина: {row.absence_reason_display}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-3">
                <Badge tone={row.days_left <= 3 ? 'warning' : 'neutral'}>
                  сгорает через {row.days_left} {pluralDays(row.days_left)}
                </Badge>
                <Button variant="primary" size="sm" icon={CalendarPlus} onClick={() => setPickingFor(row)}>
                  Отработать
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      {pickingFor && (
        <MakeupCandidatesModal
          row={pickingFor}
          onClose={() => setPickingFor(null)}
          onPick={lessonId => enroll(pickingFor, lessonId)}
        />
      )}
    </>
  )
}

function pluralDays(n) {
  const mod10 = n % 10
  const mod100 = n % 100
  if (mod10 === 1 && mod100 !== 11) return 'день'
  if ([2, 3, 4].includes(mod10) && ![12, 13, 14].includes(mod100)) return 'дня'
  return 'дней'
}

function MakeupCandidatesModal({ row, onClose, onPick }) {
  const [candidates, setCandidates] = useState(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    api.get(`attendance/${row.attendance_id}/makeup-candidates/`)
      .then(r => setCandidates(r.data.results))
      .catch(() => setError(true))
  }, [row.attendance_id])

  return (
    <Modal
      open
      onClose={onClose}
      title="Выберите занятие для отработки"
      description={`${row.group_name || 'Индивидуальное занятие'} · то же направление`}
    >
      {error && <ErrorState />}
      {!error && !candidates && <Skeleton className="h-24" />}
      {!error && candidates && candidates.length === 0 && (
        <EmptyState icon={CalendarClock} title="Подходящих занятий не нашлось" description="В этом направлении нет будущих занятий." />
      )}
      {!error && candidates && candidates.length > 0 && (
        <div className="space-y-2">
          {candidates.map(lesson => {
            const full = lesson.spots_left !== null && lesson.spots_left <= 0
            return (
              <button
                key={lesson.id}
                onClick={() => onPick(lesson.id)}
                className="flex w-full items-center justify-between gap-3 rounded-md border border-line px-3.5 py-3 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40"
              >
                <div className="min-w-0">
                  <p className="font-semibold text-ink">{lesson.group_name}</p>
                  <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-muted">
                    <span className="inline-flex items-center gap-1"><Clock className="size-3.5" />{formatDateTime(lesson.starts_at_local)}</span>
                    {lesson.room_name && <span className="inline-flex items-center gap-1"><MapPin className="size-3.5" />{lesson.room_name}</span>}
                    {lesson.teacher_name && <span>{lesson.teacher_name}</span>}
                  </div>
                </div>
                {lesson.capacity !== null && (
                  <Badge tone={full ? 'danger' : 'neutral'} className="shrink-0">
                    <Users className="size-3" />{lesson.current_count}/{lesson.capacity}
                  </Badge>
                )}
              </button>
            )
          })}
        </div>
      )}
    </Modal>
  )
}
