import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft, Check, X, RotateCcw, AlertTriangle, MapPin, Clock, ChevronLeft, ChevronRight,
  WifiOff, History, CalendarDays, Undo2,
} from 'lucide-react'
import { addDays, localDatePart, localTimePart, toISODate } from '../utils/calendarDate'
import { fetchLessons } from '../api/lessons'
import {
  fetchLesson, fetchAttendanceRoster, markAttendance, markAllPresent, resetAllAttendance, resetAttendance,
} from '../api/attendance'
import {
  ageLabel, Avatar, Badge, Button, Card, CHILD_STATUSES, DateInput, EmptyState, formatDate, PageHeader,
} from '../ui'
import { t } from '../i18n'

const ACCENT = '#C97B6E'
const MOBILE_BREAKPOINT = 640 // TRU-51: отдельный сценарий для телефона, не адаптив десктопа

const ABSENCE_REASONS = [
  ['illness', 'Болезнь'],
  ['family', 'Семейные обстоятельства'],
  ['no_reason', 'Без причины'],
]

const CONSUME_OUTCOME_LABEL = {
  no_active_subscription: 'Нет абонемента',
  subscription_frozen: 'Абонемент заморожен',
  subscription_exhausted: 'Занятия закончились',
  rule_forbids: 'Абонемент не позволяет списание',
}

const CHILD_GENDER_LABEL = {
  female: 'Девочка',
  male: 'Мальчик',
}

// TRU-53: дети, записанные «поверх» состава группы (отработка/пробное) —
// пометка типа рядом с именем, чтобы было видно, что это не обычный
// участник группы.
const ENROLLMENT_KIND_UI = {
  makeup: { label: 'Отработка', color: '#2563EB', background: '#EFF6FF', border: '#BFDBFE' },
  trial: { label: 'Пробное', color: '#7C3AED', background: '#F3E8FF', border: '#DDD6FE' },
}

function lessonLabel(lesson) {
  if (!lesson) return ''
  if (lesson.group_name) return lesson.group_name
  if (lesson.individual_children_names?.length) return lesson.individual_children_names.join(', ')
  return t('Индив. занятие')
}

function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < MOBILE_BREAKPOINT)
  useEffect(() => {
    function handler() { setIsMobile(window.innerWidth < MOBILE_BREAKPOINT) }
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])
  return isMobile
}

// ТЗ п. 10.4/13.3: плохая связь не должна незаметно терять отметку —
// баннер сверху виден всё время, пока связи нет (независимо от того, шло
// ли в этот момент сохранение), плюс у каждой строки есть свой признак
// "не сохранилось" (см. AttendanceRow) на случай обрыва посреди запроса.
function useOnlineStatus() {
  const [online, setOnline] = useState(() => navigator.onLine)
  useEffect(() => {
    function goOnline() { setOnline(true) }
    function goOffline() { setOnline(false) }
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])
  return online
}

function validDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false
  const [year, month, day] = value.split('-').map(Number)
  const parsed = new Date(year, month - 1, day)
  return toISODate(parsed) === value
}

function dateFromIso(value) {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(year, month - 1, day)
}

function AttendanceDateInput({ value, onChange }) {
  const [draft, setDraft] = useState(value)

  function handleChange(nextValue) {
    setDraft(nextValue)
    if (validDate(nextValue)) onChange(nextValue)
  }

  return (
    <div className="w-[150px]">
      <label className="sr-only" htmlFor="attendance-date">{t('Выбрать дату')}</label>
      <DateInput id="attendance-date" value={draft} onChange={handleChange} />
    </div>
  )
}

// Вход в посещаемость: без ?lesson — список занятий за выбранную дату
// (свои для преподавателя, все для админа/владельца — фильтрует бэк),
// с ?lesson — экран отметки. Дата остаётся в URL, чтобы при возврате из
// занятия администратор попадал обратно на тот же день.
export default function AttendanceScreen() {
  const [searchParams] = useSearchParams()
  const lessonId = searchParams.get('lesson')
  const requestedDate = searchParams.get('date')
  const selectedDate = validDate(requestedDate) ? requestedDate : toISODate(new Date())
  return lessonId
    ? <AttendanceLessonScreen lessonId={lessonId} listDate={selectedDate} />
    : <DailyLessonsList selectedDate={selectedDate} />
}

