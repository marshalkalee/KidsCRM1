import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { CalendarOff, ChevronLeft, ChevronRight, Plus, Trash2, UserX } from 'lucide-react'
import api from '../api/axios'
import {
  Badge, Button, Card, CardHeader, DateInput, EmptyState, ErrorState, Field, Modal, PageHeader,
  Select, Skeleton, Textarea, apiErrorMessage, cn, useConfirm, useToast,
} from '../ui'
import { t, useLang } from '../i18n'

/*
 * Отсутствия сотрудников (TRU-182): отпуск, больничный, отгул — заранее.
 * Сверху — занятия, которые остались без преподавателя («нужна замена»),
 * ниже — месяц: строка на сотрудника, полоска на каждое отсутствие.
 */

const KINDS = {
  vacation: { get label() { return t('Отпуск') }, bar: 'border-info-600 bg-info-50 text-info-600', tone: 'info', swatch: 'bg-info-600' },
  sick: { get label() { return t('Больничный') }, bar: 'border-danger-600 bg-danger-50 text-danger-600', tone: 'danger', swatch: 'bg-danger-600' },
  day_off: { get label() { return t('Отгул') }, bar: 'border-warning-600 bg-warning-50 text-warning-600', tone: 'warning', swatch: 'bg-warning-600' },
  other: { get label() { return t('Другое') }, bar: 'border-ink-subtle bg-surface-muted text-ink-muted', tone: 'neutral', swatch: 'bg-ink-subtle' },
}

const pad = n => String(n).padStart(2, '0')
const iso = date => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const fromIso = value => { const [y, m, d] = value.split('-').map(Number); return new Date(y, m - 1, d) }
const shortDate = value => `${value.slice(8, 10)}.${value.slice(5, 7)}`
const listOf = response => response.data.results || response.data

function monthLabel(month, lang) {
  const text = month.toLocaleDateString(lang === 'kk' ? 'kk-KZ' : lang === 'en' ? 'en-GB' : 'ru-RU', { month: 'long', year: 'numeric' })
  return text.charAt(0).toUpperCase() + text.slice(1).replace(/\s*г\.$/, '')
}

function period(absence) {
  return absence.starts_on === absence.ends_on
    ? shortDate(absence.starts_on)
    : `${shortDate(absence.starts_on)} – ${shortDate(absence.ends_on)}`
}

export default function Absences() {
  const lang = useLang()
  const [month, setMonth] = useState(() => { const now = new Date(); return new Date(now.getFullYear(), now.getMonth(), 1) })
  const [absences, setAbsences] = useState(null)
  const [uncovered, setUncovered] = useState(null)
  const [staff, setStaff] = useState([])
  const [error, setError] = useState(false)
  const [editing, setEditing] = useState(null)

  const first = iso(month)
  const last = iso(new Date(month.getFullYear(), month.getMonth() + 1, 0))

  const load = useCallback(() => {
    Promise.all([
      api.get('schedule/absences/', { params: { date_from: first, date_to: last } }),
      api.get('schedule/absences/uncovered/'),
    ])
      .then(([list, open]) => { setAbsences(listOf(list)); setUncovered(open.data) })
      .catch(() => setError(true))
  }, [first, last])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    api.get('users/').then(res => setStaff(listOf(res).filter(user => user.is_active !== false))).catch(() => {})
  }, [])

  function shift(delta) {
    setAbsences(null)
    setMonth(current => new Date(current.getFullYear(), current.getMonth() + delta, 1))
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title={t('Отсутствия')}
        description={t('Отпуска, больничные и отгулы сотрудников. Занятия в эти дни расписание помечает «нужна замена».')}
        actions={<Button variant="primary" icon={Plus} onClick={() => setEditing({})}>{t('Добавить')}</Button>}
      />

      {error ? <Card><ErrorState onRetry={() => { setError(false); load() }} /></Card> : (
        <>
          <UncoveredCard data={uncovered} />
          <Card>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-1">
                <Button size="icon" variant="ghost" icon={ChevronLeft} aria-label={t('Предыдущий месяц')} onClick={() => shift(-1)} />
                <h2 className="min-w-40 text-center text-[15px] font-bold text-ink">{monthLabel(month, lang)}</h2>
                <Button size="icon" variant="ghost" icon={ChevronRight} aria-label={t('Следующий месяц')} onClick={() => shift(1)} />
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1">
                {Object.entries(KINDS).map(([key, kind]) => (
                  <span key={key} className="flex items-center gap-1.5 text-[12px] text-ink-muted">
                    <span className={cn('size-2.5 rounded-sm', kind.swatch)} />{kind.label}
                  </span>
                ))}
              </div>
            </div>
            {absences === null ? <Skeleton className="h-40" /> : absences.length === 0 ? (
              <EmptyState
                icon={CalendarOff}
                title={t('В этом месяце все на месте')}
                description={t('Отметьте отпуск или больничный заранее — CRM подскажет, каким занятиям нужна замена.')}
                className="py-10"
              />
            ) : (
              <>
                <MonthGrid month={month} absences={absences} onOpen={setEditing} />
                <MonthList absences={absences} onOpen={setEditing} />
              </>
            )}
          </Card>
        </>
      )}

      {editing && (
        <AbsenceModal
          absence={editing.id ? editing : null}
          staff={staff}
          onClose={() => setEditing(null)}
          onDone={() => { setEditing(null); load() }}
        />
      )}
    </div>
  )
}

