import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Bell, Check, Clock3, UserRound, X } from 'lucide-react'
import { fetchLessons, removeLessonSubstitutions, substituteLessons } from '../../api/lessons'
import { t } from '../../i18n'

const overlaps = (left, right) => (
  new Date(left.starts_at) < new Date(right.ends_at)
  && new Date(right.starts_at) < new Date(left.ends_at)
)

const lessonDate = lesson => lesson.starts_at_local?.slice(0, 10) || lesson.starts_at.slice(0, 10)
const lessonTime = lesson => (lesson.starts_at_local || lesson.starts_at).slice(11, 16)

export default function TeacherSubstitutionModal({
  lesson,
  teachers,
  branchId,
  dateFrom,
  dateTo,
  onClose,
  onDone,
}) {
  const [scope, setScope] = useState('one')
  const [teacherId, setTeacherId] = useState('')
  const [notifyParents, setNotifyParents] = useState(true)
  const [periodLessons, setPeriodLessons] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    fetchLessons(dateFrom, dateTo)
      .then(rows => { if (active) setPeriodLessons(rows) })
      .catch(() => { if (active) setError(t('Не удалось загрузить расписание преподавателей')) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [dateFrom, dateTo])

  const scheduledTeacherId = String(lesson.original_teacher || lesson.teacher || '')
  const selectedLessons = useMemo(() => {
    if (scope === 'one') return [lesson]
    return periodLessons.filter(row => (
      row.status === 'scheduled'
      && String(row.original_teacher || row.teacher || '') === scheduledTeacherId
    ))
  }, [lesson, periodLessons, scheduledTeacherId, scope])

  const candidates = useMemo(() => teachers
    .filter(teacher => {
      const branches = (teacher.branches || []).map(String)
      return !branchId || branches.length === 0 || branches.includes(String(branchId))
    })
    .filter(teacher => String(teacher.id) !== String(lesson.teacher || ''))
    .map(teacher => {
      const busy = periodLessons.filter(other => (
        other.status === 'scheduled'
        && String(other.teacher) === String(teacher.id)
        && selectedLessons.some(selected => other.id !== selected.id && overlaps(other, selected))
      ))
      return { ...teacher, busy }
    })
    .sort((a, b) => Number(Boolean(a.busy.length)) - Number(Boolean(b.busy.length)) || a.full_name.localeCompare(b.full_name)),
  [branchId, lesson.teacher, periodLessons, selectedLessons, teachers])

  async function save() {
    if (!teacherId) return setError(t('Выберите заменяющего преподавателя'))
    setSaving(true)
    setError('')
    try {
      await substituteLessons({
        lessonIds: selectedLessons.map(row => row.id),
        teacherId,
        notifyParents,
      })
      onDone()
    } catch (requestError) {
      setError(requestError.response?.data?.detail || t('Не удалось назначить замену'))
    } finally {
      setSaving(false)
    }
  }

  async function remove() {
    setSaving(true)
    setError('')
    try {
      const substitutions = selectedLessons.filter(row => row.is_substitution)
      await removeLessonSubstitutions(substitutions.map(row => row.id))
      onDone()
    } catch (requestError) {
      setError(requestError.response?.data?.detail || t('Не удалось снять замену'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/45 p-4" onClick={onClose}>
      <div className="max-h-[calc(100vh-32px)] w-full max-w-xl overflow-y-auto rounded-2xl bg-white p-5 shadow-pop sm:p-6" onClick={event => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-ink">{t('Назначить замену')}</h2>
            <p className="mt-1 text-sm text-ink-muted">
              {lesson.group_name || t('Индивидуальное занятие')} · {lessonDate(lesson)} · {lessonTime(lesson)}
            </p>
          </div>
          <button type="button" className="rounded-lg p-2 text-ink-muted hover:bg-surface-muted" onClick={onClose} aria-label={t('Закрыть')}><X className="size-5" /></button>
        </div>

        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          <button type="button" className={`rounded-xl border px-4 py-3 text-left text-sm font-semibold ${scope === 'one' ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink'}`} onClick={() => setScope('one')}>
            {t('Только это занятие')}
          </button>
          <button type="button" className={`rounded-xl border px-4 py-3 text-left text-sm font-semibold ${scope === 'period' ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-line text-ink'}`} onClick={() => setScope('period')}>
            {t('Все занятия преподавателя за период')} ({scope === 'period' ? selectedLessons.length : periodLessons.filter(row => row.status === 'scheduled' && String(row.original_teacher || row.teacher || '') === scheduledTeacherId).length})
          </button>
        </div>

        <div className="mt-5">
          <p className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-subtle">{t('Заменяющий преподаватель')}</p>
          {loading ? <p className="py-6 text-center text-sm text-ink-muted">{t('Загрузка…')}</p> : (
            <div className="space-y-2">
              {candidates.map(teacher => {
                const selected = String(teacher.id) === teacherId
                return (
                  <button key={teacher.id} type="button" onClick={() => setTeacherId(String(teacher.id))} className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left ${selected ? 'border-brand-500 bg-brand-50' : 'border-line hover:bg-surface-muted'}`}>
                    <span className={`flex size-10 shrink-0 items-center justify-center rounded-full ${teacher.busy.length ? 'bg-warning-50 text-warning-600' : 'bg-success-50 text-success-600'}`}><UserRound className="size-5" /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block font-semibold text-ink">{teacher.full_name}</span>
                      {teacher.busy.length ? (
                        <span className="mt-0.5 flex items-center gap-1 text-xs font-semibold text-warning-600"><Clock3 className="size-3.5" />{t('Занят в {time}', { time: lessonTime(teacher.busy[0]) })}</span>
                      ) : <span className="text-xs font-semibold text-success-600">{t('Свободен')}</span>}
                    </span>
                    {selected && <Check className="size-5 text-brand-600" />}
                  </button>
                )
              })}
              {!candidates.length && <p className="rounded-xl bg-surface-muted p-4 text-sm text-ink-muted">{t('В этом филиале нет доступных преподавателей')}</p>}
            </div>
          )}
        </div>

        <label className="mt-5 flex cursor-pointer items-center gap-3 rounded-xl border border-line p-4">
          <input type="checkbox" checked={notifyParents} onChange={event => setNotifyParents(event.target.checked)} className="size-5 accent-brand-600" />
          <Bell className="size-5 text-brand-600" />
          <span className="text-sm font-semibold text-ink">{t('Сообщить родителям')}</span>
        </label>

        {candidates.find(row => String(row.id) === teacherId)?.busy.length > 0 && (
          <p className="mt-3 flex items-start gap-2 rounded-xl bg-warning-50 p-3 text-sm text-warning-700"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{t('У преподавателя есть пересекающееся занятие. Проверьте время перед сохранением.')}</p>
        )}
        {error && <p role="alert" className="mt-3 rounded-xl bg-danger-50 p-3 text-sm font-semibold text-danger-600">{error}</p>}

        <div className="mt-6 flex flex-wrap justify-end gap-2">
          {lesson.is_substitution && <button type="button" disabled={saving} onClick={remove} className="mr-auto rounded-lg border border-danger-200 px-4 py-2.5 text-sm font-semibold text-danger-600">{t('Снять замену')}</button>}
          <button type="button" onClick={onClose} className="rounded-lg border border-line px-4 py-2.5 text-sm font-semibold text-ink">{t('Отмена')}</button>
          <button type="button" disabled={saving || !selectedLessons.length} onClick={save} className="rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{saving ? t('Сохранение…') : t('Назначить замену')}</button>
        </div>
      </div>
    </div>
  )
}