function DailyLessonsList({ selectedDate }) {
  const navigate = useNavigate()
  const [, setSearchParams] = useSearchParams()
  const [lessons, setLessons] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const today = toISODate(new Date())

  function selectDate(value) {
    if (validDate(value)) setSearchParams({ date: value })
  }

  function shiftDate(days) {
    selectDate(toISODate(addDays(dateFromIso(selectedDate), days)))
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    setLessons([])
    fetchLessons(selectedDate, selectedDate)
      .then(data => { if (!cancelled) setLessons(data) })
      .catch(() => { if (!cancelled) setError(t('Не удалось загрузить занятия за выбранную дату.')) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedDate])

  return (
    <div style={{ fontFamily: 'Manrope', width: '100%' }}>
      <PageHeader
        title={t('Посещаемость')}
        description={t('Занятия за {date}', { date: formatDate(selectedDate) })}
        actions={(
          <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto">
            <Button
              icon={ChevronLeft}
              onClick={() => shiftDate(-1)}
              aria-label={t('Предыдущий день')}
              title={t('Предыдущий день')}
            >
              {t('Назад')}
            </Button>
            <AttendanceDateInput key={selectedDate} value={selectedDate} onChange={selectDate} />
            <Button
              icon={ChevronRight}
              onClick={() => shiftDate(1)}
              aria-label={t('Следующий день')}
              title={t('Следующий день')}
            >
              {t('Вперёд')}
            </Button>
            {selectedDate !== today && <Button onClick={() => selectDate(today)}>{t('Сегодня')}</Button>}
          </div>
        )}
      />

      {loading && <div style={{ padding: 24, textAlign: 'center', color: '#9CA3AF' }}>{t('Загрузка…')}</div>}
      {error && <div style={{ padding: 24, textAlign: 'center', color: '#DC2626' }}>{error}</div>}
      {!loading && !error && lessons.length === 0 && (
        <Card><EmptyState icon={CalendarDays} title={t('На выбранную дату занятий нет')} description={t('Выберите другую дату или проверьте расписание.')} /></Card>
      )}

      <div className="grid grid-cols-1 gap-[18px] md:grid-cols-2">
        {lessons.map(lesson => (
          <button
            key={lesson.id}
            onClick={() => navigate(`/attendance?lesson=${lesson.id}&date=${selectedDate}`)}
            style={{
              position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
              minHeight: 168, width: '100%', textAlign: 'left', background: '#fff',
              border: '1px solid #E9E7EF', borderRadius: 18, padding: 24,
              cursor: 'pointer', fontFamily: 'Manrope', transition: 'transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease',
            }}
            onMouseEnter={event => {
              event.currentTarget.style.transform = 'translateY(-2px)'
              event.currentTarget.style.boxShadow = '0 10px 28px rgba(46, 36, 70, 0.08)'
              event.currentTarget.style.borderColor = '#F3B6AE'
            }}
            onMouseLeave={event => {
              event.currentTarget.style.transform = 'none'
              event.currentTarget.style.boxShadow = 'none'
              event.currentTarget.style.borderColor = '#E9E7EF'
            }}
          >
            <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 48, height: 48, borderRadius: 13, background: '#FDE8EB', color: '#F05272', marginBottom: 20 }}>
              <CalendarDays size={23} />
            </span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 17, fontWeight: 750, color: '#1A1A2E' }}>{lessonLabel(lesson)}</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 13, color: '#6B7280', marginTop: 7 }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Clock size={14} /> {localTimePart(lesson.starts_at_local)}–{localTimePart(lesson.ends_at_local)}
                </span>
                {lesson.room_name && (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <MapPin size={14} /> {lesson.room_name}
                  </span>
                )}
              </div>
            </div>
            <ChevronRight size={19} style={{ position: 'absolute', right: 22, top: 24, color: '#C7C7D1' }} />
          </button>
        ))}
      </div>
    </div>
  )
}

