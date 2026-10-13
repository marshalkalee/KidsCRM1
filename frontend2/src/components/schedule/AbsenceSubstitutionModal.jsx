import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Bell, Check, ChevronDown, UserRound } from 'lucide-react'
import api from '../../api/axios'
import { fetchLessons, fetchTeachers, substituteLessons } from '../../api/lessons'
import { Button, Checkbox, DateInput, Field, Modal, Skeleton, apiErrorMessage, cn, plural, useToast } from '../../ui'
import { t } from '../../i18n'

/*
 * Замена на время отсутствия (TRU-182 + TRU-183): одним действием на все
 * занятия, которые остались без преподавателя, — за всё отсутствие или за
 * выбранный период. Назначает тот же API, что окно замены в расписании
 * (schedule/substitute/): права, филиалы и уведомления родителям — там.
 */

const LESSON_FORMS = ['занятие', 'занятия', 'занятий']
const pad = n => String(n).padStart(2, '0')
const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` }
const shortDate = value => `${value.slice(8, 10)}.${value.slice(5, 7)}`
const dayOf = row => row.starts_at_local.slice(0, 10)
const timeOf = row => row.starts_at_local.slice(11, 16)
const overlaps = (a, b) => new Date(a.starts_at_local || a.starts_at) < new Date(b.ends_at_local || b.ends_at)
  && new Date(b.starts_at_local || b.starts_at) < new Date(a.ends_at_local || a.ends_at)

export default function AbsenceSubstitutionModal({ absence, onClose, onDone }) {
  const toast = useToast()
  const first = absence.starts_on > todayIso() ? absence.starts_on : todayIso()
  const last = absence.ends_on
  const [scope, setScope] = useState('all')
  const [from, setFrom] = useState(first)
  const [to, setTo] = useState(last)
  const [data, setData] = useState(null)
  const [teacherId, setTeacherId] = useState('')
  const [onlyFree, setOnlyFree] = useState(true)
  const [notifyParents, setNotifyParents] = useState(true)
  const [showLessons, setShowLessons] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    Promise.all([
      api.get('schedule/absences/uncovered/', { params: { date_from: first, date_to: last } }),
      fetchLessons(first, last),
      fetchTeachers(),
      api.get('schedule/absences/', { params: { date_from: first, date_to: last } }),
    ])
      .then(([uncovered, lessons, teachers, absences]) => {
        if (!active) return
        setData({
          uncovered: uncovered.data.results.filter(row => row.absence.id === absence.id),
          lessons,
          teachers,
          absences: absences.data.results || absences.data,
        })
      })
      .catch(err => { if (active) setError(apiErrorMessage(err)) })
    return () => { active = false }
  }, [absence.id, first, last])

  const selected = useMemo(() => {
    if (!data) return []
    if (scope === 'all') return data.uncovered
    if (!from || !to) return []
    return data.uncovered.filter(row => dayOf(row) >= from && dayOf(row) <= to)
  }, [data, scope, from, to])

  const candidates = useMemo(() => {
    if (!data) return []
    return data.teachers
      .filter(teacher => String(teacher.id) !== String(absence.staff))
      .map(teacher => {
        const branches = (teacher.branches || []).map(String)
        const offBranch = branches.length
          ? [...new Set(selected.filter(row => row.branch_id && !branches.includes(String(row.branch_id))).map(row => row.branch_name))]
          : []
        const ownAbsences = data.absences.filter(item => String(item.staff) === String(teacher.id))
        const blocked = new Set()
        for (const row of selected) {
          const day = dayOf(row)
          const away = ownAbsences.some(item => item.starts_on <= day && day <= item.ends_on)
          const busy = data.lessons.some(other => (
            other.status === 'scheduled' && String(other.teacher) === String(teacher.id) && other.id !== row.id && overlaps(other, row)
          ))
          if (away || busy) blocked.add(row.id)
        }
        const away = ownAbsences.find(item => item.starts_on <= last && item.ends_on >= first)
        return { ...teacher, offBranch, blocked, away }
      })
      .sort((a, b) => (
        Number(a.offBranch.length > 0) - Number(b.offBranch.length > 0)
        || a.blocked.size - b.blocked.size
        || a.full_name.localeCompare(b.full_name)
      ))
  }, [data, selected, absence.staff, first, last])

  const chosen = candidates.find(teacher => String(teacher.id) === teacherId)
  const toAssign = chosen && onlyFree ? selected.filter(row => !chosen.blocked.has(row.id)) : selected

  async function save() {
    if (!chosen) { setError(t('Выберите заменяющего преподавателя')); return }
    if (!toAssign.length) { setError(t('Нет занятий, на которые можно поставить этого преподавателя')); return }
    setSaving(true)
    setError('')
    try {
      await substituteLessons({ lessonIds: toAssign.map(row => row.id), teacherId: chosen.id, notifyParents })
      toast.success(t('Замена назначена: {teacher}, {count}', {
        teacher: chosen.full_name,
        count: `${toAssign.length} ${plural(toAssign.length, LESSON_FORMS)}`,
      }))
      onDone()
    } catch (err) {
      setError(err.response?.data?.detail || apiErrorMessage(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={t('Замена на время отсутствия')}
      description={`${absence.staff_name} · ${t(absence.kind_display)} ${shortDate(absence.starts_on)}–${shortDate(absence.ends_on)}`}
      footer={
        <>
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" loading={saving} disabled={!data || !toAssign.length} onClick={save}>
            {chosen && toAssign.length ? t('Назначить на {count}', { count: `${toAssign.length} ${plural(toAssign.length, LESSON_FORMS)}` }) : t('Назначить замену')}
          </Button>
        </>
      }
    >
      {!data ? (error ? <p className="text-sm text-danger-600">{error}</p> : <Skeleton className="h-64" />) : (
        <div className="space-y-5">
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              ['all', t('Всё отсутствие'), `${data.uncovered.length} ${plural(data.uncovered.length, LESSON_FORMS)}`],
              ['period', t('За период'), t('Выберите даты')],
            ].map(([key, label, hint]) => (
              <button
                key={key}
                type="button"
                onClick={() => setScope(key)}
                className={cn('rounded-xl border px-4 py-3 text-left transition', scope === key ? 'border-brand-500 bg-brand-50' : 'border-line hover:bg-surface-muted')}
              >
                <span className={cn('block text-sm font-semibold', scope === key ? 'text-brand-700' : 'text-ink')}>{label}</span>
                <span className="text-xs text-ink-muted">{hint}</span>
              </button>
            ))}
          </div>

          {scope === 'period' && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t('С')}>
                {({ id }) => <DateInput id={id} value={from} min={first} max={last} onChange={setFrom} />}
              </Field>
              <Field label={t('По (включительно)')}>
                {({ id }) => <DateInput id={id} value={to} min={from || first} max={last} onChange={setTo} />}
              </Field>
            </div>
          )}

          <div className="rounded-xl border border-line">
            <button type="button" onClick={() => setShowLessons(v => !v)} className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left">
              <span className="text-sm font-semibold text-ink">
                {selected.length
                  ? t('Занятий без преподавателя: {count}', { count: selected.length })
                  : t('В эти дни занятий без преподавателя нет')}
              </span>
              {selected.length > 0 && <ChevronDown className={cn('size-4 text-ink-subtle transition', showLessons && 'rotate-180')} />}
            </button>
            {showLessons && selected.length > 0 && (
              <ul className="max-h-48 divide-y divide-line overflow-y-auto border-t border-line">
                {selected.map(row => (
                  <li key={row.id} className={cn('flex items-center gap-3 px-4 py-2 text-[13px]', chosen?.blocked.has(row.id) && 'bg-warning-50')}>
                    <span className="w-20 shrink-0 tabular-nums text-ink-muted">{shortDate(dayOf(row))} {timeOf(row)}</span>
                    <span className="min-w-0 flex-1 truncate font-semibold text-ink">{row.group_name || t('Индивидуальное занятие')}</span>
                    <span className="hidden shrink-0 text-ink-muted sm:inline">{row.branch_name}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <p className="mb-2 text-xs font-bold uppercase tracking-wide text-ink-subtle">{t('Кто заменяет')}</p>
            <div className="space-y-2">
              {candidates.map(teacher => {
                const isChosen = String(teacher.id) === teacherId
                const disabled = teacher.offBranch.length > 0
                const free = selected.length - teacher.blocked.size
                return (
                  <button
                    key={teacher.id}
                    type="button"
                    disabled={disabled}
                    onClick={() => setTeacherId(String(teacher.id))}
                    className={cn(
                      'flex w-full items-center gap-3 rounded-xl border p-3 text-left transition',
                      isChosen ? 'border-brand-500 bg-brand-50' : 'border-line hover:bg-surface-muted',
                      disabled && 'cursor-not-allowed opacity-55 hover:bg-transparent',
                    )}
                  >
                    <span className={cn(
                      'flex size-9 shrink-0 items-center justify-center rounded-full',
                      disabled ? 'bg-surface-muted text-ink-subtle' : teacher.blocked.size ? 'bg-warning-50 text-warning-600' : 'bg-success-50 text-success-600',
                    )}>
                      <UserRound className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold text-ink">{teacher.full_name}</span>
                      <span className={cn('block text-xs font-semibold', disabled ? 'text-ink-subtle' : teacher.blocked.size ? 'text-warning-600' : 'text-success-600')}>
                        {disabled
                          ? t('Не работает в филиале: {branches}', { branches: teacher.offBranch.join(', ') })
                          : !selected.length ? t('Свободен')
                          : teacher.blocked.size === 0 ? t('Свободен на всех занятиях')
                          : free === 0 ? t('Занят на всех выбранных занятиях')
                          : t('Свободен на {free} из {total}', { free, total: selected.length })}
                        {!disabled && teacher.away && ` · ${t(teacher.away.kind_display)} ${shortDate(teacher.away.starts_on)}–${shortDate(teacher.away.ends_on)}`}
                      </span>
                    </span>
                    {isChosen && <Check className="size-5 shrink-0 text-brand-600" />}
                  </button>
                )
              })}
              {!candidates.length && <p className="rounded-xl bg-surface-muted p-4 text-sm text-ink-muted">{t('Нет других преподавателей')}</p>}
            </div>
          </div>

          {chosen && chosen.blocked.size > 0 && selected.length > 0 && (
            <div className="rounded-xl bg-warning-50 p-3 text-sm text-warning-600">
              <p className="flex items-start gap-2 font-semibold">
                <AlertTriangle className="mt-0.5 size-4 shrink-0" />
                {t('{name} занят(а) или отсутствует на {count} из выбранных занятий.', { name: chosen.full_name, count: chosen.blocked.size })}
              </p>
              <Checkbox
                className="mt-2"
                checked={onlyFree}
                onChange={event => setOnlyFree(event.target.checked)}
                label={t('Поставить только там, где свободен(а) — остальные останутся в списке «Нужна замена»')}
              />
            </div>
          )}

          <Checkbox
            checked={notifyParents}
            onChange={event => setNotifyParents(event.target.checked)}
            label={<span className="inline-flex items-center gap-2"><Bell className="size-4 text-brand-600" />{t('Сообщить родителям')}</span>}
          />

          {error && <p role="alert" className="rounded-xl bg-danger-50 p-3 text-sm font-semibold text-danger-600">{error}</p>}
        </div>
      )}
    </Modal>
  )
}