function UncoveredCard({ data }) {
  if (data === null) return <Skeleton className="h-24" />
  const rows = data.results
  return (
    <Card>
      <CardHeader
        title={t('Нужна замена')}
        description={t('Занятия на ближайшие 30 дней, у которых преподаватель отсутствует')}
        actions={<Badge tone={rows.length ? 'danger' : 'success'} dot>{rows.length ? rows.length : t('Нет')}</Badge>}
      />
      {rows.length === 0 ? (
        <p className="text-[13px] text-ink-muted">{t('Все занятия закрыты: замены не нужны.')}</p>
      ) : (
        <ul className="divide-y divide-line">
          {rows.map(row => {
            const day = row.starts_at_local.slice(0, 10)
            return (
              <li key={row.id}>
                <Link
                  to={`/schedule?view=day&date=${day}&lesson=${row.id}`}
                  className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 hover:bg-surface-muted"
                >
                  <div className="w-14 shrink-0 text-center">
                    <div className="text-[13px] font-bold text-ink">{shortDate(day)}</div>
                    <div className="text-[12px] text-ink-muted">{row.starts_at_local.slice(11, 16)}</div>
                  </div>
                  <span className="h-8 w-1 shrink-0 rounded-full" style={{ backgroundColor: row.direction_color || '#9aa3ad' }} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14px] font-semibold text-ink">{row.group_name || t('Индивидуальное занятие')}</div>
                    <div className="truncate text-[12px] text-ink-muted">
                      {[row.branch_name, row.room_name].filter(Boolean).join(' · ')}
                    </div>
                    <div className="truncate text-[12px] font-semibold text-danger-600 sm:hidden">
                      {row.teacher_name} · {t(row.absence.kind_display)} {t('до {date}', { date: shortDate(row.absence.ends_on) })}
                    </div>
                  </div>
                  <div className="hidden min-w-0 text-right sm:block">
                    <div className="flex items-center justify-end gap-1 truncate text-[13px] font-semibold text-danger-600">
                      <UserX className="size-3.5 shrink-0" />{row.teacher_name}
                    </div>
                    <div className="text-[12px] text-ink-muted">{t(row.absence.kind_display)} {t('до {date}', { date: shortDate(row.absence.ends_on) })}</div>
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-ink-subtle" />
                </Link>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

/** Компьютер: строка на сотрудника, колонка на день месяца. */
function MonthGrid({ month, absences, onOpen }) {
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate()
  const today = new Date()
  const todayIndex = today.getFullYear() === month.getFullYear() && today.getMonth() === month.getMonth() ? today.getDate() : null
  const rows = useMemo(() => {
    const byStaff = new Map()
    for (const absence of absences) {
      if (!byStaff.has(absence.staff)) byStaff.set(absence.staff, { name: absence.staff_name, items: [] })
      byStaff.get(absence.staff).items.push(absence)
    }
    return [...byStaff.entries()].sort((a, b) => a[1].name.localeCompare(b[1].name))
  }, [absences])
  const columns = `repeat(${days}, minmax(0, 1fr))`
  const monthEnd = new Date(month.getFullYear(), month.getMonth(), days)

  return (
    <div className="hidden md:block">
      <div className="grid grid-cols-[180px_minmax(0,1fr)] items-end border-b border-line pb-1">
        <span />
        <div className="grid" style={{ gridTemplateColumns: columns }}>
          {Array.from({ length: days }, (_, i) => {
            const weekday = new Date(month.getFullYear(), month.getMonth(), i + 1).getDay()
            return (
              <span
                key={i}
                className={cn(
                  'text-center text-[11px] tabular-nums',
                  weekday === 0 || weekday === 6 ? 'text-ink-subtle' : 'text-ink-muted',
                  todayIndex === i + 1 && 'font-bold text-brand-600',
                )}
              >
                {i + 1}
              </span>
            )
          })}
        </div>
      </div>
      {rows.map(([staffId, row]) => (
        <div key={staffId} className="grid grid-cols-[180px_minmax(0,1fr)] items-center border-b border-line last:border-0">
          <Link to={`/staff/${staffId}`} state={{ from: '/absences', label: t('Отсутствия') }} className="truncate py-3 pr-3 text-[13px] font-semibold text-ink hover:text-brand-600">
            {row.name}
          </Link>
          <div className="relative grid h-10" style={{ gridTemplateColumns: columns }}>
            {Array.from({ length: days }, (_, i) => {
              const weekday = new Date(month.getFullYear(), month.getMonth(), i + 1).getDay()
              return <span key={i} className={cn('h-full', (weekday === 0 || weekday === 6) && 'bg-surface-muted', todayIndex === i + 1 && 'bg-brand-50')} />
            })}
            {row.items.map(absence => {
              const start = Math.max(1, fromIso(absence.starts_on) < month ? 1 : fromIso(absence.starts_on).getDate())
              const end = fromIso(absence.ends_on) > monthEnd ? days : fromIso(absence.ends_on).getDate()
              const kind = KINDS[absence.kind] || KINDS.other
              return (
                <button
                  key={absence.id}
                  type="button"
                  onClick={() => onOpen(absence)}
                  title={`${kind.label}: ${period(absence)}${absence.note ? ` — ${absence.note}` : ''}`}
                  className={cn('absolute inset-y-1.5 truncate rounded-md border-l-[3px] px-1.5 text-left text-[12px] font-semibold transition hover:brightness-95', kind.bar)}
                  style={{ left: `${((start - 1) / days) * 100}%`, width: `${((end - start + 1) / days) * 100}%` }}
                >
                  {kind.label}
                </button>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

/** Телефон: тот же месяц списком. */
function MonthList({ absences, onOpen }) {
  return (
    <ul className="space-y-2 md:hidden">
      {absences.map(absence => {
        const kind = KINDS[absence.kind] || KINDS.other
        return (
          <li key={absence.id}>
            <button type="button" onClick={() => onOpen(absence)} className={cn('w-full rounded-lg border-l-[3px] px-3 py-2.5 text-left', kind.bar)}>
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[14px] font-semibold text-ink">{absence.staff_name}</span>
                <span className="shrink-0 text-[12px] font-semibold">{kind.label}</span>
              </div>
              <div className="text-[12px] text-ink-muted">{period(absence)}{absence.note && ` · ${absence.note}`}</div>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function AbsenceModal({ absence, staff, onClose, onDone }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [form, setForm] = useState(() => ({
    staff: absence?.staff || '',
    kind: absence?.kind || 'vacation',
    starts_on: absence?.starts_on || '',
    ends_on: absence?.ends_on || '',
    note: absence?.note || '',
  }))
  const [errors, setErrors] = useState({})
  const [busy, setBusy] = useState(false)
  const set = (key, value) => setForm(current => ({ ...current, [key]: value }))
  const people = useMemo(() => [...staff].sort((a, b) => a.full_name.localeCompare(b.full_name)), [staff])

  async function submit(event) {
    event.preventDefault()
    const payload = { ...form, ends_on: form.ends_on || form.starts_on }
    setBusy(true)
    setErrors({})
    try {
      const { data } = absence
        ? await api.patch(`schedule/absences/${absence.id}/`, payload)
        : await api.post('schedule/absences/', payload)
      if (data.lessons_affected > 0) {
        toast.success(t('Сохранено. Занятий в эти дни: {count} — они в списке «Нужна замена».', { count: data.lessons_affected }))
      } else {
        toast.success(t('Сохранено'))
      }
      onDone()
    } catch (err) {
      const data = err.response?.data
      if (data && typeof data === 'object' && !data.detail) setErrors(data)
      else toast.error(apiErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    const ok = await confirm({
      title: t('Удалить отсутствие?'),
      message: t('Занятия в эти дни перестанут помечаться «нужна замена».'),
      confirmText: t('Удалить'),
      danger: true,
    })
    if (!ok) return
    try {
      await api.delete(`schedule/absences/${absence.id}/`)
      toast.success(t('Удалено'))
      onDone()
    } catch (err) {
      toast.error(apiErrorMessage(err))
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={absence ? t('Отсутствие') : t('Новое отсутствие')}
      description={absence?.created_by_name ? t('Внёс(ла): {name}', { name: absence.created_by_name }) : undefined}
      footer={
        <>
          {absence && <Button variant="danger-ghost" icon={Trash2} className="mr-auto" onClick={remove}>{t('Удалить')}</Button>}
          <Button onClick={onClose}>{t('Отмена')}</Button>
          <Button variant="primary" type="submit" form="absence-form" loading={busy}>{t('Сохранить')}</Button>
        </>
      }
    >
      <form id="absence-form" onSubmit={submit} className="space-y-4">
        <Field label={t('Сотрудник')} error={errors.staff} required>
          {({ id, invalid }) => (
            <Select id={id} invalid={invalid} value={form.staff} onChange={e => set('staff', e.target.value)} required>
              <option value="">{t('Выберите сотрудника')}</option>
              {people.map(user => <option key={user.id} value={user.id}>{user.full_name}</option>)}
            </Select>
          )}
        </Field>
        <Field label={t('Тип')} error={errors.kind}>
          {({ id }) => (
            <div id={id} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {Object.entries(KINDS).map(([key, kind]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => set('kind', key)}
                  className={cn(
                    'h-9 rounded-md border text-[13px] font-semibold transition',
                    form.kind === key ? cn('border-l-[3px]', kind.bar) : 'border-line-strong text-ink-muted hover:bg-surface-muted',
                  )}
                >
                  {kind.label}
                </button>
              ))}
            </div>
          )}
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('С')} error={errors.starts_on} required>
            {({ id, invalid }) => <DateInput id={id} invalid={invalid} value={form.starts_on} onChange={value => set('starts_on', value)} required />}
          </Field>
          <Field label={t('По (включительно)')} error={errors.ends_on} hint={t('Пусто — один день')}>
            {({ id, invalid }) => <DateInput id={id} invalid={invalid} value={form.ends_on} min={form.starts_on || undefined} onChange={value => set('ends_on', value)} />}
          </Field>
        </div>
        <Field label={t('Заметка')} error={errors.note}>
          {({ id }) => <Textarea id={id} rows={2} maxLength={500} value={form.note} onChange={e => set('note', e.target.value)} placeholder={t('Например: замену ищет Алия')} />}
        </Field>
        {errors.non_field_errors && <p className="text-[13px] text-danger-600">{errors.non_field_errors[0]}</p>}
      </form>
    </Modal>
  )
}