// Экран отметки: десктоп (TRU-56) — компактные кнопки в ряд, причина
// пропуска раскрывается внутри строки. Телефон (TRU-51) — отдельный
// сценарий, не адаптив: кнопки на весь ряд под палец, причина — шторка
// снизу экрана, «отметить всех» прибита к низу (работа одной рукой).
// Всё остальное (мгновенная реакция, автосохранение, признак «не
// сохранилось», ≤3 клика на ребёнка) общее для обеих версий.
function AttendanceLessonScreen({ lessonId, listDate }) {
  const navigate = useNavigate()
  const isMobile = useIsMobile()
  const online = useOnlineStatus()

  const [lesson, setLesson] = useState(null)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reasonPickerFor, setReasonPickerFor] = useState(null)
  const [savingIds, setSavingIds] = useState({})
  const [bulkSaving, setBulkSaving] = useState(false)

  const load = useCallback(() => {
    if (!lessonId) {
      setError(t('Не указано занятие.'))
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    Promise.all([fetchLesson(lessonId), fetchAttendanceRoster(lessonId)])
      .then(([lessonData, rosterData]) => {
        setLesson(lessonData)
        setRows(rosterData.results)
      })
      .catch(err => {
        setError(
          err.response?.status === 403
            ? t('Доступно только для своих занятий.')
            : t('Не удалось загрузить занятие.')
        )
      })
      .finally(() => setLoading(false))
  }, [lessonId])

  useEffect(() => { load() }, [load])

  async function handleMark(childId, statusValue, absenceReason = '') {
    setReasonPickerFor(null)
    setSavingIds(s => ({ ...s, [childId]: true }))
    // Мгновенная реакция на нажатие — обновляем строку сразу, не дожидаясь
    // ответа сервера; при ошибке откатываем и показываем, что не сохранилось.
    setRows(rs => rs.map(r => (
      r.child === childId
        ? { ...r, status: statusValue, absence_reason: absenceReason, _error: false }
        : r
    )))
    try {
      const updated = await markAttendance({ lesson: lessonId, child: childId, status: statusValue, absenceReason })
      setRows(rs => rs.map(r => (r.child === childId ? { ...r, ...updated, _error: false } : r)))
    } catch {
      setRows(rs => rs.map(r => (r.child === childId ? { ...r, _error: true } : r)))
    } finally {
      setSavingIds(s => ({ ...s, [childId]: false }))
    }
  }

  async function handleReset(childId) {
    setReasonPickerFor(null)
    setSavingIds(s => ({ ...s, [childId]: true }))
    const previous = rows.find(row => row.child === childId)
    setRows(current => current.map(row => (
      row.child === childId
        ? {
            ...row,
            attendance_id: null,
            status: null,
            status_display: null,
            absence_reason: '',
            consumed_from_subscription: false,
            no_subscription_flag: false,
            consume_outcome: '',
            is_retroactive_edit: false,
            marked_at: null,
            _error: false,
          }
        : row
    )))
    try {
      await resetAttendance({ lesson: lessonId, child: childId })
    } catch {
      setRows(current => current.map(row => (
        row.child === childId ? { ...previous, _error: true } : row
      )))
    } finally {
      setSavingIds(s => ({ ...s, [childId]: false }))
    }
  }

  async function handleMarkAllPresent() {
    setBulkSaving(true)
    try {
      await markAllPresent(lessonId)
      load()
    } catch {
      setError(t('Не удалось отметить всех — попробуйте ещё раз.'))
    } finally {
      setBulkSaving(false)
    }
  }

  async function handleResetAll() {
    setBulkSaving(true)
    try {
      await resetAllAttendance(lessonId)
      load()
    } catch {
      setError(t('Не удалось сбросить отметки — попробуйте ещё раз.'))
    } finally {
      setBulkSaving(false)
    }
  }

  const markedCount = rows.filter(r => r.status).length
  const reasonPickerRow = rows.find(r => r.child === reasonPickerFor)

  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: '#9CA3AF', fontFamily: 'Manrope' }}>
        {t('Загрузка…')}
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: 40, textAlign: 'center', fontFamily: 'Manrope' }}>
        <p style={{ color: '#DC2626', marginBottom: 16 }}>{error}</p>
        <button style={backBtn} onClick={() => navigate(`/attendance?date=${listDate}`)}>
          <ArrowLeft size={14} /> {t('К списку занятий')}
        </button>
      </div>
    )
  }

  return (
    <div style={{ fontFamily: 'Manrope', width: '100%' }}>
      <PageHeader
        back={{ to: `/attendance?date=${listDate}`, label: t('К списку занятий') }}
        title={lessonLabel(lesson)}
        description={[
          `${localDatePart(lesson.starts_at_local)} · ${localTimePart(lesson.starts_at_local)}–${localTimePart(lesson.ends_at_local)}`,
          lesson.room_name,
          t('{marked}/{total} отмечено', { marked: markedCount, total: rows.length }),
        ].filter(Boolean).join(' · ')}
        actions={(
          <>
            <Button icon={Undo2} loading={bulkSaving} disabled={markedCount === 0} onClick={handleResetAll}>
              {t('Сбросить')}
            </Button>
            <Button variant="primary" icon={Check} loading={bulkSaving} disabled={markedCount === rows.length} onClick={handleMarkAllPresent}>
              {t('Отметить всех пришедшими')}
            </Button>
          </>
        )}
      />

      {!online && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px', marginBottom: 14,
          borderRadius: 10, background: '#FEF3C7', color: '#92400E', fontSize: 12.5, fontWeight: 600,
        }}>
          <WifiOff size={15} /> {t('Нет связи — отметки не сохранятся, пока она не появится')}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(100%, 380px), 420px))', justifyContent: 'start', gap: 14 }}>
        {rows.map(row => (
          <AttendanceRow
            key={row.child}
            row={row}
            mobile={isMobile}
            saving={!!savingIds[row.child]}
            onOpenReasonPicker={() => setReasonPickerFor(row.child)}
            onMark={(statusValue, reason) => handleMark(row.child, statusValue, reason)}
            onReset={() => handleReset(row.child)}
          />
        ))}
      </div>

      {isMobile && reasonPickerRow && (
        <AbsenceReasonSheet
          childName={reasonPickerRow.child_name}
          onSelect={reason => handleMark(reasonPickerRow.child, 'absent', reason)}
          onClose={() => setReasonPickerFor(null)}
        />
      )}
    </div>
  )
}

function AttendanceRow({ row, mobile, saving, onOpenReasonPicker, onMark, onReset }) {
  const isPresent = row.status === 'present'
  const isAbsent = row.status === 'absent'
  const isMakeup = row.status === 'makeup'
  const [reasonPickerOpenDesktop, setReasonPickerOpenDesktop] = useState(false)
  const childStatus = CHILD_STATUSES[row.child_status] || { label: row.child_status, tone: 'neutral' }

  function handleAbsentClick() {
    // Телефон — шторка снизу экрана (AbsenceReasonSheet, управляется
    // родителем через reasonPickerFor); десктоп — раскрытие тут же в
    // строке, ближе к месту клика, без лишнего визуального шума модалки.
    if (mobile) onOpenReasonPicker()
    else setReasonPickerOpenDesktop(true)
  }

  const statusButtons = (
    <div style={{ display: 'flex', gap: mobile ? 8 : 6, flexShrink: 0, width: mobile ? '100%' : 'auto' }}>
      <StatusButton mobile={mobile} active={isPresent} color="#16A34A" icon={Check} label={t('Пришёл')} saving={saving} onClick={() => onMark('present')} />
      <StatusButton mobile={mobile} active={isAbsent} color="#DC2626" icon={X} label={t('Не был')} saving={saving} onClick={handleAbsentClick} />
      <StatusButton mobile={mobile} active={isMakeup} color={ACCENT} icon={RotateCcw} label={t('Отработка')} saving={saving} onClick={() => onMark('makeup')} />
      {row.status && <StatusButton mobile={mobile} active={false} color="#6B7280" icon={Undo2} label={t('Сбросить')} saving={saving} onClick={onReset} />}
    </div>
  )

  const statusNote = (
    <>
      {row._error && (
        <div style={{ fontSize: 11, color: '#DC2626', marginTop: 2 }}>
          {t('Не сохранилось — нажмите ещё раз')}
        </div>
      )}
      {!row._error && row.status === 'present' && row.consumed_from_subscription && (
        <div style={{ fontSize: 11, color: '#16A34A', marginTop: 2, display: 'flex', alignItems: 'center', gap: 3 }}>
          <Check size={11} /> {t('Списано с абонемента')}
        </div>
      )}
      {!row._error && row.status === 'present' && !row.consumed_from_subscription && row.no_subscription_flag && (
        <div style={{ fontSize: 11.5, fontWeight: 700, color: '#D97706', marginTop: 2, display: 'flex', alignItems: 'center', gap: 3 }}>
          <AlertTriangle size={12} /> {t('Нет абонемента')}
        </div>
      )}
      {!row._error && row.status === 'present' && !row.consumed_from_subscription && !row.no_subscription_flag && CONSUME_OUTCOME_LABEL[row.consume_outcome] && (
        <div style={{ fontSize: 11.5, color: '#D97706', marginTop: 2 }}>
          {t(CONSUME_OUTCOME_LABEL[row.consume_outcome])}
        </div>
      )}
      {isAbsent && row.absence_reason && (
        <div style={{ fontSize: 11, color: '#9CA3AF', marginTop: 2 }}>
          {t(ABSENCE_REASONS.find(([v]) => v === row.absence_reason)?.[1])}
        </div>
      )}
      {row.is_retroactive_edit && (
        <div
          style={{ fontSize: 11, color: '#7C6FF7', marginTop: 2, display: 'flex', alignItems: 'center', gap: 3 }}
          title={t('Отметку поменяли после того, как занятие уже прошло')}
        >
          <History size={11} /> {t('Изменено задним числом')}
        </div>
      )}
    </>
  )

  const enrollmentKind = ENROLLMENT_KIND_UI[row.enrollment_kind]
  const enrollmentBadge = enrollmentKind && (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, marginLeft: 6 }}>
      <span style={{
        fontSize: 10, fontWeight: 750, color: enrollmentKind.color,
        background: enrollmentKind.background, border: `1px solid ${enrollmentKind.border}`,
        borderRadius: 999, padding: '2px 7px', whiteSpace: 'nowrap',
      }}>
        {t(enrollmentKind.label)}
      </span>
      {row.enrollment_kind === 'trial' && row.source_lead_id && (
        <Link
          to={`/leads/${row.source_lead_id}`}
          style={{ fontSize: 10, fontWeight: 700, color: '#7C3AED', textDecoration: 'none', whiteSpace: 'nowrap' }}
        >
          {t('Открыть заявку')}
        </Link>
      )}
    </span>
  )

  return (
    <div style={{ background: '#fff', border: '1px solid #E9E7EF', borderRadius: 16, padding: 16, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, minHeight: 58 }}>
        <Avatar name={row.child_name} src={row.child_photo_url} size="md" />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#1A1A2E', display: 'flex', alignItems: 'center', flexWrap: 'wrap' }}>
            {row.child_name}{enrollmentBadge}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '3px 8px', marginTop: 3, fontSize: 11.5, color: '#8B8798' }}>
            <span title={t('Дата рождения: {date}', { date: formatDate(row.child_birth_date) })}>
              {ageLabel(row.child_age)} · {formatDate(row.child_birth_date)}
            </span>
            {CHILD_GENDER_LABEL[row.child_gender] && <span>{t(CHILD_GENDER_LABEL[row.child_gender])}</span>}
          </div>
          {statusNote}
        </div>
        <Badge tone={childStatus.tone}>{t(childStatus.label)}</Badge>
      </div>
      <div style={{ marginTop: 12 }}>{statusButtons}</div>

      {!mobile && reasonPickerOpenDesktop && (
        <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid #F0F0F5', display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {ABSENCE_REASONS.map(([value, label]) => (
            <button key={value} style={reasonChip} onClick={() => { setReasonPickerOpenDesktop(false); onMark('absent', value) }}>
              {t(label)}
            </button>
          ))}
          <button style={{ ...reasonChip, color: '#9CA3AF' }} onClick={() => setReasonPickerOpenDesktop(false)}>{t('Отмена')}</button>
        </div>
      )}
    </div>
  )
}

// Шторка снизу (TRU-51) вместо модалки в центре — большой палец достаёт
// без переноса руки, закрывается тапом по подложке.
function AbsenceReasonSheet({ childName, onSelect, onClose }) {
  return (
    <div
      onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'flex-end' }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%', background: '#fff', borderRadius: '20px 20px 0 0', padding: '20px 16px 28px',
          fontFamily: 'Manrope',
        }}
      >
        <div style={{ width: 36, height: 4, borderRadius: 2, background: '#E5E7EB', margin: '0 auto 16px' }} />
        <div style={{ fontSize: 13, color: '#9CA3AF', marginBottom: 2 }}>{t('Причина пропуска')}</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: '#1A1A2E', marginBottom: 16 }}>{childName}</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {ABSENCE_REASONS.map(([value, label]) => (
            <button key={value} style={sheetOption} onClick={() => onSelect(value)}>{t(label)}</button>
          ))}
          <button style={{ ...sheetOption, color: '#9CA3AF', border: 'none', background: 'transparent' }} onClick={onClose}>
            {t('Отмена')}
          </button>
        </div>
      </div>
    </div>
  )
}

function StatusButton({ mobile, active, color, icon: Icon, label, saving, onClick }) {
  return (
    <button
      onClick={onClick}
      disabled={saving}
      title={label}
      style={mobile ? {
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4,
        flex: 1, padding: '12px 4px', borderRadius: 12, cursor: saving ? 'default' : 'pointer',
        border: active ? `1.5px solid ${color}` : '1.5px solid #EBEBF0',
        background: active ? `${color}14` : '#fff',
        color: active ? color : '#6B7280',
        opacity: saving ? 0.6 : 1,
        fontFamily: 'Manrope', fontSize: 12, fontWeight: 700,
      } : {
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2,
        width: 58, padding: '8px 4px', borderRadius: 10, cursor: saving ? 'default' : 'pointer',
        border: active ? `1.5px solid ${color}` : '1.5px solid #EBEBF0',
        background: active ? `${color}14` : '#fff',
        color: active ? color : '#9CA3AF',
        opacity: saving ? 0.6 : 1,
        fontFamily: 'Manrope', fontSize: 10, fontWeight: 700,
      }}
    >
      <Icon size={mobile ? 20 : 16} />
      {label}
    </button>
  )
}

const backBtn = {
  display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px',
  border: '1px solid #E5E7EB', borderRadius: 8, background: '#fff',
  fontSize: 12.5, fontWeight: 600, color: '#6B7280', cursor: 'pointer', fontFamily: 'Manrope',
}

const reasonChip = {
  padding: '7px 12px', borderRadius: 20, border: '1px solid #EBEBF0', background: '#fff',
  fontSize: 12, fontWeight: 600, color: '#1A1A2E', cursor: 'pointer', fontFamily: 'Manrope',
}

const sheetOption = {
  padding: '14px 16px', borderRadius: 12, border: '1px solid #EBEBF0', background: '#fff',
  fontSize: 15, fontWeight: 600, color: '#1A1A2E', cursor: 'pointer', fontFamily: 'Manrope',
  textAlign: 'left', width: '100%',
}
